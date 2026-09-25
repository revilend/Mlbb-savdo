"""Bot ichidan boshqaruv va AI moderatsiya uchun testlar.

Qamrov:
* `settings` do'koni: standart qiymat, tekshirish, saqlash, standartga qaytarish.
* AI mijozi: so'rov tanasi, javob tahlili, xatoliklar, ulanishni tekshirish.
* `handlers.moderation`: avtomatik tasdiqlash/rad etish mantiqi.
* `handlers.settings_panel`: admin panel navigatsiyasi va tahrirlash oqimi.
* Klaviaturalar va garant havolasining sozlamaga bog'lanishi.

Barcha testlar tarmoqqa murojaat qilmaydi.
"""

from __future__ import annotations

import json
import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

import ai
import config
import keyboards
from database import db
from handlers.admin import adm_restore_start
from handlers.admin import adm_ai, adm_ai_toggle, ai_check_cb
from handlers.moderation import ai_moderate_listing, manual_ai_check
from handlers.sell import sell_finish, sell_price
from handlers.settings_panel import (
    cfg_ai_test,
    cfg_detail,
    cfg_edit,
    cfg_group,
    cfg_home,
    cfg_reset,
    cfg_reset_group,
    cfg_toggle,
    cfg_value,
)
from keyboards import (
    admin_panel_kb,
    ai_panel_kb,
    garant_url,
    garant_username,
    moderation_kb,
    setting_detail_kb,
    settings_groups_kb,
    settings_items_kb,
)
from settings import GROUPS, SPEC, SettingsError, mask_secret, settings, validate
from states import AdminFSM, SellFSM, SettingsFSM

from conftest import ADMIN_ID, USER_ID, make_callback, make_message, make_user

TEST_BOT_USERNAME = "mlbb_market_test_bot"


# ---------------------------------------------------------------------------
# Fixture'lar
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def reset_settings():
    """Har bir test oldidan va keyin runtime sozlamalarni tozalaydi."""
    saved = settings.as_dict()
    settings.load({})
    yield
    settings.load(saved)


@pytest.fixture
async def test_db(tmp_path):
    """Vaqtinchalik SQLite baza bilan global `db` singletonini ishlatadi."""
    old_path = db.path
    old_admins = set(db.admin_ids)
    db.path = str(tmp_path / "features3.sqlite3")

    await db.close()
    await db.connect()
    yield db
    await db.close()

    db.path = old_path
    db.admin_ids.clear()
    db.admin_ids.update(old_admins)


@pytest.fixture
def fsm() -> FSMContext:
    """Shaxsiy chat uchun FSM konteksti."""
    return FSMContext(
        storage=MemoryStorage(),
        key=StorageKey(bot_id=1, chat_id=USER_ID, user_id=USER_ID),
    )


@pytest.fixture
def admin_fsm() -> FSMContext:
    """Administrator uchun FSM konteksti."""
    return FSMContext(
        storage=MemoryStorage(),
        key=StorageKey(bot_id=1, chat_id=ADMIN_ID, user_id=ADMIN_ID),
    )


@pytest.fixture
def fake_bot() -> AsyncMock:
    """Tarmoqqa murojaat qilmaydigan bot."""
    bot = AsyncMock()
    bot.send_message = AsyncMock(return_value=SimpleNamespace(message_id=900))
    bot.send_photo = AsyncMock(return_value=SimpleNamespace(message_id=901))
    bot.send_media_group = AsyncMock(return_value=[SimpleNamespace(message_id=902)])
    bot.send_document = AsyncMock(return_value=SimpleNamespace(message_id=904))
    bot.edit_message_caption = AsyncMock(return_value=True)
    bot.edit_message_text = AsyncMock(return_value=True)
    bot.delete_message = AsyncMock(return_value=True)
    bot.copy_message = AsyncMock(return_value=SimpleNamespace(message_id=903))
    bot.get_me = AsyncMock(return_value=SimpleNamespace(id=42, username=TEST_BOT_USERNAME))
    bot.get_chat = AsyncMock(
        return_value=SimpleNamespace(
            id=-100555, username="pytest_post_channel", title="Test kanal", invite_link=None
        )
    )
    bot.get_chat_member = AsyncMock(return_value=SimpleNamespace(status="administrator"))
    return bot


@pytest.fixture
def bot_username(monkeypatch):
    """Share/referal havolalari uchun bot username o'rnatadi."""
    old = keyboards.BOT_USERNAME
    keyboards.set_bot_username(TEST_BOT_USERNAME)
    yield TEST_BOT_USERNAME
    keyboards.set_bot_username(old)


