"""Self-destruct (TTL) mantiqi uchun testlar.

Qamrov:

* `temporary()` / `permanent()` kontekst menejerlari va ularning ustuvorligi
* `MessageRegistry` (add / forget / take / peek / count / cheklov)
* `SelfDestructMiddleware` rejalashtirish qoidalari:
  - shaxsiy chat ✅ / kanal va guruh ❌
  - `skip_chat_ids` ❌
  - `default_ttl = 0` (faqat kuzatish)
  - yuborish bo'lmagan metodlar ❌
  - media-guruh natijasi (ro'yxat) ✅
* haqiqiy o'chirish, xatolarga chidamlilik, `shutdown()`
* session middleware zanjiri orqali to'liq integratsiya
* `sweep_chat()` (`/clean` uchun)
* `UserMessageCleanerMiddleware`
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError
from aiogram.methods import (
    DeleteMessage,
    SendChatAction,
    SendMediaGroup,
    SendMessage,
    SendPhoto,
)
from conftest import FakeResult, USER_ID, make_message, make_user
from middlewares.self_destruct import (
    MessageRegistry,
    SelfDestructMiddleware,
    UserMessageCleanerMiddleware,
    LatestMenuMiddleware,
    delete_later,
    delete_silently,
    messages as global_registry,
    permanent,
    replace_previous,
    sweep_chat,
    temporary,
)


# ---------------------------------------------------------------------------
# temporary() / permanent()
# ---------------------------------------------------------------------------
def test_temporary_sets_and_resets_override():
    """`temporary()` TTL ni faqat blok ichida o'zgartiradi."""
    from middlewares.self_destruct import _ttl_override, _keep_forever

    assert _ttl_override.get() is None
    with temporary(7):
        assert _ttl_override.get() == 7
    assert _ttl_override.get() is None

    with temporary(0):
        assert _ttl_override.get() == 1, "TTL kamida 1 sekund bo'lishi kerak"


def test_temporary_resets_on_exception():
    """Xatolik bo'lsa ham kontekst tiklanadi."""
    from middlewares.self_destruct import _ttl_override

    with pytest.raises(ValueError):
        with temporary(3):
            raise ValueError("boom")

    assert _ttl_override.get() is None


def test_permanent_sets_and_resets_flag():
    """`permanent()` belgisi blokdan chiqqach o'chadi."""
    from middlewares.self_destruct import _keep_forever

    assert _keep_forever.get() is False
    with permanent():
        assert _keep_forever.get() is True
    assert _keep_forever.get() is False


def test_contexts_are_nested():
    """Ichki `permanent()` tashqi `temporary()` ustidan turadi."""
    from middlewares.self_destruct import _keep_forever, _ttl_override

    with temporary(5):
        assert _ttl_override.get() == 5
        with permanent():
            assert _keep_forever.get() is True
        assert _keep_forever.get() is False
        assert _ttl_override.get() == 5, "ichki blok tashqi TTL ni buzmasligi kerak"
    assert _ttl_override.get() is None


# ---------------------------------------------------------------------------
# MessageRegistry
# ---------------------------------------------------------------------------
def test_registry_add_and_count():
    """Xabarlar qo'shiladi va sanaladi."""
    registry = MessageRegistry(limit=5)
    registry.add(1, 10)
    registry.add(1, 11)
    registry.add(2, 20)

    assert registry.count(1) == 2
    assert registry.count(2) == 1
    assert registry.count(3) == 0
    assert registry.total_chats() == 2


def test_registry_ignores_duplicates_and_invalid_values():
    """Takroriy va noto'g'ri qiymatlar hisobga olinmaydi."""
    registry = MessageRegistry(limit=5)
    registry.add(1, 10)
    registry.add(1, 10)
    registry.add(1, "10")  # type: ignore[arg-type]
    registry.add("x", 10)  # type: ignore[arg-type]

    assert registry.count(1) == 1


def test_registry_respects_limit():
    """Eski xabarlar chegaradan oshgach tushib qoladi."""
    registry = MessageRegistry(limit=3)
    for message_id in range(10, 15):
        registry.add(1, message_id)

    assert registry.count(1) == 3
    assert registry.peek(1) == [12, 13, 14]


