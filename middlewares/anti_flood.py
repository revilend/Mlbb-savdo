"""Anti-flood (spamga qarshi) middleware.

Foydalanuvchi yuborgan har bir `message` va `callback_query` hodisasi shu
middleware orqali filtrlanadi:

* **Sürgülü oyna** (sliding window) — belgilangan vaqt ichida ruxsat etilgan
  hodisalar soni cheklanadi.
* **Ogohlantirish** — chegara buzilganda foydalanuvchi ogohlantiriladi.
  Ogohlantirish xabari o'z-o'zidan o'chib ketadi (anti-flood bilan bir xil
  tozalash mexanizmi orqali).
* **Mute** — qayta-qayta buzgan foydalanuvchi vaqtincha cheklanadi.
* **Purge** — spam bo'lgan xabar chatdan o'chiriladi.

Middleware `Dispatcher.message` va `Dispatcher.callback_query` uchun
**outer middleware** sifatida ulanadi, shu sababli routerlar ishga
tushishidan oldin hodisani to'xtata oladi.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Deque, Dict, Optional, Set

from aiogram import BaseMiddleware
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, Message, TelegramObject, User

import config
from middlewares.self_destruct import temporary

logger = logging.getLogger(__name__)

EventHandler = Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]]

FLOOD_WARNING_TEXT = (
    "🐢 <b>Bir oz sekinroq, iltimos</b> 🙏\n\n"
    "Soʻrovlaringiz juda tez-tez kelyapti. Iltimos, {cooldown:.0f} soniya "
    "kutib, qaytadan urinib koʻring."
)

MUTE_TEXT = (
    "⏳ <b>Biroz kutish kerak</b> 🙏\n\n"
    "Qisqa vaqt ichida juda koʻp soʻrov yubordingiz, shu sababli "
    "<b>{seconds} soniya</b> kutish kerak.\n\n"
    "Bu cheklov botni himoya qiladi — iltimos, sabr qiling. Rahmat!"
)


@dataclass
class _UserState:
    """Bitta foydalanuvchi uchun anti-flood holati."""

    events: Deque[float] = field(default_factory=deque)
    violations: int = 0
    last_violation: float = 0.0
    muted_until: float = 0.0
    last_notice: float = 0.0


class AntiFloodMiddleware(BaseMiddleware):
    """Foydalanuvchi hodisalarini oyna boʻyicha cheklovchi middleware."""

    def __init__(
        self,
        *,
        window: float = 4.0,
        max_events: int = 8,
        notice_cooldown: float = 3.0,
        violation_limit: int = 3,
        mute_seconds: int = 60,
        mute_reset_seconds: int = 180,
        warning_ttl: int = 6,
        delete_flooding_messages: bool = False,
        notify: bool = True,
        bypass_user_ids: Optional[Set[int]] = None,
    ) -> None:
        self.window = max(0.5, float(window))
        self.max_events = max(1, int(max_events))
        self.notice_cooldown = max(0.0, float(notice_cooldown))
        self.violation_limit = max(1, int(violation_limit))
        self.mute_seconds = max(1, int(mute_seconds))
        self.mute_reset_seconds = max(1, int(mute_reset_seconds))
        self.warning_ttl = max(1, int(warning_ttl))
        self.delete_flooding_messages = bool(delete_flooding_messages)
        # False bo'lsa hech qanday ogohlantirish yuborilmaydi ("jimgina rejim")
        self.notify_enabled = bool(notify)
        self.bypass_user_ids: Set[int] = set(bypass_user_ids or ())

        self._states: Dict[int, _UserState] = {}
        self._calls: int = 0

    # ------------------------------------------------------------------ asosiy
    async def __call__(
        self,
        handler: EventHandler,
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        user = self._extract_user(event, data)
        if user is None or user.id in self.bypass_user_ids:
            return await handler(event, data)

        now = time.monotonic()
        state = self._states.get(user.id)
        if state is None:
            state = _UserState()
            self._states[user.id] = state

        # 1) Mute davom etayotgan bo'lsa — hodisani to'xtatamiz
        if state.muted_until > now:
            remaining = state.muted_until - now
            await self._block(
                event,
                MUTE_TEXT.format(seconds=int(remaining) + 1),
                notify=self.notify_enabled,
                alert=self.notify_enabled,
            )
            await self._purge(event)
            self._track_call(now)
            return None

        # 2) Mute tugagan bo'lsa holatni tiklaymiz
        if state.muted_until and state.muted_until <= now:
            state.muted_until = 0.0
            state.violations = 0
            state.events.clear()

        # 3) Uzoq vaqt tinch turgan foydalanuvchining hisobini nolga tushiramiz
        if state.last_violation and now - state.last_violation > self.mute_reset_seconds:
            state.violations = 0
            state.last_violation = 0.0
            state.events.clear()

        # 4) Oynadan chiqib ketgan hodisalarni olib tashlaymiz
        while state.events and now - state.events[0] > self.window:
            state.events.popleft()

        # 5) Chegaradan oshgan bo'lsa
        if len(state.events) >= self.max_events:
            state.violations += 1
            state.last_violation = now

            muted = state.violations >= self.violation_limit
            if muted:
                state.muted_until = now + self.mute_seconds
                state.violations = 0
                state.events.clear()
                text = MUTE_TEXT.format(seconds=self.mute_seconds)
            else:
                text = FLOOD_WARNING_TEXT.format(cooldown=self.window)

            should_notify = muted or (now - state.last_notice >= self.notice_cooldown)
            if should_notify:
                state.last_notice = now

            logger.info(
                "Anti-flood: user=%s hodisalar=%s buzilish=%s mute=%s",
                user.id,
                len(state.events),
                state.violations,
                muted,
            )

            await self._block(
                event,
                text,
                notify=should_notify and self.notify_enabled,
                alert=muted and self.notify_enabled,
            )
            await self._purge(event)
            self._track_call(now)
            return None

        # 6) Ruxsat etilgan hodisa
        state.events.append(now)
        self._track_call(now)
        return await handler(event, data)

    # --------------------------------------------------------------- yordamchi
    @staticmethod
    def _extract_user(event: TelegramObject, data: Dict[str, Any]) -> Optional[User]:
        """Hodisa egasini aniqlaydi."""
        user = data.get("event_from_user")
        if isinstance(user, User):
            return user
        candidate = getattr(event, "from_user", None)
        return candidate if isinstance(candidate, User) else None

    async def _block(
        self,
        event: TelegramObject,
        text: str,
        *,
        notify: bool,
        alert: bool,
    ) -> None:
        """Foydalanuvchiga cheklov haqida xabar beradi.

        Callback soʻrovlar har qanday holatda javob olishi shart, aks holda
        Telegram mijozida "aylanayotgan yuklanish" belgisi qolib ketadi.
        """
        try:
            if isinstance(event, CallbackQuery):
                await event.answer(text if notify else None, show_alert=alert and notify)
            elif isinstance(event, Message):
                if notify:
                    with temporary(self.warning_ttl):
                        await event.answer(text, disable_web_page_preview=True)
        except TelegramAPIError as exc:
            logger.debug("Anti-flood javobini yuborib boʻlmadi: %s", exc)

    async def _purge(self, event: TelegramObject) -> None:
        """Spam boʻlgan xabarni chatdan oʻchiradi."""
        if not self.delete_flooding_messages or not isinstance(event, Message):
            return
        try:
            await event.delete()
        except TelegramAPIError as exc:
            logger.debug("Spam xabarni oʻchirib boʻlmadi: %s", exc)

    def _track_call(self, now: float) -> None:
        """Vaqti-vaqti bilan ishlatilmayotgan holatlarni tozalaydi (xotira oqmasligi uchun)."""
        self._calls += 1
        if self._calls % 512 != 0:
            return
        for user_id, state in list(self._states.items()):
            idle = not state.events
            expired = (
                not state.last_violation
                or now - state.last_violation > self.mute_reset_seconds
            )
            if idle and expired and state.muted_until <= now:
                self._states.pop(user_id, None)

    # ------------------------------------------------------------------ holat
    def active_users(self) -> int:
        """Kuzatilayotgan foydalanuvchilar soni."""
        return len(self._states)

    def mute_remaining(self, user_id: int) -> int:
        """Foydalanuvchi uchun qolgan mute vaqti (sekund)."""
        state = self._states.get(user_id)
        if state is None:
            return 0
        remaining = state.muted_until - time.monotonic()
        return max(0, int(remaining) + 1)

    def reset(self, user_id: Optional[int] = None) -> None:
        """Holatni tozalaydi (bitta foydalanuvchi yoki hammasi uchun)."""
        if user_id is None:
            self._states.clear()
            return
        self._states.pop(user_id, None)


def build_anti_flood() -> Optional[AntiFloodMiddleware]:
    """Konfiguratsiyaga asoslanib middleware yaratadi (oʻchirilgan boʻlsa `None`)."""
    if not config.FLOOD_PROTECTION:
        return None

    bypass: Set[int] = set()
    if config.FLOOD_BYPASS_ADMIN and config.ADMIN_ID:
        bypass.add(config.ADMIN_ID)

    return AntiFloodMiddleware(
        window=config.FLOOD_WINDOW_SECONDS,
        max_events=config.FLOOD_MAX_EVENTS,
        notice_cooldown=config.FLOOD_NOTICE_COOLDOWN,
        violation_limit=config.FLOOD_VIOLATION_LIMIT,
        mute_seconds=config.FLOOD_MUTE_SECONDS,
        mute_reset_seconds=config.FLOOD_MUTE_RESET_SECONDS,
        warning_ttl=config.FLOOD_WARNING_TTL,
        delete_flooding_messages=config.FLOOD_DELETE_MESSAGES,
        notify=config.FLOOD_NOTIFY,
        bypass_user_ids=bypass,
    )


__all__ = ["AntiFloodMiddleware", "build_anti_flood"]