@pytest.fixture(autouse=True)
def message_edits(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """`Message.edit_*` chaqiruvlarini soxtalashtiradi."""
    mocks = SimpleNamespace(
        edit_text=AsyncMock(return_value=True),
        edit_reply_markup=AsyncMock(return_value=True),
        edit_caption=AsyncMock(return_value=True),
    )
    monkeypatch.setattr("aiogram.types.Message.edit_text", mocks.edit_text)
    monkeypatch.setattr("aiogram.types.Message.edit_reply_markup", mocks.edit_reply_markup)
    monkeypatch.setattr("aiogram.types.Message.edit_caption", mocks.edit_caption)
    return mocks


async def _enable_ai(
    *,
    auto_approve: bool = False,
    reject_scams: bool = True,
    confidence: int = 70,
) -> None:
    """AI moderatsiyani test uchun yoqadi."""
    await settings.set("AI_ENABLED", "true")
    await settings.set("AI_API_KEY", "sk-test-1234567890")
    await settings.set("AI_AUTO_APPROVE", "true" if auto_approve else "false")
    await settings.set("AI_REJECT_SCAMS", "true" if reject_scams else "false")
    await settings.set("AI_MIN_CONFIDENCE", str(confidence))


async def _make_listing(
    *,
    user_id: int = USER_ID,
    price: int = 2_000_000,
    status: str = "pending",
) -> dict:
    """Test uchun e'lon yaratadi."""
    listing_id = await db.create_listing(
        user_id=user_id,
        listing_type="sell",
        rank_info="Mythic Glory",
        skins_info="45 ta skin, 8 collector",
        price_numeric=price,
        price_display=f"{price:,} soʻm".replace(",", " "),
        contact="@seller",
        description="Test eʼlon",
        photos=["AAA"],
        status=status,
    )
    listing = await db.get_listing(listing_id)
    assert listing is not None
    return listing


def _verdict(decision: str, confidence: int = 90, risk: str = "ok") -> ai.AIVerdict:
    """Test uchun AI natijasi."""
    return ai.AIVerdict(
        decision=decision,
        confidence=confidence,
        reason="Test sabab",
        risk=risk,
        model="test-model",
    )


def _callbacks(markup) -> list[str]:
    """Klaviaturdagi callback_data ro'yxati."""
    return [
        btn.callback_data
        for row in markup.inline_keyboard
        for btn in row
        if btn.callback_data
    ]


# ---------------------------------------------------------------------------
# 1. Sozlamalar do'koni
# ---------------------------------------------------------------------------
def test_defaults_come_from_config():
    """Bot ichidan o'zgartirilmagan sozlamalar `.env` qiymatini beradi."""
    assert settings.get("MIN_PRICE") == config.MIN_PRICE
    assert settings.get("LISTING_TTL_DAYS") == config.LISTING_TTL_DAYS
    assert settings.get("TZ_OFFSET_HOURS") == config.TZ_OFFSET_HOURS
    assert settings.get("AI_BASE_URL") == config.AI_BASE_URL
    assert settings.is_overridden("MIN_PRICE") is False
    assert settings.source("MIN_PRICE") == "env"
    assert settings.overridden_count() == 0
    assert settings.total_count() == len(SPEC) > 20


def test_load_accepts_prefixed_plain_and_unknown_keys():
    """`load` prefiksli va prefikssiz kalitlarni qabul qiladi, begonalarni tashlaydi."""
    settings.load(
        {
            "cfg:MIN_PRICE": "555000",
            "TZ_OFFSET_HOURS": "3",
            "nomaʼlum": "x",
            "post_channel": "@kanal",
        }
    )
    assert settings.get("MIN_PRICE") == 555_000
    assert settings.get("TZ_OFFSET_HOURS") == 3
    assert settings.overridden_count() == 2


def test_as_dict_round_trips():
    """`as_dict()` natijasini `load()` ga qaytarish mumkin."""
    settings.load({"MIN_PRICE": "777000"})
    snapshot = settings.as_dict()
    settings.load({})
    assert settings.get("MIN_PRICE") == config.MIN_PRICE
    settings.load(snapshot)
    assert settings.get("MIN_PRICE") == 777_000


async def test_set_validates_and_persists_to_db(test_db):
    """To'g'ri qiymat bazaga `cfg:` prefiksi bilan yoziladi."""
    ok, message = await settings.set("LISTING_TTL_DAYS", "30")

    assert ok is True
    assert "30" in message
    assert settings.get("LISTING_TTL_DAYS") == 30
    assert settings.is_overridden("LISTING_TTL_DAYS") is True
    assert settings.source("LISTING_TTL_DAYS") == "bot"
    assert await db.get_setting("cfg:LISTING_TTL_DAYS") == "30"


async def test_set_rejects_invalid_values(test_db):
    """Yaroqsiz qiymat saqlanmaydi va foydalanuvchiga sabab qaytadi."""
    for bad in ("abc", "0", "999", ""):
        ok, message = await settings.set("LISTING_TTL_DAYS", bad)
        assert ok is False
        assert message.startswith("❌")

    assert settings.get("LISTING_TTL_DAYS") == config.LISTING_TTL_DAYS
    assert await db.get_setting("cfg:LISTING_TTL_DAYS") is None


async def test_bool_toggle_and_display(test_db):
    """Mantiqiy sozlama almashtiriladi va matnda ko'rinadi."""
    assert settings.get_bool("AI_ENABLED") is False
    assert settings.display("AI_ENABLED") == "⛔️ Oʻchirilgan"

    await settings.set("AI_ENABLED", "true")
    assert settings.get_bool("AI_ENABLED") is True
    assert settings.display("AI_ENABLED") == "✅ Yoqilgan"

    ok, _ = await settings.set("AI_ENABLED", "balki")
    assert ok is False


async def test_secret_masking_and_length(test_db):
    """Maxfiy kalit niqoblanadi va qisqasi qabul qilinmaydi."""
    ok, _ = await settings.set("AI_API_KEY", "qisqa")
    assert ok is False
    assert settings.display("AI_API_KEY") == "— sozlanmagan"

    await settings.set("AI_API_KEY", "sk-abcdefghijklmnop")
    assert settings.display("AI_API_KEY") == "sk-a…mnop"
    assert "abcdefghijkl" not in settings.display("AI_API_KEY")
    assert mask_secret("12345") == "•••••"


async def test_reset_returns_to_default(test_db):
    """Standartga qaytarish bazadagi yozuvni ham o'chiradi."""
    await settings.set("MIN_PRICE", "999000")
    assert settings.is_overridden("MIN_PRICE") is True

    assert await settings.reset("MIN_PRICE") is True
    assert settings.get("MIN_PRICE") == config.MIN_PRICE
    assert await db.get_setting("cfg:MIN_PRICE") is None
    assert await settings.reset("MIN_PRICE") is False  # allaqachon standart


async def test_reset_group_restores_everything(test_db):
    """Guruhni standartga qaytarish barcha o'zgarishlarni bekor qiladi."""
    await settings.set("AI_ENABLED", "true")
    await settings.set("AI_API_KEY", "sk-abcdefghijkl")
    await settings.set("MIN_PRICE", "999000")

    assert await settings.reset_group("ai") == 2
    assert settings.overridden_count() == 1
    assert settings.get_bool("AI_ENABLED") is False

    assert await settings.reset_group("ai") == 0
    assert await settings.reset_group("yoq") == 0


def test_display_formats_numbers():
    """Katta sonlar bo'shliq bilan ajratiladi."""
    assert settings.display("MIN_PRICE") == "1 000 soʻm"
    assert settings.display("SIMILAR_PRICE_TOLERANCE") == "0.3 ulush"


def test_unknown_key_raises():
    """Noma'lum kalit uchun xatolik ko'tariladi."""
    with pytest.raises(SettingsError):
        settings.spec("YOQ_BUNDAY_SOZLAMA")
    with pytest.raises(SettingsError):
        settings.get("YOQ_BUNDAY_SOZLAMA")


def test_validate_grup_and_channel_rules():
    """Garant va kanal qiymatlari normallashtiriladi, noto'g'risi rad etiladi."""
    assert validate(SPEC["GARANT_USERNAME"], "@my_garant") == "my_garant"
    assert validate(SPEC["DEFAULT_CHANNEL_ID"], "@kanal") == "@kanal"
    assert validate(SPEC["DEFAULT_CHANNEL_ID"], "-1001234567890") == "-1001234567890"

    for bad in ("my garant", "-", "@"):
        with pytest.raises(SettingsError):
            validate(SPEC["GARANT_USERNAME"], bad)
    with pytest.raises(SettingsError):
        validate(SPEC["DEFAULT_CHANNEL_ID"], "kanal")
    with pytest.raises(SettingsError):
        validate(SPEC["AI_BASE_URL"], "openrouter.ai")


def test_settings_are_grouped_consistently():
    """Barcha sozlamalar ro'yxatdagi guruhlardan biriga tegishli."""
    for item in SPEC.values():
        assert item.group in GROUPS
        assert settings.group_items(item.group)
    assert settings.group_label("ai") == GROUPS["ai"]


async def test_min_price_setting_affects_sell_validation(test_db, fsm, message_answer):
    """Bot ichidan o'zgartirilgan eng kam narx darhol kuchga kiradi."""
    await settings.set("MIN_PRICE", "5000000")

    await sell_price(make_message(text="1000000"), fsm)

    assert "juda past" in message_answer.await_args.args[0]
    assert await fsm.get_state() is None or await fsm.get_state() == SellFSM.price

    await fsm.set_state(SellFSM.price)
    await sell_price(make_message(text="6000000"), fsm)
    data = await fsm.get_data()
    assert data["price_numeric"] == 6_000_000


# ---------------------------------------------------------------------------
# 2. AI: javobni tahlil qilish
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "raw,expected",
    [
        ('{"decision": "approve", "confidence": 91, "reason": "ok", "risk": "ok"}', "approve"),
        ('{"decision": "REJECT", "confidence": 80, "risk": "scam"}', "reject"),
        ('{"decision": "manual", "confidence": 40, "risk": "other"}', "review"),
        ('{"decision": "rad etish", "confidence": 10}', "review"),
        ('{"qaror": "qabul", "ishonch": 70, "sabab": "yaxshi"}', "approve"),
        ('mana natija:\n```json\n{"decision": "approve", "confidence": 55}\n```', "approve"),
    ],
)
def test_parse_verdict_variants(raw, expected):
    """Turli ko'rinishdagi AI javoblari to'g'ri o'qiladi."""
    verdict = ai.parse_verdict(raw, model="m")
    assert verdict.decision == expected
    assert verdict.model == "m"


