"""`AntiFloodMiddleware` uchun testlar.

Qamrov:

* sürgülü oyna (ruxsat / bloklash / oynadan chiqish)
* ogohlantirish va uning throttling'i
* bosqichli mute (buzilishlar soni, davomiyligi, tugashi)
* mute tugagach hisobning nolga tushishi
* spam xabarni o'chirish (yoqilgan / o'chirilgan)
* "jimgina rejim" (`notify=False`) va callback kafolati
* chetlab o'tish (`bypass_user_ids`) va `from_user` yo'qligi
* holatlar izolyatsiyasi, `reset()`, xotira tozalash (GC)
* `build_anti_flood()` konfiguratsiyaga mosligi
* Telegram xatolariga chidamlilik
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import config
import pytest
from aiogram.exceptions import TelegramForbiddenError
from aiogram.types import Chat, Message
from conftest import GC_PERIOD, USER_ID, make_callback, make_message, make_user
from middlewares.anti_flood import AntiFloodMiddleware, build_anti_flood


@pytest.fixture(autouse=True)
def _patch_telegram_shortcuts(monkeypatch: pytest.MonkeyPatch) -> None:
    """Middleware Telegram metodlarini chaqiradi — ularni doim soxtalashtiramiz.

    Testlar o'z mock'ini alohida fixture orqali olsa, u shu mock'ni
    almashtiradi (pytest autouse fixture'larni birinchi yaratadi).
    """
    monkeypatch.setattr(Message, "answer", AsyncMock())
    monkeypatch.setattr(Message, "delete", AsyncMock(return_value=True))


def make_middleware(**overrides: object) -> AntiFloodMiddleware:
    """Test uchun qisqa sozlamali middleware."""
    params: dict = {
        "window": 5.0,
        "max_events": 3,
        "notice_cooldown": 0.0,
        "violation_limit": 3,
        "mute_seconds": 60,
        "mute_reset_seconds": 180,
        "warning_ttl": 6,
        "delete_flooding_messages": False,
        "notify": True,
    }
    params.update(overrides)
    return AntiFloodMiddleware(**params)


# ---------------------------------------------------------------------------
# Sürgülü oyna
# ---------------------------------------------------------------------------
async def test_allows_events_within_limit(handler, event_data):
    """Chegaragacha bo'lgan hodisalar handler'ga yetib boradi."""
    middleware = make_middleware(max_events=3)

    for index in range(3):
        assert await middleware(handler, make_message(message_id=index), event_data) == "handled"

    assert handler.await_count == 3


async def test_blocks_event_over_limit(handler, event_data, message_answer):
    """Chegaradan oshgan hodisa to'xtatiladi va handler chaqirilmaydi."""
    middleware = make_middleware(max_events=2)
    await middleware(handler, make_message(message_id=1), event_data)
    await middleware(handler, make_message(message_id=2), event_data)

    assert await middleware(handler, make_message(message_id=3), event_data) is None
    assert handler.await_count == 2
    assert message_answer.await_count == 1


async def test_old_events_leave_the_window(clock, handler, event_data):
    """Oynadan chiqib ketgan hodisalar hisobga olinmaydi."""
    middleware = make_middleware(window=5.0, max_events=2)
    await middleware(handler, make_message(message_id=1), event_data)
    await middleware(handler, make_message(message_id=2), event_data)
    assert await middleware(handler, make_message(message_id=3), event_data) is None

    clock.advance(5.1)

    assert await middleware(handler, make_message(message_id=4), event_data) == "handled"


async def test_state_is_isolated_per_user(handler, event_data):
    """Bitta foydalanuvchining limiti boshqasiga ta'sir qilmaydi."""
    middleware = make_middleware(max_events=1)
    await middleware(handler, make_message(message_id=1), event_data)
    assert await middleware(handler, make_message(message_id=2), event_data) is None

    other = make_user(user_id=777)
    other_data = {"event_from_user": other}
    assert await middleware(handler, make_message(user=other, message_id=3), other_data) == "handled"


# ---------------------------------------------------------------------------
# Ogohlantirish
# ---------------------------------------------------------------------------
async def test_warning_is_throttled(handler, event_data, message_answer):
    """`notice_cooldown` ichida faqat bitta ogohlantirish yuboriladi."""
    middleware = make_middleware(max_events=1, notice_cooldown=60.0, violation_limit=99)

    for index in range(5):
        await middleware(handler, make_message(message_id=index), event_data)

    assert message_answer.await_count == 1


async def test_warning_resent_after_cooldown(clock, handler, event_data, message_answer):
    """Cooldown o'tgach keyingi buzilishda yana ogohlantiriladi."""
    middleware = make_middleware(max_events=1, notice_cooldown=5.0, violation_limit=99)

    await middleware(handler, make_message(message_id=1), event_data)  # ruxsat
    await middleware(handler, make_message(message_id=2), event_data)  # 1-ogohlantirish
    assert message_answer.await_count == 1

    clock.advance(6.0)
    await middleware(handler, make_message(message_id=3), event_data)  # oyna bo'shadi -> ruxsat
    await middleware(handler, make_message(message_id=4), event_data)  # 2-ogohlantirish
    assert message_answer.await_count == 2


# ---------------------------------------------------------------------------
# Mute
# ---------------------------------------------------------------------------
async def test_mute_after_violation_limit(handler, event_data, message_answer):
    """`violation_limit` marta buzilgach mute qo'llaniladi."""
    middleware = make_middleware(max_events=1, violation_limit=3, mute_seconds=60)

    await middleware(handler, make_message(message_id=1), event_data)  # ruxsat
    for index in range(3):
        await middleware(handler, make_message(message_id=10 + index), event_data)

    assert middleware.mute_remaining(USER_ID) > 0
    assert "kutish kerak" in message_answer.await_args.args[0]


async def test_muted_user_is_blocked_and_alerted(clock, handler, event_data, message_answer):
    """Mute davomida hodisalar bloklanadi va foydalanuvchi xabardor qilinadi."""
    middleware = make_middleware(max_events=1, violation_limit=1, mute_seconds=30)

    await middleware(handler, make_message(message_id=1), event_data)
    await middleware(handler, make_message(message_id=2), event_data)  # mute
    assert middleware.mute_remaining(USER_ID) > 0

    messages_before = message_answer.await_count
    clock.advance(1.0)

    assert await middleware(handler, make_message(message_id=3), event_data) is None
    assert handler.await_count == 1
    assert message_answer.await_count > messages_before


async def test_mute_expires_and_counter_resets(clock, handler, event_data):
    """Mute tugagach foydalanuvchi yana ishlay oladi."""
    middleware = make_middleware(max_events=1, violation_limit=1, mute_seconds=10)

    await middleware(handler, make_message(message_id=1), event_data)
    await middleware(handler, make_message(message_id=2), event_data)
    assert middleware.mute_remaining(USER_ID) > 0

    clock.advance(11.0)

    assert middleware.mute_remaining(USER_ID) == 0
    assert await middleware(handler, make_message(message_id=3), event_data) == "handled"


async def test_violations_reset_after_quiet_period(clock, handler, event_data):
    """Uzoq tinchlikdan keyin buzilish hisobi nolga tushadi."""
    middleware = make_middleware(
        window=1.0, max_events=1, violation_limit=5, mute_reset_seconds=60
    )

    await middleware(handler, make_message(message_id=1), event_data)
    await middleware(handler, make_message(message_id=2), event_data)  # 1-buzilish
    assert middleware._states[USER_ID].violations == 1

    clock.advance(120.0)

    assert await middleware(handler, make_message(message_id=3), event_data) == "handled"
    assert middleware._states[USER_ID].violations == 0


# ---------------------------------------------------------------------------
# Purge (spam xabarni o'chirish)
# ---------------------------------------------------------------------------
async def test_purge_deletes_message_when_enabled(handler, event_data, message_delete):
    """`delete_flooding_messages=True` bo'lsa spam xabar o'chiriladi."""
    middleware = make_middleware(max_events=1, delete_flooding_messages=True)

    await middleware(handler, make_message(message_id=1), event_data)
    await middleware(handler, make_message(message_id=2), event_data)

    assert message_delete.await_count == 1


async def test_purge_disabled_keeps_message(handler, event_data, message_delete):
    """Yumshoq rejimda foydalanuvchining xabari o'chirilmaydi."""
    middleware = make_middleware(max_events=1, delete_flooding_messages=False)

    await middleware(handler, make_message(message_id=1), event_data)
    await middleware(handler, make_message(message_id=2), event_data)

    assert message_delete.await_count == 0


# ---------------------------------------------------------------------------
# Jimgina rejim va callback kafolati
# ---------------------------------------------------------------------------
async def test_silent_mode_sends_nothing(handler, event_data, message_answer):
    """`notify=False` bo'lsa hech qanday ogohlantirish yuborilmaydi."""
    middleware = make_middleware(
        max_events=1, violation_limit=1, mute_seconds=30, notify=False
    )

    for index in range(6):
        await middleware(handler, make_message(message_id=index), event_data)

    assert middleware.mute_remaining(USER_ID) > 0
    assert message_answer.await_count == 0


async def test_callback_always_gets_an_answer(handler, event_data, callback_answer):
    """Bloklangan har bir callback javob oladi (aks holda spinner qolib ketadi)."""
    middleware = make_middleware(max_events=1, violation_limit=99)

    await middleware(handler, make_callback(), event_data)  # ruxsat -> handler javob beradi
    assert await middleware(handler, make_callback(), event_data) is None
    assert await middleware(handler, make_callback(), event_data) is None

    assert handler.await_count == 1
    assert callback_answer.await_count == 2, "har bir bloklangan callback javob olishi kerak"


async def test_silent_mode_still_answers_callbacks(handler, event_data, callback_answer):
    """Jimgina rejimda ham callback javob oladi, lekin matnsiz."""
    middleware = make_middleware(max_events=1, notify=False, violation_limit=99)

    await middleware(handler, make_callback(), event_data)  # ruxsat
    assert await middleware(handler, make_callback(), event_data) is None

    assert callback_answer.await_count == 1
    assert all(call.args[0] is None for call in callback_answer.await_args_list)


async def test_mute_alert_is_shown_for_callbacks(handler, event_data, callback_answer):
    """Mute bo'lganda callback uchun alert ko'rsatiladi."""
    middleware = make_middleware(max_events=1, violation_limit=1, mute_seconds=30)

    await middleware(handler, make_callback(), event_data)
    await middleware(handler, make_callback(), event_data)  # mute

    assert callback_answer.await_args_list[-1].kwargs.get("show_alert") is True


# ---------------------------------------------------------------------------
# Chetlab o'tish holatlari
# ---------------------------------------------------------------------------
async def test_bypass_ids_are_never_limited(handler):
    """`bypass_user_ids` ro'yxatidagi foydalanuvchilar cheklanmaydi."""
    admin = make_user(user_id=config.ADMIN_ID, username="admin")
    data = {"event_from_user": admin}
    middleware = make_middleware(max_events=1, violation_limit=1,
                                 bypass_user_ids={config.ADMIN_ID})

    for index in range(20):
        result = await middleware(handler, make_message(user=admin, message_id=index), data)
        assert result == "handled"

    assert handler.await_count == 20
    assert middleware.active_users() == 0


async def test_admin_is_not_bypassed_without_config(handler):
    """`bypass_user_ids` bo'sh bo'lsa hech kim chetlab o'tilmaydi."""
    admin = make_user(user_id=999)
    data = {"event_from_user": admin}
    middleware = make_middleware(max_events=1, bypass_user_ids=set())

    await middleware(handler, make_message(user=admin, message_id=1), data)
    assert await middleware(handler, make_message(user=admin, message_id=2), data) is None


async def test_missing_from_user_passes_through(handler):
    """`from_user` yo'q (kanal posti) bo'lsa middleware aralashmaydi."""
    middleware = make_middleware(max_events=1)
    channel_post = Message(
        message_id=1,
        date=datetime.now(timezone.utc),
        chat=Chat(id=-1001234567890, type="channel"),
        text="kanal posti",
    )
    assert channel_post.from_user is None

    for _ in range(5):
        assert await middleware(handler, channel_post, {"bot": MagicMock()}) == "handled"

    assert middleware.active_users() == 0


# ---------------------------------------------------------------------------
# Holat boshqaruvi
# ---------------------------------------------------------------------------
async def test_reset_clears_state(handler, event_data):
    """`reset()` hisobni tozalaydi."""
    middleware = make_middleware(max_events=1)
    await middleware(handler, make_message(message_id=1), event_data)
    await middleware(handler, make_message(message_id=2), event_data)
    assert middleware.active_users() == 1

    middleware.reset(USER_ID)
    assert middleware.active_users() == 0
    assert await middleware(handler, make_message(message_id=3), event_data) == "handled"

    middleware.reset()
    assert middleware.active_users() == 0


async def test_gc_keeps_muted_user(handler, event_data):
    """Xotira tozalash (GC) faol mute holatini o'chirib yubormasligi kerak."""
    middleware = make_middleware(max_events=1, violation_limit=1, mute_seconds=600)

    await middleware(handler, make_message(message_id=1), event_data)
    await middleware(handler, make_message(message_id=2), event_data)  # mute
    assert middleware.mute_remaining(USER_ID) > 0

    guard = 0
    while middleware._calls % GC_PERIOD != 0 and guard < GC_PERIOD + 5:
        await middleware(handler, make_message(message_id=100 + guard), event_data)
        guard += 1

    assert middleware._calls % GC_PERIOD == 0, "GC ishga tushmadi"
    assert USER_ID in middleware._states
    assert middleware.mute_remaining(USER_ID) > 0


async def test_gc_purges_expired_users(clock, handler):
    """Muddati o'tgan va bo'sh holatlar xotiradan o'chiriladi."""
    middleware = make_middleware(
        max_events=1, violation_limit=1, mute_seconds=10, mute_reset_seconds=5
    )
    stale = make_user(user_id=777)
    stale_data = {"event_from_user": stale}

    await middleware(handler, make_message(user=stale, message_id=1), stale_data)
    await middleware(handler, make_message(user=stale, message_id=2), stale_data)  # mute
    assert middleware.mute_remaining(777) > 0

    clock.advance(20.0)  # mute ham, buzilish hisobi ham eskirdi

    fresh = make_user(user_id=888)
    fresh_data = {"event_from_user": fresh}
    guard = 0
    while middleware._calls % GC_PERIOD != 0 and guard < GC_PERIOD + 5:
        await middleware(handler, make_message(user=fresh, message_id=200 + guard), fresh_data)
        guard += 1

    assert middleware._calls % GC_PERIOD == 0, "GC ishga tushmadi"
    assert 777 not in middleware._states


# ---------------------------------------------------------------------------
# `build_anti_flood` va sozlamalar
# ---------------------------------------------------------------------------
def test_build_anti_flood_returns_none_when_disabled(monkeypatch):
    """`FLOOD_PROTECTION=false` bo'lsa middleware umuman yaratilmaydi."""
    monkeypatch.setattr(config, "FLOOD_PROTECTION", False)
    assert build_anti_flood() is None


def test_build_anti_flood_reads_config(monkeypatch):
    """Middleware sozlamalarni `config` dan oladi."""
    monkeypatch.setattr(config, "FLOOD_PROTECTION", True)
    monkeypatch.setattr(config, "FLOOD_WINDOW_SECONDS", 1.5)
    monkeypatch.setattr(config, "FLOOD_MAX_EVENTS", 4)
    monkeypatch.setattr(config, "FLOOD_NOTICE_COOLDOWN", 2.0)
    monkeypatch.setattr(config, "FLOOD_VIOLATION_LIMIT", 6)
    monkeypatch.setattr(config, "FLOOD_MUTE_SECONDS", 7)
    monkeypatch.setattr(config, "FLOOD_WARNING_TTL", 3)
    monkeypatch.setattr(config, "FLOOD_DELETE_MESSAGES", True)
    monkeypatch.setattr(config, "FLOOD_NOTIFY", False)

    middleware = build_anti_flood()
    assert middleware is not None
    assert middleware.window == 1.5
    assert middleware.max_events == 4
    assert middleware.notice_cooldown == 2.0
    assert middleware.violation_limit == 6
    assert middleware.mute_seconds == 7
    assert middleware.warning_ttl == 3
    assert middleware.delete_flooding_messages is True
    assert middleware.notify_enabled is False


def test_build_anti_flood_bypasses_admin(monkeypatch):
    """Administrator avtomatik chetlab o'tiladi, o'chirilsa — yo'q."""
    monkeypatch.setattr(config, "FLOOD_PROTECTION", True)
    monkeypatch.setattr(config, "ADMIN_ID", 4321)

    monkeypatch.setattr(config, "FLOOD_BYPASS_ADMIN", True)
    middleware = build_anti_flood()
    assert middleware is not None
    assert 4321 in middleware.bypass_user_ids

    monkeypatch.setattr(config, "FLOOD_BYPASS_ADMIN", False)
    middleware = build_anti_flood()
    assert middleware is not None
    assert middleware.bypass_user_ids == set()


def test_default_settings_are_gentle():
    """Sukut qiymatlar yumshoq rejimni ta'minlaydi (regressiya himoyasi)."""
    assert config.FLOOD_DELETE_MESSAGES is False, "spam bo'lsa ham xabar o'chirilmasin"
    assert config.FLOOD_MUTE_SECONDS <= 30, "jazo juda uzoq bo'lmasin"
    assert config.FLOOD_VIOLATION_LIMIT >= 5, "mute uchun ko'p buzilish kerak"
    assert config.FLOOD_MAX_EVENTS / config.FLOOD_WINDOW_SECONDS <= 3.0, (
        "ruxsat etilgan tezlik sekundiga 3 so'rovdan oshmasin"
    )


# ---------------------------------------------------------------------------
# Xatolarga chidamlilik
# ---------------------------------------------------------------------------
async def test_telegram_error_while_warning_does_not_crash(handler, event_data, monkeypatch):
    """Ogohlantirish yuborilmasa ham middleware ishlashda davom etadi."""
    monkeypatch.setattr(
        Message,
        "answer",
        AsyncMock(side_effect=TelegramForbiddenError(method=MagicMock(), message="blocked")),
    )

    middleware = make_middleware(max_events=1, violation_limit=99)
    await middleware(handler, make_message(message_id=1), event_data)

    assert await middleware(handler, make_message(message_id=2), event_data) is None
    assert handler.await_count == 1


async def test_telegram_error_while_purging_does_not_crash(handler, event_data, monkeypatch):
    """Xabarni o'chirib bo'lmasa ham ishlash davom etadi."""
    monkeypatch.setattr(
        Message,
        "delete",
        AsyncMock(side_effect=TelegramForbiddenError(method=MagicMock(), message="blocked")),
    )

    middleware = make_middleware(max_events=1, delete_flooding_messages=True, violation_limit=99)
    await middleware(handler, make_message(message_id=1), event_data)

    assert await middleware(handler, make_message(message_id=2), event_data) is None
