"""O'z-o'zini o'chiruvchi xabarlar (self-destruct) va chat tozalagichi.

Arxitektura:

1. :class:`SelfDestructMiddleware` — **session darajasidagi** middleware.
   U Telegram API'ga yuborilgan har bir so'rovni ushlaydi va javob
   xabar(lar)ni ro'yxatga olib, belgilangan vaqtdan keyin o'chiradi.
   Bu yagona ishonchli joy, chunki barcha yuborish yo'llari
   (`send_message`, `send_photo`, `send_media_group`, `copy_message`, …)
   shu yerdan o'tadi.

2. :class:`MessageRegistry` — chat bo'yicha yuborilgan xabarlar tarixi.
   `/clean` buyrug'i shu tarix asosida chatni bir zumda tozalaydi.

3. :func:`temporary` va :func:`permanent` — handler ichida TTL ni
   boshqarish uchun kontekst menejerlari (contextvars orqali ishlaydi,
   shuning uchun bir vaqtda ishlayotgan boshqa handlerlarga ta'sir qilmaydi).

Xavfsizlik qoidalari:

* **Kanallar va guruhlar** (`chat_id < 0`) hech qachon tozalanmaydi —
  kanalga joylangan eʼlonlar o'chib ketmasligi kerak.
* `SELF_DESTRUCT_SKIP_CHAT_IDS` (masalan administrator chati) butunlay
  chetlab o'tiladi.
* `permanent()` bilan belgilangan xabarlar saqlanib qoladi.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict, deque
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Deque, Dict, Iterator, List, Optional, Sequence, Set

from aiogram import BaseMiddleware, Bot
from aiogram.client.session.middlewares.base import BaseRequestMiddleware
from aiogram.exceptions import TelegramAPIError
from aiogram.types import Message, TelegramObject
from aiogram.methods import (
    CopyMessage,
    ForwardMessage,
    SendAnimation,
    SendAudio,
    SendContact,
    SendDice,
    SendDocument,
    SendLocation,
    SendMediaGroup,
    SendMessage,
    SendPhoto,
    SendPoll,
    SendSticker,
    SendVenue,
    SendVideo,
    SendVideoNote,
    SendVoice,
)

import config

logger = logging.getLogger(__name__)

#: Xabar qaytaradigan (va demak o'chirilishi mumkin bo'lgan) metodlar
SEND_METHODS: tuple = (
    SendMessage,
    SendPhoto,
    SendVideo,
    SendAnimation,
    SendDocument,
    SendAudio,
    SendVoice,
    SendVideoNote,
    SendSticker,
    SendMediaGroup,
    SendLocation,
    SendVenue,
    SendContact,
    SendDice,
    SendPoll,
    CopyMessage,
    ForwardMessage,
)

# Kontekstga bog'liq TTL: None — umumiy sozlamadan foydalaniladi
_ttl_override: ContextVar[Optional[int]] = ContextVar("self_destruct_ttl", default=None)
# Kontekstga bog'liq "o'chirmaslik" belgisi
_keep_forever: ContextVar[bool] = ContextVar("self_destruct_keep", default=False)


# ---------------------------------------------------------------------------
# Kontekst menejerlari
# ---------------------------------------------------------------------------
@contextmanager
def temporary(seconds: Optional[int] = None) -> Iterator[None]:
    """Shu blok ichida yuborilgan xabarlarni ``seconds`` soniyadan keyin o'chiradi.

    >>> with temporary(10):
    ...     await message.answer("Bu xabar 10 soniyadan keyin o'chadi")
    """
    value = config.SELF_DESTRUCT_NOTICE_TTL if seconds is None else int(seconds)
    token = _ttl_override.set(max(1, value))
    try:
        yield
    finally:
        _ttl_override.reset(token)


@contextmanager
def permanent() -> Iterator[None]:
    """Shu blok ichida yuborilgan xabarlar hech qachon o'chirilmaydi.

    >>> with permanent():
    ...     await message.answer("Bu xabar doim qoladi")
    """
    token = _keep_forever.set(True)
    try:
        yield
    finally:
        _keep_forever.reset(token)


# ---------------------------------------------------------------------------
# Xabarlar reyestri
# ---------------------------------------------------------------------------
class MessageRegistry:
    """Chat bo'yicha bot yuborgan xabarlar tarixini saqlaydi."""

    def __init__(self, limit: int = 40) -> None:
        self.limit = max(1, int(limit))
        self._store: Dict[int, Deque[int]] = defaultdict(self._new_bucket)

    def _new_bucket(self) -> Deque[int]:
        return deque(maxlen=self.limit)

    def add(self, chat_id: int, message_id: int) -> None:
        """Xabarni tarixga qo'shadi."""
        if not isinstance(chat_id, int) or not isinstance(message_id, int):
            return
        bucket = self._store[chat_id]
        if message_id in bucket:
            return
        bucket.append(message_id)

    def forget(self, chat_id: int, message_id: int) -> None:
        """Xabarni tarixdan olib tashlaydi."""
        bucket = self._store.get(chat_id)
        if not bucket:
            return
        try:
            bucket.remove(message_id)
        except ValueError:
            return
        if not bucket:
            self._store.pop(chat_id, None)

    def take(self, chat_id: int) -> List[int]:
        """Tarixdagi barcha xabar ID larini qaytaradi va tarixni tozalaydi."""
        bucket = self._store.pop(chat_id, None)
        return list(bucket) if bucket else []

    def peek(self, chat_id: int) -> List[int]:
        """Tarixni tozalamasdan ko'rish."""
        return list(self._store.get(chat_id, ()))

    def count(self, chat_id: int) -> int:
        """Chatdagi kuzatilayotgan xabarlar soni."""
        return len(self._store.get(chat_id, ()))

    def total_chats(self) -> int:
        """Tarix yuritilayotgan chatlar soni."""
        return len(self._store)

    def clear(self) -> None:
        """Butun tarixni tozalaydi."""
        self._store.clear()