def test_parse_verdict_clamps_and_falls_back():
    """Ishonch chegaralanadi, tushunarsiz javob qo'lda tekshirishga tushadi."""
    verdict = ai.parse_verdict('{"decision": "approve", "confidence": 500}')
    assert verdict.confidence == 100

    broken = ai.parse_verdict("kechirasiz, javob bera olmayman")
    assert broken.decision == ai.REVIEW
    assert broken.confidence == 0
    assert "qoʻlda" in broken.reason.lower()
    assert broken.raw


def test_verdict_text_contains_key_fields():
    """Admin xabaridagi matn qaror, ishonch va turini ko'rsatadi."""
    text = _verdict("reject", confidence=88, risk="scam").as_text()
    assert "AI tekshiruvi" in text
    assert "RAD ETISH" in text
    assert "88%" in text
    assert "Firibgarlik" in text
    assert "test-model" in text


async def test_is_enabled_requires_flag_and_key(test_db):
    """AI faqat kalit va yoqilgan bayroq bilan ishlaydi."""
    assert ai.is_enabled() is False
    assert ai.config_summary() == "⛔️ Oʻchirilgan"

    await settings.set("AI_ENABLED", "true")
    assert ai.is_enabled() is False
    assert "Kalit kiritilmagan" in ai.config_summary()

    await settings.set("AI_API_KEY", "sk-abcdefghijklmnop")
    assert ai.is_enabled() is True
    assert "Yoqilgan" in ai.config_summary()


async def test_auto_decision_helpers(test_db):
    """Avtomatik qaror chegaralar bo'yicha qabul qilinadi."""
    await _enable_ai(auto_approve=True, reject_scams=True, confidence=70)

    assert ai.should_auto_approve(_verdict("approve", 70)) is True
    assert ai.should_auto_approve(_verdict("approve", 69)) is False
    assert ai.should_auto_approve(_verdict("review", 99)) is False

    assert ai.should_auto_reject(_verdict("reject", 90, risk="scam")) is True
    assert ai.should_auto_reject(_verdict("reject", 90, risk="duplicate")) is False
    assert ai.should_auto_reject(_verdict("reject", 10, risk="scam")) is False

    await settings.set("AI_REJECT_SCAMS", "false")
    assert ai.should_auto_reject(_verdict("reject", 95, risk="scam")) is False


# ---------------------------------------------------------------------------
# 3. AI: HTTP mijozi
# ---------------------------------------------------------------------------
class FakeResponse:
    """`aiohttp` javobi o'rnini bosuvchi."""

    def __init__(self, status: int, body: str) -> None:
        self.status = status
        self._body = body

    async def text(self) -> str:
        return self._body

    async def __aenter__(self) -> "FakeResponse":
        return self

    async def __aexit__(self, *exc) -> bool:
        return False


class FakeSession:
    """`aiohttp.ClientSession` o'rnini bosuvchi."""

    def __init__(self, responses: list[FakeResponse], captured: list[dict]) -> None:
        self._responses = list(responses)
        self._captured = captured

    async def __aenter__(self) -> "FakeSession":
        return self

    async def __aexit__(self, *exc) -> bool:
        return False

    def post(self, url, json=None, headers=None):  # noqa: A002 - aiohttp bilan bir xil imzo
        self._captured.append({"url": url, "json": json, "headers": headers})
        return self._responses.pop(0)


@pytest.fixture
def http(monkeypatch):
    """Soxta HTTP sessiyasini o'rnatadi va yuborilgan so'rovlarni yozib boradi."""
    captured: list[dict] = []

    def install(responses: list[FakeResponse]) -> list[dict]:
        monkeypatch.setattr(
            ai.aiohttp, "ClientSession", lambda **kwargs: FakeSession(responses, captured)
        )
        return captured

    return install


