"""Pytest uchun umumiy fixture va yordamchi obyektlar.

Muhim: muhit o'zgaruvchilari `config` import qilinishidan **oldin**
o'rnatiladi, chunki `config.py` qiymatlarni import vaqtida o'qiydi.
"""

from __future__ import annotations

import os

# `config` import qilinishidan oldin ishlashi shart
os.environ["BOT_TOKEN"] = "123456789:PYTEST-FAKE-TOKEN"
os.environ["ADMIN_ID"] = "1"
os.environ["DEFAULT_CHANNEL_ID"] = "@pytest_channel"
os.environ["GARANT_USERNAME"] = "pytest_garant"

from datetime import datetime, timezone  # noqa: E402
from types import SimpleNamespace  # noqa: E402
from typing import Any, List, Optional  # noqa: E402
from unittest.mock import AsyncMock, MagicMock  # noqa: E402

import pytest  # noqa: E402
from aiogram import Bot  # noqa: E402
from aiogram.client.default import DefaultBotProperties  # noqa: E402
from aiogram.enums import ParseMode  # noqa: E402
from aiogram.types import CallbackQuery, Chat, Message, User  # noqa: E402

ADMIN_ID = 1
USER_ID = 555

#: `_track_call` dagi GC davri (`self._calls % 512`) bilan mos bo'lishi kerak
GC_PERIOD = 512


# ---------------------------------------------------------------------------
# Boshqariladigan vaqt
# ---------------------------------------------------------------------------
class Clock:
    """Qo'lda boshqariladigan `time.monotonic` o'rnini bosuvchi.

    Testlar `asyncio.sleep` kutmasdan vaqtni oldinga sura oladi.
    """

    def __init__(self, start: float = 10_000.0) -> None:
        self.value = float(start)

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        """Vaqtni oldinga suradi."""
        self.value += float(seconds)

    def set(self, value: float) -> None:
        """Vaqtni aniq qiymatga o'rnatadi (masalan, tizim endigina yonganda)."""
        self.value = float(value)


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    """Faqat `middlewares.anti_flood` nom fazosidagi `time` ni almashtiradi.

    Global `time` moduli va asyncio event loop tegilmaydi, shuning uchun
    `asyncio.sleep` normal ishlashda davom etadi.
    """
    clock = Clock()
    monkeypatch.setattr("middlewares.anti_flood.time", SimpleNamespace(monotonic=clock))
    return clock


# ---------------------------------------------------------------------------
# Telegram obyektlari
# ---------------------------------------------------------------------------
def make_user(
    user_id: int = USER_ID,
    username: Optional[str] = "tester",
    full_name: str = "Test User",
) -> User:
    """Haqiqiy `aiogram.types.User` yaratadi."""
    return User(id=user_id, is_bot=False, first_name=full_name, last_name=None,
                username=username)


def make_message(
    user: Optional[User] = None,
    chat_id: int = USER_ID,
    message_id: int = 1,
    text: str = "salom",
    chat_type: str = "private",
) -> Message:
    """Haqiqiy `aiogram.types.Message` yaratadi (settersiz — faqat o'qish uchun)."""
    return Message(
        message_id=message_id,
        date=datetime.now(timezone.utc),
        chat=Chat(id=chat_id, type=chat_type),
        from_user=user if user is not None else make_user(),
        text=text,
    )


def make_callback(
    user: Optional[User] = None,
    data: str = "f_100",
    message: Optional[Message] = None,
    callback_id: str = "cb-1",
) -> CallbackQuery:
    """Haqiqiy `aiogram.types.CallbackQuery` yaratadi."""
    return CallbackQuery(
        id=callback_id,
        from_user=user if user is not None else make_user(),
        chat_instance="chat-instance",
        data=data,
        message=message if message is not None else make_message(),
    )


class FakeResult:
    """Telegram API javobi o'rnini bosuvchi (faqat `message_id` muhim)."""

    def __init__(self, message_id: Optional[int]) -> None:
        if message_id is not None:
            self.message_id = message_id


# ---------------------------------------------------------------------------
# Fixture'lar
# ---------------------------------------------------------------------------
@pytest.fixture
def handler() -> AsyncMock:
    """Xatolarni yutmaydigan soxta handler."""
    return AsyncMock(return_value="handled")


@pytest.fixture
def event_data() -> dict:
    """Middleware'ga uzatiladigan `data` (UserContextMiddleware kabi)."""
    return {"event_from_user": make_user(), "bot": MagicMock()}


@pytest.fixture(autouse=True)
def telegram(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Telegram "shortcut" metodlarini almashtiradi.

    Soxta obyektlar ustidan **bitta** fixture egalik qiladi. Aks holda bir nechta
    fixture bir xil atributni almashtirib, qaysi mock chaqiruvni olishi fixture
    tartibiga bog'liq bo'lib qolar edi — bu esa jimgina "yashil" o'tadigan
    yolg'on testlarni keltirib chiqaradi.
    """
    mocks = SimpleNamespace(
        answer=AsyncMock(),
        delete=AsyncMock(return_value=True),
        callback_answer=AsyncMock(),
    )
    monkeypatch.setattr(Message, "answer", mocks.answer)
    monkeypatch.setattr(Message, "delete", mocks.delete)
    monkeypatch.setattr(CallbackQuery, "answer", mocks.callback_answer)
    return mocks


@pytest.fixture
def message_answer(telegram: SimpleNamespace) -> AsyncMock:
    """`Message.answer` mock'i (chaqiruvlarni yozib boradi)."""
    return telegram.answer


@pytest.fixture
def message_delete(telegram: SimpleNamespace) -> AsyncMock:
    """`Message.delete` mock'i."""
    return telegram.delete


@pytest.fixture
def callback_answer(telegram: SimpleNamespace) -> AsyncMock:
    """`CallbackQuery.answer` mock'i."""
    return telegram.callback_answer


@pytest.fixture
def bot() -> Bot:
    """Haqiqiy `Bot` obyekti — tarmoqqa murojaat qilmaydi.

    `UserMessageCleanerMiddleware` `isinstance(data["bot"], Bot)` ni tekshiradi,
    shuning uchun oddiy `MagicMock` yetarli emas.
    """
    return Bot(
        token="123456789:PYTEST-FAKE-TOKEN",
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


@pytest.fixture
def recording_delete() -> tuple[List[tuple], Any]:
    """`delete_message` chaqiruvlarini yozib boruvchi funksiya."""
    calls: List[tuple] = []

    async def _delete(chat_id: int, message_id: int, **kwargs: Any) -> bool:
        calls.append((chat_id, message_id))
        return True

    return calls, _delete