def test_registry_forget_and_take():
    """`forget()` bitta xabarni, `take()` hammasini olib tashlaydi."""
    registry = MessageRegistry(limit=5)
    registry.add(1, 10)
    registry.add(1, 11)

    registry.forget(1, 10)
    assert registry.peek(1) == [11]

    registry.forget(1, 999)  # mavjud emas — xatolik bermasligi kerak
    assert registry.peek(1) == [11]

    assert registry.take(1) == [11]
    assert registry.count(1) == 0
    assert registry.take(1) == []


def test_registry_clear():
    """`clear()` butun tarixni o'chiradi."""
    registry = MessageRegistry(limit=5)
    registry.add(1, 10)
    registry.add(2, 20)
    registry.clear()

    assert registry.total_chats() == 0


def test_global_registry_exists():
    """Handlerlar ishlatadigan global reyestr mavjud."""
    assert isinstance(global_registry, MessageRegistry)


# ---------------------------------------------------------------------------
# Rejalashtirish qoidalari
# ---------------------------------------------------------------------------
@pytest.fixture
def registry() -> MessageRegistry:
    """Har bir test uchun toza reyestr."""
    return MessageRegistry(limit=10)


@pytest.fixture
def middleware(registry: MessageRegistry) -> SelfDestructMiddleware:
    """Standart sozlamali self-destruct middleware."""
    return SelfDestructMiddleware(default_ttl=300, registry=registry)


async def test_schedules_message_in_private_chat(middleware, registry):
    """Shaxsiy chatdagi xabar o'chirishga qo'yiladi."""
    middleware._schedule(MagicMock(), SendMessage(chat_id=USER_ID, text="salom"), FakeResult(42))

    assert registry.count(USER_ID) == 1
    assert middleware.pending == 1

    await middleware.shutdown()


def test_never_schedules_for_channels_and_groups(middleware, registry):
    """Kanal va guruhlar (manfiy ID) hech qachon tozalanmaydi."""
    for chat_id in (-1001234567890, -987654321):
        middleware._schedule(MagicMock(), SendMessage(chat_id=chat_id, text="post"), FakeResult(1))

    assert registry.total_chats() == 0
    assert middleware.pending == 0


def test_skip_chat_ids_are_honoured(registry):
    """`skip_chat_ids` ro'yxatidagi chatlar chetlab o'tiladi."""
    middleware = SelfDestructMiddleware(default_ttl=300, registry=registry, skip_chat_ids={USER_ID})
    middleware._schedule(MagicMock(), SendMessage(chat_id=USER_ID, text="x"), FakeResult(1))

    assert registry.count(USER_ID) == 0
    assert middleware.pending == 0


def test_permanent_block_disables_scheduling(middleware, registry):
    """`permanent()` ichida yuborilgan xabar saqlanadi, lekin kuzatiladi."""
    with permanent():
        middleware._schedule(MagicMock(), SendMessage(chat_id=USER_ID, text="x"), FakeResult(1))

    assert registry.count(USER_ID) == 1, "kuzatuv davom etadi"
    assert middleware.pending == 0, "o'chirish rejalashtirilmaydi"


async def test_temporary_overrides_default_ttl(middleware, registry):
    """`temporary()` umumiy TTL ni almashtiradi."""
    with temporary(5):
        middleware._schedule(MagicMock(), SendMessage(chat_id=USER_ID, text="x"), FakeResult(1))

    assert middleware.pending == 1

    await middleware.shutdown()


def test_zero_ttl_only_tracks(registry):
    """`default_ttl = 0` bo'lsa faqat kuzatiladi (o'chirilmaydi)."""
    middleware = SelfDestructMiddleware(default_ttl=0, registry=registry)
    middleware._schedule(MagicMock(), SendMessage(chat_id=USER_ID, text="x"), FakeResult(1))

    assert registry.count(USER_ID) == 1
    assert middleware.pending == 0


def test_non_send_methods_are_ignored(middleware, registry):
    """`sendChatAction` kabi metodlar xabar qaytarmaydi — tegmaymiz."""
    middleware._schedule(MagicMock(), SendChatAction(chat_id=USER_ID, action="typing"), True)

    assert registry.total_chats() == 0
    assert middleware.pending == 0


def test_delete_message_is_not_re_scheduled(middleware, registry):
    """`deleteMessage` rekursiya keltirib chiqarmasligi kerak."""
    middleware._schedule(MagicMock(), DeleteMessage(chat_id=USER_ID, message_id=1), True)

    assert middleware.pending == 0