async def test_moderate_listing_sends_listing_fields(test_db, http):
    """So'rov tanasida e'lon ma'lumotlari va sozlangan model bo'ladi."""
    await _enable_ai()
    await settings.set("AI_MODEL", "test/model")
    captured = http(
        [
            FakeResponse(
                200,
                json.dumps(
                    {
                        "choices": [
                            {
                                "message": {
                                    "content": '{"decision": "approve", "confidence": 88, '
                                    '"risk": "ok", "reason": "Toza eʼlon"}'
                                }
                            }
                        ]
                    }
                ),
            )
        ]
    )
    listing = await _make_listing()

    verdict = await ai.moderate_listing(listing)

    assert verdict.decision == "approve"
    assert verdict.confidence == 88

    request = captured[0]
    assert request["url"] == f"{config.AI_BASE_URL}/chat/completions"
    assert request["headers"]["Authorization"].startswith("Bearer sk-")
    assert request["json"]["model"] == "test/model"
    assert request["json"]["response_format"] == {"type": "json_object"}

    user_content = request["json"]["messages"][-1]["content"]
    assert "Mythic Glory" in user_content
    assert "2 000 000" in user_content
    assert f"#{listing['id']}" in user_content


async def test_moderate_listing_retries_without_json_mode(test_db, http):
    """`response_format` qo'llamaydigan provayder uchun qayta uriniladi."""
    await _enable_ai()
    captured = http(
        [
            FakeResponse(400, '{"error": "unsupported"}'),
            FakeResponse(
                200,
                json.dumps({"choices": [{"message": {"content": '{"decision": "review"}'}}]}),
            ),
        ]
    )

    verdict = await ai.moderate_listing(await _make_listing())

    assert verdict.decision == "review"
    assert len(captured) == 2
    assert "response_format" in captured[0]["json"]
    assert "response_format" not in captured[1]["json"]


@pytest.mark.parametrize(
    "status,expected",
    [(401, "Kalit notoʻgʻri"), (402, "mablagʻ"), (429, "chegarasi"), (500, "AI xatosi")],
)
async def test_moderate_listing_maps_http_errors(test_db, http, status, expected):
    """HTTP xatolari tushunarli xabarga aylanadi."""
    await _enable_ai()
    http([FakeResponse(status, "xato")])

    with pytest.raises(ai.AIError) as excinfo:
        await ai.moderate_listing(await _make_listing())

    assert expected in str(excinfo.value)


async def test_moderate_listing_requires_key(test_db):
    """Kalitsiz so'rov yuborilmaydi."""
    await settings.set("AI_ENABLED", "true")

    with pytest.raises(ai.AIError) as excinfo:
        await ai.moderate_listing(await _make_listing())

    assert "kaliti" in str(excinfo.value).lower()


async def test_moderate_listing_appends_extra_rules(test_db, http):
    """Qo'shimcha qoidalar so'rovga qo'shiladi."""
    await _enable_ai()
    await settings.set("AI_EXTRA_RULES", "10 milliondan qimmat e'lonlarni tekshir")
    captured = http(
        [
            FakeResponse(
                200, json.dumps({"choices": [{"message": {"content": '{"decision": "review"}'}}]})
            )
        ]
    )

    await ai.moderate_listing(await _make_listing())

    assert "QO'SHIMCHA QOIDALAR" in captured[0]["json"]["messages"][-1]["content"]
    assert "10 milliondan" in captured[0]["json"]["messages"][-1]["content"]


async def test_test_connection_success_and_bad_json(test_db, http):
    """Ulanishni tekshirish muvaffaqiyatli va buzuq javobni ajratadi."""
    await _enable_ai()
    http(
        [
            FakeResponse(
                200, json.dumps({"choices": [{"message": {"content": '{"ok": true}'}}]})
            )
        ]
    )
    assert "ok" in await ai.test_connection()

    http([FakeResponse(200, json.dumps({"choices": [{"message": {"content": "salom"}}]}))])
    with pytest.raises(ai.AIError):
        await ai.test_connection()


# ---------------------------------------------------------------------------
# 4. AI moderatsiya orkestratsiyasi
# ---------------------------------------------------------------------------
async def test_ai_moderation_skipped_when_disabled(test_db, fake_bot, monkeypatch):
    """AI o'chirilgan bo'lsa hech narsa qilinmaydi va xabar yuborilmaydi."""
    mocked = AsyncMock()
    monkeypatch.setattr(ai, "moderate_listing", mocked)
    listing = await _make_listing()

    outcome = await ai_moderate_listing(fake_bot, int(listing["id"]))

    assert outcome.text == ""
    assert outcome.decided is False
    assert mocked.await_count == 0


async def test_ai_moderation_text_only_when_manual(test_db, fake_bot, monkeypatch):
    """Avtomatik rejim o'chirilgan bo'lsa faqat tavsiya ko'rsatiladi."""
    await _enable_ai(auto_approve=False)
    monkeypatch.setattr(
        ai, "moderate_listing", AsyncMock(return_value=_verdict("approve", 99))
    )
    listing = await _make_listing()

    outcome = await ai_moderate_listing(fake_bot, int(listing["id"]))

    assert outcome.decided is False
    assert outcome.failed is False
    assert "TASDIQLASH tavsiya etiladi" in outcome.text
    assert (await db.get_listing(int(listing["id"])))["status"] == "pending"


async def test_ai_moderation_auto_approves(test_db, fake_bot, monkeypatch, bot_username):
    """Ishonch yetarli bo'lsa e'lon avtomatik kanalga chiqadi."""
    await _enable_ai(auto_approve=True, confidence=70)
    monkeypatch.setattr(
        ai, "moderate_listing", AsyncMock(return_value=_verdict("approve", 95))
    )
    listing = await _make_listing()

    outcome = await ai_moderate_listing(fake_bot, int(listing["id"]))

    assert outcome.decided is True
    assert "AI avtomatik tasdiqladi" in outcome.text
    assert (await db.get_listing(int(listing["id"])))["status"] == "active"
    assert fake_bot.send_photo.await_count >= 1


async def test_ai_moderation_auto_rejects_scam(test_db, fake_bot, monkeypatch):
    """Aniq firibgarlik belgisi bo'lsa e'lon rad etiladi."""
    await _enable_ai(reject_scams=True, confidence=70)
    monkeypatch.setattr(
        ai,
        "moderate_listing",
        AsyncMock(return_value=_verdict("reject", 92, risk="scam")),
    )
    listing = await _make_listing()

    outcome = await ai_moderate_listing(fake_bot, int(listing["id"]))

    assert outcome.decided is True
    assert "AI avtomatik rad etdi" in outcome.text
    assert (await db.get_listing(int(listing["id"])))["status"] == "rejected"
    # Ega sabab bilan xabardor qilinadi
    owner_calls = [
        call for call in fake_bot.send_message.await_args_list if call.args[0] == USER_ID
    ]
    assert owner_calls and "Test sabab" in owner_calls[0].args[1]