#: Global reyestr — middleware yozadi, handlerlar o'qiydi
messages = MessageRegistry(limit=config.CLEANER_TRACK_LIMIT)


# ---------------------------------------------------------------------------
# Session darajasidagi middleware
# ---------------------------------------------------------------------------
class SelfDestructMiddleware(BaseRequestMiddleware):
    """Yuborilgan xabarlarni belgilangan vaqtdan keyin avtomatik o'chiradi."""

    def __init__(
        self,
        *,
        enabled: bool = True,
        default_ttl: int = 300,
        registry: Optional[MessageRegistry] = None,
        skip_chat_ids: Sequence[int] = (),
        max_pending_tasks: int = 2000,
        delete_user_messages: bool = False,
    ) -> None:
        self.enabled = bool(enabled)
        self.default_ttl = max(0, int(default_ttl))
        self.registry = registry if registry is not None else messages
        self.skip_chat_ids: Set[int] = {int(cid) for cid in skip_chat_ids}
        self.max_pending_tasks = max(10, int(max_pending_tasks))
        self.delete_user_messages = bool(delete_user_messages)

        self._tasks: Set[asyncio.Task] = set()
        self.deleted_count = 0

    # ------------------------------------------------------------------ asosiy
    async def __call__(self, make_request, bot: Bot, method: Any) -> Any:
        """So'rovni bajaradi va natijadagi xabarlarni rejalashtiradi."""
        result = await make_request(bot, method)
        if not self.enabled:
            return result
        try:
            self._schedule(bot, method, result)
        except Exception:  # tozalash hech qachon asosiy oqimni buzmasligi kerak
            logger.exception("Self-destruct rejalashtirishda kutilmagan xatolik")
        return result

    def _schedule(self, bot: Bot, method: Any, result: Any) -> None:
        """Natijadagi xabarlarni ro'yxatga oladi va o'chirishni rejalashtiradi."""
        if not isinstance(method, SEND_METHODS):
            return

        chat_id = getattr(method, "chat_id", None)
        if not isinstance(chat_id, int):
            return

        # Kanallar va guruhlar (manfiy ID) hamda istisno qilingan chatlar tegilmaydi
        if chat_id < 0 or chat_id in self.skip_chat_ids:
            return

        keep = _keep_forever.get()
        ttl = _ttl_override.get()
        if ttl is None:
            ttl = self.default_ttl

        for message_id in self._message_ids(result):
            self.registry.add(chat_id, message_id)
            if keep or ttl <= 0:
                continue
            self._spawn_delete(bot, chat_id, message_id, ttl)

    @staticmethod
    def _message_ids(result: Any) -> List[int]:
        """API javobidan xabar ID larini ajratib oladi."""
        if result is None:
            return []
        items = result if isinstance(result, (list, tuple)) else [result]
        ids: List[int] = []
        for item in items:
            message_id = getattr(item, "message_id", None)
            if isinstance(message_id, int):
                ids.append(message_id)
        return ids

    def _spawn_delete(self, bot: Bot, chat_id: int, message_id: int, delay: int) -> None:
        """O'chirish vazifasini fon rejimida ishga tushiradi."""
        if len(self._tasks) >= self.max_pending_tasks:
            logger.warning("Self-destruct navbati toʻldi, xabar saqlanib qoldi: %s", message_id)
            return
        task = asyncio.create_task(
            self._delete_later(bot, chat_id, message_id, delay),
            name=f"self-destruct:{chat_id}:{message_id}",
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _delete_later(self, bot: Bot, chat_id: int, message_id: int, delay: int) -> None:
        """Belgilangan vaqtdan keyin xabarni o'chiradi."""
        try:
            await asyncio.sleep(delay)
            await bot.delete_message(chat_id=chat_id, message_id=message_id)
            self.deleted_count += 1
            self.registry.forget(chat_id, message_id)
        except asyncio.CancelledError:
            raise
        except TelegramAPIError as exc:
            # Xabar allaqachon oʻchirilgan yoki 48 soatdan eski boʻlishi mumkin
            logger.debug("Xabarni oʻchirib boʻlmadi (%s/%s): %s", chat_id, message_id, exc)
            self.registry.forget(chat_id, message_id)
        except Exception as exc:  # pragma: no cover — kutilmagan holatlar
            logger.debug("Self-destruct vazifasida xatolik: %s", exc)

    # ------------------------------------------------------------------ boshqa
    @property
    def pending(self) -> int:
        """Navbatdagi o'chirish vazifalari soni."""
        return len(self._tasks)

    async def shutdown(self) -> None:
        """Barcha kutilayotgan o'chirish vazifalarini bekor qiladi."""
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()

    def track_user_message(self, chat_id: int, message_id: int, ttl: Optional[int] = None) -> int:
        """Foydalanuvchi xabarini ham tozalash ro'yxatiga qo'shadi.

        Faqat `SELF_DESTRUCT_USER_MESSAGES` yoqilgan bo'lsa ishlaydi.
        """
        if not self.delete_user_messages:
            return 0
        delay = self.default_ttl if ttl is None else int(ttl)
        if delay <= 0:
            return 0
        self.registry.add(chat_id, message_id)
        return delay


# ---------------------------------------------------------------------------
# Foydalanuvchi xabarlarini tozalash (ixtiyoriy)
# ---------------------------------------------------------------------------
class UserMessageCleanerMiddleware(BaseMiddleware):
    """Foydalanuvchi yuborgan xabarlarni ham vaqtincha qiladi.

    Standart holatda **oʻchirilgan**. Yoqish uchun `.env` faylida
    ``SELF_DESTRUCT_USER_MESSAGES=true`` qilib belgilang — bu holda
    chat butunlay toza turishini taʼminlaydi.
    """

    def __init__(
        self,
        *,
        ttl: int = 600,
        skip_chat_ids: Sequence[int] = (),
        min_ttl: int = 10,
    ) -> None:
        self.ttl = max(min_ttl, int(ttl))
        self.skip_chat_ids: Set[int] = {int(cid) for cid in skip_chat_ids}
        self._tasks: Set[asyncio.Task] = set()

    async def __call__(
        self,
        handler: Any,
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        result = await handler(event, data)

        bot = data.get("bot")
        if not isinstance(event, Message) or not isinstance(bot, Bot):
            return result

        chat_id = getattr(event.chat, "id", None)
        if not isinstance(chat_id, int) or chat_id <= 0 or chat_id in self.skip_chat_ids:
            return result

        task = asyncio.create_task(
            self._cleanup(bot, chat_id, event.message_id),
            name=f"user-cleanup:{chat_id}:{event.message_id}",
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return result

    async def _cleanup(self, bot: Bot, chat_id: int, message_id: int) -> None:
        try:
            await asyncio.sleep(self.ttl)
            await bot.delete_message(chat_id=chat_id, message_id=message_id)
        except asyncio.CancelledError:
            raise
        except TelegramAPIError as exc:
            logger.debug("Foydalanuvchi xabari oʻchirilmadi (%s): %s", message_id, exc)

    async def shutdown(self) -> None:
        """Kutilayotgan vazifalarni bekor qiladi."""
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()


# ---------------------------------------------------------------------------
# Yordamchi funksiyalar
# ---------------------------------------------------------------------------
async def delete_later(bot: Bot, chat_id: int, message_id: int, delay: int) -> None:
    """Bitta xabarni ``delay`` soniyadan keyin o'chiradi (fon vazifasi)."""
    try:
        await asyncio.sleep(max(1, int(delay)))
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except asyncio.CancelledError:
        raise
    except TelegramAPIError as exc:
        logger.debug("Xabarni oʻchirib boʻlmadi (%s/%s): %s", chat_id, message_id, exc)


async def delete_silently(bot: Bot, chat_id: int, message_id: Optional[int]) -> bool:
    """Xabarni darhol va jimgina o'chiradi."""
    if not message_id:
        return False
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
        return True
    except TelegramAPIError:
        return False


async def sweep_chat(
    bot: Bot,
    chat_id: int,
    registry: Optional[MessageRegistry] = None,
    *,
    limit: int = 120,
    pause: float = 0.04,
) -> int:
    """Chatdagi bot xabarlarini bir zumda tozalaydi.

    Qaytaradi: muvaffaqiyatli o'chirilgan xabarlar soni.
    """
    registry = registry or messages
    message_ids = registry.take(chat_id)[:limit]
    if not message_ids:
        return 0

    deleted = 0
    for message_id in message_ids:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=message_id)
            deleted += 1
        except TelegramAPIError:
            # 48 soatdan eski yoki allaqachon o'chirilgan xabarlar
            continue
        await asyncio.sleep(pause)
    return deleted


def cleanup_registry(registry: Optional[MessageRegistry] = None) -> None:
    """Reyestrni tozalaydi (test va qayta ishga tushirish uchun)."""
    (registry or messages).clear()


__all__ = [
    "MessageRegistry",
    "SelfDestructMiddleware",
    "UserMessageCleanerMiddleware",
    "delete_later",
    "delete_silently",
    "messages",
    "permanent",
    "sweep_chat",
    "temporary",
    "cleanup_registry",
]