async def test_media_group_schedules_every_message(middleware, registry):
    """Media-guruh natijasi (ro'yxat) — barcha xabarlar rejalashtiriladi."""
    result = [FakeResult(100), FakeResult(101), FakeResult(102)]
    middleware._schedule(MagicMock(), SendMediaGroup(chat_id=USER_ID, media=[]), result)

    assert registry.count(USER_ID) == 3
    assert middleware.pending == 3

    await middleware.shutdown()


def test_result_without_message_id_is_ignored(middleware, registry):
    """Xabar ID si bo'lmagan javob o'tkazib yuboriladi."""
    middleware._schedule(MagicMock(), SendMessage(chat_id=USER_ID, text="x"), True)
    middleware._schedule(MagicMock(), SendMessage(chat_id=USER_ID, text="x"), None)

    assert registry.total_chats() == 0


async def test_photo_messages_are_scheduled(middleware, registry):
    """`sendPhoto` ham qamrab olinadi."""
    middleware._schedule(MagicMock(), SendPhoto(chat_id=USER_ID, photo="file-id"), FakeResult(7))

    assert registry.peek(USER_ID) == [7]

    await middleware.shutdown()


async def test_disabled_middleware_does_nothing(registry):
    """`enabled=False` bo'lsa hech narsa kuzatilmaydi."""
    middleware = SelfDestructMiddleware(enabled=False, default_ttl=300, registry=registry)

    async def make_request(bot: Any, method: Any, timeout: Optional[int] = None) -> Any:
        return FakeResult(1)

    await middleware(make_request, MagicMock(), SendMessage(chat_id=USER_ID, text="x"))

    assert registry.total_chats() == 0


# ---------------------------------------------------------------------------
# O'chirish jarayoni
# ---------------------------------------------------------------------------
async def test_delete_later_removes_message(middleware, registry):
    """`_delete_later` xabarni o'chiradi va reyestrdan chiqaradi."""
    calls: list[tuple[int, int]] = []

    async def fake_delete(chat_id: int, message_id: int, **kwargs: Any) -> bool:
        calls.append((chat_id, message_id))
        return True

    bot = MagicMock()
    bot.delete_message = fake_delete
    registry.add(USER_ID, 42)

    await middleware._delete_later(bot, USER_ID, 42, 0)

    assert calls == [(USER_ID, 42)]
    assert registry.count(USER_ID) == 0
    assert middleware.deleted_count == 1


async def test_delete_later_tolerates_telegram_error(middleware, registry):
    """Xabar allaqachon o'chirilgan bo'lsa xatolik yutiladi."""
    bot = MagicMock()
    bot.delete_message = AsyncMock(
        side_effect=TelegramForbiddenError(method=MagicMock(), message="not found")
    )
    registry.add(USER_ID, 42)

    await middleware._delete_later(bot, USER_ID, 42, 0)

    assert registry.count(USER_ID) == 0
    assert middleware.deleted_count == 0


async def test_delete_later_handles_unexpected_error(middleware, registry):
    """Kutilmagan xatolik ham asosiy oqimni buzmaydi."""
    bot = MagicMock()
    bot.delete_message = AsyncMock(side_effect=RuntimeError("boom"))

    await middleware._delete_later(bot, USER_ID, 42, 0)  # xatolik ko'tarilmaydi


async def test_shutdown_cancels_pending_tasks(middleware):
    """`shutdown()` kutilayotgan vazifalarni bekor qiladi."""
    middleware._schedule(MagicMock(), SendMessage(chat_id=USER_ID, text="x"), FakeResult(1))
    assert middleware.pending == 1

    await middleware.shutdown()

    assert middleware.pending == 0


async def test_pending_task_limit(registry):
    """Navbat chegarasi oshsa yangi vazifa qo'shilmaydi."""
    middleware = SelfDestructMiddleware(default_ttl=600, registry=registry, max_pending_tasks=10)
    for message_id in range(30):
        middleware._schedule(MagicMock(), SendMessage(chat_id=USER_ID, text="x"), FakeResult(message_id + 1))

    assert middleware.pending <= 10
    await middleware.shutdown()