async def test_ai_moderation_reports_failure(test_db, fake_bot, monkeypatch):
    """AI xatosi adminlarga xabar qilinadi, e'lon moderatsiyada qoladi."""
    await _enable_ai()
    monkeypatch.setattr(
        ai, "moderate_listing", AsyncMock(side_effect=ai.AIError("Kalit notoʻgʻri (401)"))
    )
    listing = await _make_listing()

    outcome = await ai_moderate_listing(fake_bot, int(listing["id"]))

    assert outcome.failed is True
    assert outcome.decided is False
    assert "AI tekshiruvi bajarilmadi" in outcome.text
    assert "401" in outcome.text
    assert (await db.get_listing(int(listing["id"])))["status"] == "pending"


async def test_ai_moderation_handles_missing_listing(test_db, fake_bot):
    """Mavjud bo'lmagan e'lon uchun jim qaytadi."""
    await _enable_ai()
    outcome = await ai_moderate_listing(fake_bot, 999_999)
    assert outcome.text == ""


async def test_sell_finish_sends_ai_note(test_db, fsm, fake_bot, monkeypatch):
    """Anketa yakunlangach AI natijasi adminlarga alohida xabar bo'lib boradi."""
    await _enable_ai(auto_approve=False)
    monkeypatch.setattr(
        ai, "moderate_listing", AsyncMock(return_value=_verdict("review", 55, risk="other"))
    )

    await fsm.set_state(SellFSM.photos)
    await fsm.update_data(
        rank_info="Mythic Glory",
        skins_info="40 skin",
        listing_mode="sell",
        price_numeric=1_000_000,
        price_display="1 000 000 soʻm",
        is_vip=0,
        contact="@seller",
        description="test",
        photos=["AAA"],
    )

    await sell_finish(make_message(text="✅ Tayyor"), fsm, fake_bot)

    texts = [call.args[1] for call in fake_bot.send_message.await_args_list]
    assert any("AI tekshiruvi" in text for text in texts)
    assert any("QOʻLDA TEKSHIRISH" in text for text in texts)


# ---------------------------------------------------------------------------
# 5. Sozlamalar paneli
# ---------------------------------------------------------------------------
async def test_cfg_home_requires_admin(callback_answer):
    """Ruxsatsiz foydalanuvchi sozlamalar panelini ocha olmaydi."""
    intruder = make_user(user_id=31_337)

    await cfg_home(make_callback(user=intruder, data="cfg_home"), _dummy_state())

    assert callback_answer.await_args.kwargs.get("show_alert") is True


async def test_cfg_home_lists_groups(message_edits, callback_answer):
    """Asosiy sozlamalar sahifasi barcha bo'limlarni ko'rsatadi."""
    admin = make_user(user_id=ADMIN_ID, username="boss")

    await cfg_home(make_callback(user=admin, data="cfg_home"), _dummy_state())

    markup = message_edits.edit_text.await_args.kwargs["reply_markup"]
    callbacks = _callbacks(markup)
    assert "cfg_home" not in callbacks
    assert all(f"cfg_g|{group}" in callbacks for group in GROUPS)
    assert "cfg_ai_test" in callbacks


async def test_cfg_group_and_detail_navigation(test_db, message_edits):
    """Guruh sahifasi va sozlama tafsiloti to'g'ri chiziladi."""
    admin = make_user(user_id=ADMIN_ID)

    await cfg_group(make_callback(user=admin, data="cfg_g|ai"), _dummy_state())
    text = message_edits.edit_text.await_args.args[0]
    assert GROUPS["ai"] in text
    markup = message_edits.edit_text.await_args.kwargs["reply_markup"]
    assert "cfg_s|AI_API_KEY" in _callbacks(markup)
    assert "cfg_resetg|ai" in _callbacks(markup)

    await cfg_detail(make_callback(user=admin, data="cfg_s|AI_API_KEY"), _dummy_state())
    detail = message_edits.edit_text.await_args.args[0]
    assert "AI API kaliti" in detail
    assert "📄 .env (standart)" in detail

    # Bot ichidan kiritilgandan keyin manba o'zgaradi
    await settings.set("AI_API_KEY", "sk-abcdefghijklmnop")
    await cfg_detail(make_callback(user=admin, data="cfg_s|AI_API_KEY"), _dummy_state())
    assert "🤖 bot ichidan" in message_edits.edit_text.await_args.args[0]
    assert "sk-a…mnop" in message_edits.edit_text.await_args.args[0]


async def test_cfg_group_unknown(message_edits, callback_answer):
    """Mavjud bo'lmagan guruh uchun ogohlantirish chiqadi."""
    admin = make_user(user_id=ADMIN_ID)

    await cfg_group(make_callback(user=admin, data="cfg_g|yoq"), _dummy_state())

    assert callback_answer.await_args.kwargs.get("show_alert") is True


async def test_cfg_edit_starts_fsm_and_value_saves(
    test_db, admin_fsm, fake_bot, message_answer, callback_answer
):
    """Tahrirlash FSM orqali ishlaydi va qiymat saqlanadi."""
    admin = make_user(user_id=ADMIN_ID)

    await cfg_edit(make_callback(user=admin, data="cfg_edit|LISTING_TTL_DAYS"), admin_fsm)
    assert await admin_fsm.get_state() == SettingsFSM.waiting_value
    assert (await admin_fsm.get_data())["cfg_key"] == "LISTING_TTL_DAYS"
    assert "amal muddati" in message_answer.await_args.args[0]

    await cfg_value(make_message(user=admin, text="21"), admin_fsm, fake_bot)

    assert await admin_fsm.get_state() is None
    assert settings.get("LISTING_TTL_DAYS") == 21
    confirmation = message_answer.await_args.args[0]
    assert "21 kun" in confirmation
    assert "🤖 bot ichidan" in confirmation


async def test_cfg_value_deletes_secret_message(
    test_db, admin_fsm, fake_bot, message_answer
):
    """Kalit kiritilganda foydalanuvchi xabari chatdan o'chiriladi."""
    admin = make_user(user_id=ADMIN_ID)
    await admin_fsm.set_state(SettingsFSM.waiting_value)
    await admin_fsm.update_data(cfg_key="AI_API_KEY")

    await cfg_value(make_message(user=admin, text="sk-super-secret-key"), admin_fsm, fake_bot)

    assert settings.get("AI_API_KEY") == "sk-super-secret-key"
    assert fake_bot.delete_message.await_count == 1
    assert "sk-super-secret-key" not in message_answer.await_args.args[0]


async def test_cfg_value_rejects_invalid_and_keeps_state(
    test_db, admin_fsm, fake_bot, message_answer
):
    """Yaroqsiz qiymat saqlanmaydi va holat saqlanib qoladi."""
    admin = make_user(user_id=ADMIN_ID)
    await admin_fsm.set_state(SettingsFSM.waiting_value)
    await admin_fsm.update_data(cfg_key="LISTING_TTL_DAYS")

    await cfg_value(make_message(user=admin, text="abc"), admin_fsm, fake_bot)

    assert await admin_fsm.get_state() == SettingsFSM.waiting_value
    assert "❌" in message_answer.await_args.args[0]
    assert settings.get("LISTING_TTL_DAYS") == config.LISTING_TTL_DAYS


async def test_cfg_value_ignores_non_admin(test_db, admin_fsm, message_answer):
    """Admin bo'lmagan foydalanuvchi sozlamani o'zgartira olmaydi."""
    await admin_fsm.set_state(SettingsFSM.waiting_value)
    await admin_fsm.update_data(cfg_key="LISTING_TTL_DAYS")

    await cfg_value(make_message(user=make_user(user_id=55_555), text="30"), admin_fsm, AsyncMock())

    assert settings.get("LISTING_TTL_DAYS") == config.LISTING_TTL_DAYS
    assert message_answer.await_count == 0


async def test_cfg_edit_rejects_bool_and_unknown(test_db, admin_fsm, callback_answer):
    """Mantiqiy sozlama matn orqali tahrirlanmaydi."""
    admin = make_user(user_id=ADMIN_ID)

    await cfg_edit(make_callback(user=admin, data="cfg_edit|AI_ENABLED"), admin_fsm)
    assert await admin_fsm.get_state() is None
    assert "almashtirish" in callback_answer.await_args.args[0]

    await cfg_edit(make_callback(user=admin, data="cfg_edit|YOQ"), admin_fsm)
    assert callback_answer.await_args.kwargs.get("show_alert") is True


async def test_cfg_toggle_flips_boolean(test_db, message_edits, callback_answer):
    """Almashtirish tugmasi bayroqni o'giradi va guruhni qayta chizadi."""
    admin = make_user(user_id=ADMIN_ID)
    assert settings.get_bool("AI_ENABLED") is False

    await cfg_toggle(make_callback(user=admin, data="cfg_toggle|AI_ENABLED"))

    assert settings.get_bool("AI_ENABLED") is True
    assert "Yoqilgan" in callback_answer.await_args.args[0]
    assert GROUPS["ai"] in message_edits.edit_text.await_args.args[0]

    await cfg_toggle(make_callback(user=admin, data="cfg_toggle|AI_ENABLED"))
    assert settings.get_bool("AI_ENABLED") is False


async def test_cfg_reset_and_reset_group(test_db, message_edits, callback_answer):
    """Standartga qaytarish tugmalari ishlaydi."""
    await settings.set("BACKUP_HOUR", "5")
    await settings.set("BACKUP_KEEP", "3")
    admin = make_user(user_id=ADMIN_ID)

    await cfg_reset(make_callback(user=admin, data="cfg_reset|BACKUP_HOUR"))
    assert settings.get("BACKUP_HOUR") == config.BACKUP_HOUR
    assert "standart qiymatga qaytarildi" in message_edits.edit_text.await_args.args[0]
    assert settings.is_overridden("BACKUP_KEEP") is True

    await cfg_reset_group(make_callback(user=admin, data="cfg_resetg|backup"))
    assert settings.is_overridden("BACKUP_KEEP") is False
    assert "1 ta sozlama" in message_edits.edit_text.await_args.args[0]


async def test_cfg_ai_test_success_and_failure(test_db, fake_bot, message_answer, monkeypatch):
    """AI ulanishini tekshirish natijasi adminga ko'rsatiladi."""
    admin = make_user(user_id=ADMIN_ID)

    monkeypatch.setattr(ai, "test_connection", AsyncMock(return_value='{"ok": true}'))
    await cfg_ai_test(make_callback(user=admin, data="cfg_ai_test"), fake_bot)
    assert "AI ulanishi ishlaydi" in message_answer.await_args.args[0]

    monkeypatch.setattr(
        ai, "test_connection", AsyncMock(side_effect=ai.AIError("Kalit notoʻgʻri (401)"))
    )
    await cfg_ai_test(make_callback(user=admin, data="cfg_ai_test"), fake_bot)
    failure = message_answer.await_args.args[0]
    assert "AI ulanishi ishlamadi" in failure
    assert "401" in failure


async def test_cfg_ai_test_requires_admin(callback_answer, message_answer):
    """Ruxsatsiz foydalanuvchi AI testni ishga tushira olmaydi."""
    intruder = make_user(user_id=31_337)

    await cfg_ai_test(make_callback(user=intruder, data="cfg_ai_test"), AsyncMock())

    assert callback_answer.await_args.kwargs.get("show_alert") is True
    assert message_answer.await_count == 0


# ---------------------------------------------------------------------------
# 6. Klaviaturalar va havolalar
# ---------------------------------------------------------------------------
def test_admin_panel_has_settings_shortcuts():
    """Admin panelda sozlamalar va AI tugmalari bor."""
    callbacks = _callbacks(admin_panel_kb())
    assert "cfg_home" in callbacks
    assert "cfg_g|ai" in callbacks


def test_garant_links_follow_settings(test_db):
    """Garant havolasi bot ichidan o'zgartirilgan qiymatga ergashadi."""
    assert garant_username() == config.GARANT_USERNAME
    assert garant_url() == f"https://t.me/{config.GARANT_USERNAME}"

    settings.load({"GARANT_USERNAME": "super_garant"})
    assert garant_username() == "super_garant"
    assert garant_url() == "https://t.me/super_garant"

    buttons = [btn for row in garant_kb_rows() for btn in row if btn.url]
    assert any(btn.url == "https://t.me/super_garant" for btn in buttons)


def test_legacy_garant_username_is_migrated(test_db):
    """Eski `my_garant` qiymati bazada qolsa ham joriy garantga o'tadi."""
    settings.load({f"{settings.PREFIX}GARANT_USERNAME": "my_garant"})
    assert garant_username() == config.DEFAULT_GARANT_USERNAME
    assert garant_url() == f"https://t.me/{config.DEFAULT_GARANT_USERNAME}"

    settings.load({})