# ---------------------------------------------------------------------------
# Session zanjiri orqali integratsiya
# ---------------------------------------------------------------------------
async def test_session_middleware_integration(bot: Bot, registry: MessageRegistry):
    """`Bot.session` zanjiriga ulanganda xabarlarni ushlab oladi."""
    middleware = SelfDestructMiddleware(default_ttl=300, registry=registry)
    bot.session.middleware(middleware)

    async def fake_make_request(bot_: Bot, method: Any, timeout: Optional[int] = None) -> Any:
        if isinstance(method, SendMediaGroup):
            return [FakeResult(100), FakeResult(101)]
        return FakeResult(42)

    wrapped = bot.session.middleware.wrap_middlewares(fake_make_request)

    await wrapped(bot, SendMessage(chat_id=USER_ID, text="salom"))
    assert registry.peek(USER_ID) == [42]

    await wrapped(bot, SendMessage(chat_id=-100999, text="kanal posti"))
    assert registry.total_chats() == 1, "kanal tegilmasligi kerak"

    await wrapped(bot, SendMediaGroup(chat_id=USER_ID, media=[]))
    assert registry.count(USER_ID) == 3
    assert middleware.pending == 3

    await middleware.shutdown()


async def test_session_middleware_returns_api_result(bot: Bot, registry: MessageRegistry):
    """Middleware API javobini o'zgartirmasdan qaytaradi."""
    middleware = SelfDestructMiddleware(default_ttl=0, registry=registry)
    bot.session.middleware(middleware)
    expected = FakeResult(7)

    async def fake_make_request(bot_: Bot, method: Any, timeout: Optional[int] = None) -> Any:
        return expected

    wrapped = bot.session.middleware.wrap_middlewares(fake_make_request)
    assert await wrapped(bot, SendMessage(chat_id=USER_ID, text="x")) is expected


# ---------------------------------------------------------------------------
# sweep_chat / delete_silently
# ---------------------------------------------------------------------------
async def test_sweep_chat_deletes_tracked_messages(registry):
    """`sweep_chat()` reyestrdagi barcha xabarlarni o'chiradi."""
    calls: list[tuple[int, int]] = []

    async def fake_delete(chat_id: int, message_id: int, **kwargs: Any) -> bool:
        calls.append((chat_id, message_id))
        return True

    bot = MagicMock()
    bot.delete_message = fake_delete
    for message_id in (10, 11, 12):
        registry.add(USER_ID, message_id)

    deleted = await sweep_chat(bot, USER_ID, registry, pause=0.0)

    assert deleted == 3
    assert sorted(calls) == [(USER_ID, 10), (USER_ID, 11), (USER_ID, 12)]
    assert registry.count(USER_ID) == 0


async def test_sweep_chat_ignores_errors(registry):
    """O'chirib bo'lmaydigan xabarlar hisobga olinmaydi, qolganlari o'chadi."""
    bot = MagicMock()
    bot.delete_message = AsyncMock(
        side_effect=[
            TelegramForbiddenError(method=MagicMock(), message="too old"),
            True,
        ]
    )
    registry.add(USER_ID, 10)
    registry.add(USER_ID, 11)

    assert await sweep_chat(bot, USER_ID, registry, pause=0.0) == 1


async def test_sweep_empty_chat_returns_zero(registry):
    """Bo'sh chat uchun API chaqirilmaydi."""
    bot = MagicMock()
    bot.delete_message = AsyncMock()
    assert await sweep_chat(bot, USER_ID, registry) == 0
    bot.delete_message.assert_not_awaited()


async def test_delete_silently():
    """`delete_silently()` xatolarni yutadi."""
    bot = MagicMock()
    bot.delete_message = AsyncMock(return_value=True)

    assert await delete_silently(bot, USER_ID, 5) is True
    assert await delete_silently(bot, USER_ID, None) is False

    bot.delete_message = AsyncMock(
        side_effect=TelegramForbiddenError(method=MagicMock(), message="nope")
    )
    assert await delete_silently(bot, USER_ID, 6) is False


async def test_delete_later_helper():
    """Modul darajasidagi `delete_later()` yordamchisi ishlaydi."""
    bot = MagicMock()
    calls: list[tuple[int, int]] = []

    async def fake_delete(chat_id: int, message_id: int, **kwargs: Any) -> bool:
        calls.append((chat_id, message_id))
        return True

    bot.delete_message = fake_delete
    await delete_later(bot, USER_ID, 99, 0)

    assert calls == [(USER_ID, 99)]