def test_other_garant_username_is_untouched(test_db):
    """Boshqa qiymatlar migratsiyadan chetlab o'tadi."""
    settings.load({"GARANT_USERNAME": "real_garant"})
    assert garant_username() == "real_garant"

    settings.load({})


def garant_kb_rows():
    """Garant klaviaturasi qatorlari."""
    return keyboards.garant_kb().inline_keyboard


def test_settings_keyboards_reflect_values(test_db):
    """Panel klaviaturalari joriy qiymatni ko'rsatadi."""
    markup = settings_items_kb("prices")
    texts = [btn.text for row in markup.inline_keyboard for btn in row]
    assert any("Eng kam narx" in text for text in texts)
    assert any(text.startswith("•") for text in texts)
    assert "cfg_resetg|prices" in _callbacks(markup)

    settings.load({"MIN_PRICE": "123000"})
    marked = [btn.text for row in settings_items_kb("prices").inline_keyboard for btn in row]
    assert any(text.startswith("✏️") for text in marked)

    detail = setting_detail_kb(SPEC["AI_ENABLED"], "ai")
    assert "cfg_toggle|AI_ENABLED" in _callbacks(detail)
    assert "cfg_reset|AI_ENABLED" in _callbacks(detail)

    text_detail = setting_detail_kb(SPEC["AI_API_KEY"], "ai")
    callbacks = _callbacks(text_detail)
    assert "cfg_edit|AI_API_KEY" in callbacks
    assert "cfg_ai_test" in callbacks

    groups = settings_groups_kb()
    assert len(_callbacks(groups)) == len(GROUPS) + 2


# ---------------------------------------------------------------------------
# 7. AI boshqaruvi (admin panel)
# ---------------------------------------------------------------------------
def test_ai_panel_kb_has_full_control(test_db):
    """AI panelida yoqish/oʻchirish, kalit, tekshirish va sozlamalar bor."""
    callbacks = _callbacks(ai_panel_kb())
    assert "adm_ai_toggle" in callbacks
    assert "cfg_edit|AI_API_KEY" in callbacks
    assert "cfg_ai_test" in callbacks
    assert "cfg_g|ai" in callbacks
    assert "adm_back" in callbacks

    off_texts = [btn.text for row in ai_panel_kb().inline_keyboard for btn in row]
    assert any("yoqish" in text for text in off_texts)

    settings.load({"AI_ENABLED": "true"})
    on_texts = [btn.text for row in ai_panel_kb().inline_keyboard for btn in row]
    assert any("oʻchirish" in text for text in on_texts)


def test_moderation_kb_has_manual_ai_button():
    """E'lon kartochkasida qoʻlda AI tekshirish tugmasi bor."""
    assert "ai_chk_42" in _callbacks(moderation_kb(42))
    assert "app_42" in _callbacks(moderation_kb(42))


def test_admin_panel_ai_button_reflects_state(test_db):
    """Admin paneldagi AI tugmasi holatni ko'rsatadi va bosiladi."""
    callbacks = _callbacks(admin_panel_kb())
    assert "adm_ai" in callbacks

    def ai_texts() -> list[str]:
        return [btn.text for row in admin_panel_kb().inline_keyboard for btn in row]

    assert any("oʻchiq" in text for text in ai_texts())
    settings.load({"AI_ENABLED": "true"})
    assert any("yoqilgan" in text for text in ai_texts())


async def test_adm_ai_panel_requires_admin(callback_answer):
    """AI paneli faqat administrator uchun."""
    await adm_ai(make_callback(user=make_user(user_id=55_555), data="adm_ai"), _dummy_state())
    assert callback_answer.await_args.kwargs.get("show_alert") is True


async def test_adm_ai_panel_shows_status(test_db, message_edits):
    """AI paneli holat, kalit, model va avto-qarorlarni ko'rsatadi."""
    await _enable_ai(auto_approve=True)
    admin = make_user(user_id=ADMIN_ID)

    await adm_ai(make_callback(user=admin, data="adm_ai"), _dummy_state())

    text = message_edits.edit_text.await_args.args[0]
    assert "AI moderatsiya" in text
    assert "✅ yoqilgan" in text
    assert "sk-t…7890" in text
    assert "Avto-tasdiqlash: ✅ Yoqilgan" in text


async def test_adm_ai_toggle_requires_admin(callback_answer):
    """AI yoqish/oʻchirish faqat administrator uchun."""
    await adm_ai_toggle(make_callback(user=make_user(user_id=55_555), data="adm_ai_toggle"))
    assert callback_answer.await_args.kwargs.get("show_alert") is True


async def test_adm_ai_toggle_warns_when_key_missing(test_db, message_edits, callback_answer):
    """Kalitsiz yoqilsa admin ogohlantiriladi, holat baribir saqlanadi."""
    admin = make_user(user_id=ADMIN_ID)

    await adm_ai_toggle(make_callback(user=admin, data="adm_ai_toggle"))

    assert settings.get_bool("AI_ENABLED") is True
    assert "kalit" in callback_answer.await_args.args[0].lower()
    assert "API kaliti kiritilmagan" in message_edits.edit_text.await_args.args[0]


async def test_adm_ai_toggle_off_and_on_with_key(test_db, message_edits, callback_answer):
    """Kalit bor bo'lsa yoqiladi, keyin bir tugma bilan oʻchiriladi."""
    await _enable_ai()
    admin = make_user(user_id=ADMIN_ID)

    await adm_ai_toggle(make_callback(user=admin, data="adm_ai_toggle"))
    assert settings.get_bool("AI_ENABLED") is False
    assert "oʻchirildi" in callback_answer.await_args.args[0].lower()

    await adm_ai_toggle(make_callback(user=admin, data="adm_ai_toggle"))
    assert settings.get_bool("AI_ENABLED") is True


async def test_manual_ai_check_when_disabled(test_db, fake_bot):
    """AI oʻchirilgan boʻlsa qoʻlda tekshiruv sababni aytadi."""
    text, decided = await manual_ai_check(fake_bot, 1)
    assert decided is False
    assert "oʻchirilgan" in text


async def test_manual_ai_check_without_key(test_db, fake_bot):
    """Kalit yoʻq boʻlsa aniq koʻrsatma beriladi."""
    await settings.set("AI_ENABLED", "true")
    text, decided = await manual_ai_check(fake_bot, 1)
    assert decided is False
    assert "API kaliti kiritilmagan" in text


async def test_manual_ai_check_reports_verdict(test_db, fake_bot, monkeypatch):
    """Qoʻlda tekshiruv AI xulosasini qaytaradi, qaror qoʻlda qoladi."""
    await _enable_ai(auto_approve=False)
    monkeypatch.setattr(
        ai, "moderate_listing", AsyncMock(return_value=_verdict("review", 55, risk="other"))
    )
    listing = await _make_listing()

    text, decided = await manual_ai_check(fake_bot, int(listing["id"]))

    assert decided is False
    assert "QOʻLDA TEKSHIRISH" in text
    assert "Mustaqil qaror qabul qilinmadi" in text
    assert (await db.get_listing(int(listing["id"])))["status"] == "pending"


async def test_manual_ai_check_applies_auto_rules(test_db, fake_bot, monkeypatch, bot_username):
    """Qoʻlda tekshiruv ham avto-tasdiqlash sozlamasiga boʻysunadi."""
    await _enable_ai(auto_approve=True, confidence=70)
    monkeypatch.setattr(
        ai, "moderate_listing", AsyncMock(return_value=_verdict("approve", 99))
    )
    listing = await _make_listing()

    text, decided = await manual_ai_check(fake_bot, int(listing["id"]))

    assert decided is True
    assert "AI avtomatik tasdiqladi" in text
    assert (await db.get_listing(int(listing["id"])))["status"] == "active"


async def test_manual_ai_check_reports_error(test_db, fake_bot, monkeypatch):
    """Qoʻlda tekshiruvda xatolik ham tushunarli koʻrsatiladi."""
    await _enable_ai()
    monkeypatch.setattr(ai, "moderate_listing", AsyncMock(side_effect=ai.AIError("429")))
    listing = await _make_listing()

    text, decided = await manual_ai_check(fake_bot, int(listing["id"]))
    assert decided is False
    assert "AI tekshiruvi bajarilmadi" in text


async def test_ai_check_handler_requires_admin(callback_answer, message_edits):
    """Qoʻlda tekshirish tugmasi faqat administrator uchun."""
    await ai_check_cb(
        make_callback(user=make_user(user_id=55_555), data="ai_chk_1"), AsyncMock()
    )
    assert callback_answer.await_args.kwargs.get("show_alert") is True
    assert message_edits.edit_text.await_count == 0


async def test_ai_check_handler_bad_id(callback_answer, message_edits):
    """Notoʻgʻri raqam uchun ogohlantirish."""
    admin = make_user(user_id=ADMIN_ID)
    await ai_check_cb(make_callback(user=admin, data="ai_chk_abc"), AsyncMock())
    assert callback_answer.await_args.kwargs.get("show_alert") is True
    assert message_edits.edit_text.await_count == 0


async def test_ai_check_handler_keeps_buttons_when_undecided(
    test_db, fake_bot, monkeypatch, message_edits
):
    """Qaror qilinmasa e'lon tugmalari saqlanib qoladi."""
    await _enable_ai(auto_approve=False)
    monkeypatch.setattr(
        ai, "moderate_listing", AsyncMock(return_value=_verdict("review", 60, risk="other"))
    )
    listing = await _make_listing()
    admin = make_user(user_id=ADMIN_ID)

    await ai_check_cb(
        make_callback(user=admin, data=f"ai_chk_{listing['id']}"), fake_bot
    )

    markup = message_edits.edit_text.await_args.kwargs["reply_markup"]
    assert f"app_{listing['id']}" in _callbacks(markup)
    assert f"ai_chk_{listing['id']}" in _callbacks(markup)


async def test_ai_check_handler_removes_buttons_when_auto(test_db, fake_bot, monkeypatch, message_edits, bot_username):
    """Avto-tasdiq boʻlsa tugmalar olib tashlanadi."""
    await _enable_ai(auto_approve=True, confidence=70)
    monkeypatch.setattr(
        ai, "moderate_listing", AsyncMock(return_value=_verdict("approve", 99))
    )
    listing = await _make_listing()
    admin = make_user(user_id=ADMIN_ID)

    await ai_check_cb(
        make_callback(user=admin, data=f"ai_chk_{listing['id']}"), fake_bot
    )

    assert message_edits.edit_text.await_args.kwargs["reply_markup"] is None
    assert "AI avtomatik tasdiqladi" in message_edits.edit_text.await_args.args[0]


# ---------------------------------------------------------------------------
# Restore testlari
# ---------------------------------------------------------------------------
async def test_restore_valid_sqlite_backup(test_db, tmp_path):
    """Valid backup faylni atomik tiklash va joriy bazani almashtirish."""
    backup_path = tmp_path / "backup.sqlite3"
    assert await db.backup_to(str(backup_path))

    await db.add_user(999, "new_user", "Yangi foydalanuvchi")
    with sqlite3.connect(backup_path) as conn:
        conn.execute("DELETE FROM users WHERE user_id = 999")
        conn.commit()

    ok, safety_path = await db.restore_from(str(backup_path))
    assert ok is True
    assert safety_path
    assert await db.get_user(999) is None


async def test_restore_rejects_non_sqlite_file(test_db, tmp_path):
    """Noto'g'ri fayl tiklashdan oldin rad etiladi."""
    invalid = tmp_path / "invalid.sqlite3"
    invalid.write_text("not a database " + ("x" * 40), encoding="utf-8")

    ok, reason = await db.restore_from(str(invalid))
    assert ok is False
    assert "SQLite" in reason


async def test_restore_button_is_admin_only(callback_answer):
    """Restore tugmasi faqat admin uchun boshqariladi."""
    callback = make_callback(user=make_user(USER_ID), data="adm_restore")
    state = FSMContext(
        storage=MemoryStorage(), key=StorageKey(bot_id=1, chat_id=USER_ID, user_id=USER_ID)
    )
    await adm_restore_start(callback, state)
    callback_answer.assert_awaited_once()
    assert await state.get_state() is None


def test_admin_panel_has_restore_button():
    callbacks = {
        button.callback_data
        for row in admin_panel_kb().inline_keyboard
        for button in row
    }
    assert "adm_backup" in callbacks
    assert "adm_restore" in callbacks


# ---------------------------------------------------------------------------
# Yordamchi
# ---------------------------------------------------------------------------
class _DummyState:
    """`FSMContext` o'rnini bosuvchi (navigatsiya handlerlari uchun)."""

    async def clear(self) -> None:
        return None

    async def get_data(self) -> dict:
        return {}


def _dummy_state() -> _DummyState:
    return _DummyState()