async def test_latest_menu_middleware_cleans_previous_private_messages(bot, registry):
    """Menyu tugmasi eski javobni o'chirib, yangisini qoldiradi."""
    middleware = SelfDestructMiddleware(registry=registry)
    calls: list[tuple[int, int]] = []

    async def fake_delete(chat_id: int, message_id: int, **kwargs: Any) -> bool:
        calls.append((chat_id, message_id))
        return True

    bot.delete_message = fake_delete  # type: ignore[method-assign]
    registry.add(USER_ID, 10)
    registry.add(USER_ID, 11)

    with replace_previous():
        await middleware._replace_previous_bot_messages(
            bot, SendMessage(chat_id=USER_ID, text="javob")
        )

    assert calls == [(USER_ID, 10), (USER_ID, 11)]
    assert registry.count(USER_ID) == 0
    await middleware.shutdown()


async def test_latest_menu_middleware_keeps_group_messages(bot, registry):
    """Guruhdagi eski xabarlar tozalanmaydi."""
    middleware = SelfDestructMiddleware(registry=registry)
    registry.add(-100123, 10)

    with replace_previous():
        await middleware._replace_previous_bot_messages(
            bot, SendMessage(chat_id=-100123, text="javob")
        )

    assert registry.count(-100123) == 1


# ---------------------------------------------------------------------------
# UserMessageCleanerMiddleware
# ---------------------------------------------------------------------------
async def test_user_cleaner_skips_channels_and_groups(bot: Bot):
    """Guruh va kanallarda foydalanuvchi xabarlari o'chirilmaydi."""
    cleaner = UserMessageCleanerMiddleware(ttl=600)
    handler = AsyncMock(return_value="ok")

    group_message = make_message(chat_id=-100500, chat_type="supergroup")
    assert await cleaner(handler, group_message, {"bot": bot}) == "ok"
    assert len(cleaner._tasks) == 0


async def test_user_cleaner_honours_skip_chat_ids(bot: Bot):
    """`skip_chat_ids` ro'yxatidagi chatlar himoyalanadi."""
    user = make_user()
    cleaner = UserMessageCleanerMiddleware(ttl=600, skip_chat_ids={USER_ID})
    handler = AsyncMock(return_value="ok")

    await cleaner(handler, make_message(user=user), {"bot": bot})
    assert len(cleaner._tasks) == 0


async def test_user_cleaner_schedules_deletion(bot: Bot, registry: MessageRegistry):
    """Shaxsiy chatda xabar o'chirishga qo'yiladi."""
    cleaner = UserMessageCleanerMiddleware(ttl=600)
    handler = AsyncMock(return_value="ok")

    await cleaner(handler, make_message(message_id=77), {"bot": bot})

    assert len(cleaner._tasks) == 1
    await cleaner.shutdown()
    assert len(cleaner._tasks) == 0


async def test_user_cleaner_requires_real_bot():
    """`bot` haqiqiy `Bot` bo'lmasa hech narsa rejalashtirilmaydi."""
    cleaner = UserMessageCleanerMiddleware(ttl=600)
    handler = AsyncMock(return_value="ok")

    await cleaner(handler, make_message(), {"bot": MagicMock()})
    assert len(cleaner._tasks) == 0


async def test_user_cleaner_cleanup_deletes(bot: Bot):
    """`_cleanup()` xabarni o'chiradi (TTL 0 bilan darhol)."""
    calls: list[tuple[int, int]] = []

    async def fake_delete(chat_id: int, message_id: int, **kwargs: Any) -> bool:
        calls.append((chat_id, message_id))
        return True

    bot.delete_message = fake_delete  # type: ignore[method-assign]
    cleaner = UserMessageCleanerMiddleware(ttl=0, min_ttl=0)

    await cleaner._cleanup(bot, USER_ID, 55)

    assert calls == [(USER_ID, 55)]


async def test_user_cleaner_started_task_actually_deletes(bot: Bot):
    """Middleware orqali boshlangan vazifa rostdan ham o'chiradi."""
    calls: list[tuple[int, int]] = []

    async def fake_delete(chat_id: int, message_id: int, **kwargs: Any) -> bool:
        calls.append((chat_id, message_id))
        return True

    bot.delete_message = fake_delete  # type: ignore[method-assign]
    cleaner = UserMessageCleanerMiddleware(ttl=0, min_ttl=0)

    await cleaner(AsyncMock(return_value=None), make_message(message_id=77), {"bot": bot})
    await asyncio.sleep(0.05)
    await cleaner.shutdown()

    assert calls == [(USER_ID, 77)]
