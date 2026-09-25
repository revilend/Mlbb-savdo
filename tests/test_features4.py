"""Bozor statistikasi, shikoyat, komment, bot bahosi va tasdiqlash testlari.

Qamrov:
* `handlers.market`: narx statistikasi, bozor tavsiyasi, shikoyat oqimi.
* `handlers.comments`: e'longa izoh yozish va o'qish.
* `handlers.bot_rating`: 1–10 baho, izoh, past bahoda admin ogohlantirishi.
* `handlers.admin`: shikoyatlarni ko'rish/yopish, sotuvchini tasdiqlash.
* `handlers.common`: tasdiqlash belgisi e'lon kartochkasida.

Barcha testlar tarmoqqa murojaat qilmaydi.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

from database import db
from handlers.admin import adm_report_by_id, adm_report_done, adm_reports, adm_verify_seller
from handlers.bot_rating import bot_rating_pick, bot_rating_skip, bot_rating_start, stars_bar
from handlers.comments import comment_list, comment_save, comment_write
from handlers.common import seller_label_of
from handlers.market import (
    market_menu,
    market_period,
    price_suggestion_text,
    report_details,
    report_reason,
    report_start,
)
from keyboards import (
    BTN_BOT_RATING,
    BTN_MARKET,
    MAIN_MENU_ROWS,
    admin_panel_kb,
    bot_rating_kb,
    comment_list_kb,
    listing_action_kb,
    market_period_kb,
    report_admin_kb,
    report_reason_kb,
    verify_seller_kb,
)
from states import BotRatingFSM, CommentFSM, ReportFSM

from conftest import ADMIN_ID, USER_ID, make_callback, make_message, make_user

#: Sotuvchi sifatida ishlatiladigan foydalanuvchi
OTHER_ID = 4242


# ---------------------------------------------------------------------------
# Fixture'lar
# ---------------------------------------------------------------------------
@pytest.fixture
async def test_db(tmp_path):
    """Vaqtinchalik SQLite baza bilan global `db` singletonini ishlatadi."""
    old_path = db.path
    old_admins = set(db.admin_ids)
    db.path = str(tmp_path / "features4.sqlite3")

    await db.close()
    await db.connect()
    db.admin_ids.clear()
    db.admin_ids.add(ADMIN_ID)
    yield db
    await db.close()

    db.path = old_path
    db.admin_ids.clear()
    db.admin_ids.update(old_admins)


@pytest.fixture
def fsm() -> FSMContext:
    return FSMContext(
        storage=MemoryStorage(),
        key=StorageKey(bot_id=1, chat_id=USER_ID, user_id=USER_ID),
    )


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


@pytest.fixture
def fake_bot():
    """Tarmoqqa murojaat qilmaydigan bot."""
    return AsyncMock()


def _callbacks(markup) -> list[str]:
    return [
        btn.callback_data
        for row in markup.inline_keyboard
        for btn in row
        if btn.callback_data
    ]


async def _make_sold_listing(rank: str, price: int, user_id: int = 4242) -> dict:
    """Sotilgan e'lon yaratadi — bozor statistikasi faqat shularni hisoblaydi."""
    listing_id = await db.create_listing(
        user_id=user_id,
        listing_type="sell",
        rank_info=rank,
        skins_info="10 ta skin",
        price_numeric=price,
        price_display=str(price),
        contact="@seller",
        description="",
        photos=[],
        status="sold",
    )
    return await db.get_listing(listing_id)


# ---------------------------------------------------------------------------
# 📈 Narx statistikasi
# ---------------------------------------------------------------------------
async def test_market_menu_shows_empty_state(test_db, message_answer):
    """Sotilgan e'lon yo'q bo'lsa bozor bo'shligi aytiladi."""
    await market_menu(make_message(user=make_user(), text=BTN_MARKET))

    text = message_answer.await_args_list[0][0][0]
    assert "Narx statistikasi" in text
    assert "yetarli maʼlumot yoʻq" in text


async def test_market_menu_groups_by_rank(test_db, message_answer):
    """Sotilgan e'lonlar rank bo'yicha guruhlanib, o'rtacha narx ko'rsatiladi."""
    await _make_sold_listing("Mythic Glory", 1_000_000)
    await _make_sold_listing("Mythic Glory", 3_000_000)
    await _make_sold_listing("Legend I", 500_000)

    await market_menu(make_message(user=make_user(), text=BTN_MARKET))

    text = message_answer.await_args_list[0][0][0]
    assert "Mythic Glory" in text
    assert "2 000 000" in text.replace(" ", " ").replace(" ", " ") or "2 000 000" in text
    assert "Legend I" in text


async def test_market_menu_ignores_unsold_listings(test_db, message_answer):
    """Faqat sotilgan e'lonlar bozorga hisoblanadi."""
    listing_id = await db.create_listing(
        user_id=4242,
        listing_type="sell",
        rank_info="Epic",
        skins_info="",
        price_numeric=9_000_000,
        price_display="9000000",
        contact="@s",
        description="",
        photos=[],
        status="active",
    )
    assert listing_id

    await market_menu(make_message(user=make_user(), text=BTN_MARKET))

    assert "Epic" not in message_answer.await_args_list[0][0][0]


async def test_market_period_switches_window(test_db, message_answer, callback_answer):
    """Davrni o'zgartirish statistikani qayta hisoblaydi."""
    await _make_sold_listing("Mythic Glory", 1_500_000)

    await market_period(
        make_callback(user=make_user(), data="mkt_7", message=make_message()),
        None,
    )

    text = message_answer.await_args_list[0][0][0]
    assert "7" in text
    assert "Mythic Glory" in text


async def test_market_period_back_to_menu(test_db, message_answer, callback_answer):
    """«Orqaga» menyuga qaytaradi."""
    await market_period(
        make_callback(user=make_user(), data="mkt_back", message=make_message()),
        None,
    )

    assert "Bozor statistikasi" in message_answer.await_args_list[0][0][0]


async def test_market_period_rejects_garbage(callback_answer):
    """Noto'g'ri davr rad etiladi."""
    await market_period(
        make_callback(user=make_user(), data="mkt_abc", message=make_message()),
        None,
    )

    assert callback_answer.await_args.kwargs.get("show_alert") is True


def test_market_period_kb_marks_current(test_db):
    """Faol davr `✅` bilan belgilanadi."""
    callbacks = _callbacks(market_period_kb(30))
    assert "mkt_7" in callbacks and "mkt_90" in callbacks
    texts = [b.text for row in market_period_kb(30).inline_keyboard for b in row]
    assert any("30 kun ✅" == t for t in texts)


def test_menu_button_is_registered():
    """Bozor statistikasi tugmasi asosiy menyuda bor."""
    assert BTN_MARKET in [b for row in MAIN_MENU_ROWS for b in row]


# ---------------------------------------------------------------------------
# Bozor narxi tavsiyasi
# ---------------------------------------------------------------------------
async def test_price_suggestion_uses_sold_average(test_db):
    """Tavsiya — sotilgan e'lonlarning o'rtacha narxi."""
    await _make_sold_listing("Mythic Glory", 2_000_000)
    await _make_sold_listing("Mythic Glory", 4_000_000)

    text = await price_suggestion_text("Mythic Glory")

    assert text is not None
    assert "3 000 000" in text or "3000000" in text.replace(" ", "")


async def test_price_suggestion_none_without_data(test_db):
    """Bozorda ma'lumot yo'q bo'lsa tavsiya berilmaydi."""
    assert await price_suggestion_text("Mythic Glory") is None


# ---------------------------------------------------------------------------
# 🚨 Shikoyat qilish
# ---------------------------------------------------------------------------
def test_listing_card_has_report_and_comment_buttons(test_db):
    """E'lon kartasida shikoyat va komment tugmalari bor."""
    listing = {"id": 7, "user_id": 42, "listing_type": "sell", "status": "active"}
    callbacks = _callbacks(listing_action_kb(listing))

    assert "rep_l_7" in callbacks
    assert "cmt_7" in callbacks


def test_buy_listing_has_no_report_button(test_db):
    """Xaridor e'loni uchun shikoyat tugmasi chiqmaydi."""
    listing = {"id": 8, "user_id": 42, "listing_type": "buy", "status": "active"}

    assert "rep_l_8" not in _callbacks(listing_action_kb(listing))


def test_report_reason_kb_lists_all_reasons(test_db):
    """Har bir sabab uchun alohida tugma bor."""
    from keyboards import REPORT_REASONS

    callbacks = _callbacks(report_reason_kb(5, 42))
    assert len(callbacks) == len(REPORT_REASONS)
    assert "rep_r_scam_5_42" in callbacks


async def test_report_start_shows_reasons(test_db, message_answer, callback_answer, fsm):
    """Shikoyat tugmasi sabablar ro'yxatini ochadi."""
    listing = await _make_sold_listing("Mythic Glory", 1_000_000, user_id=OTHER_ID)

    await report_start(
        make_callback(user=make_user(), data=f"rep_l_{listing['id']}"),
        fsm,
    )

    text = message_answer.await_args_list[0][0][0]
    assert "Shikoyat qilish" in text
    assert f"#{listing['id']}" in text


async def test_report_start_blocks_self_report(test_db, callback_answer, fsm):
    """O'z e'loniga shikoyat qilishga ruxsat berilmaydi."""
    listing = await _make_sold_listing("Mythic Glory", 1_000_000, user_id=USER_ID)

    await report_start(
        make_callback(user=make_user(user_id=USER_ID), data=f"rep_l_{listing['id']}"),
        fsm,
    )

    assert callback_answer.await_args.args[0].startswith("🙂")


async def test_report_reason_asks_for_details(test_db, message_answer, callback_answer, fsm):
    """Sabab tanlangach izoh so'raladi."""
    listing = await _make_sold_listing("Mythic Glory", 1_000_000, user_id=OTHER_ID)

    await report_reason(
        make_callback(
            user=make_user(),
            data=f"rep_r_scam_{listing['id']}_{OTHER_ID}",
        ),
        fsm,
    )

    assert await fsm.get_state() == ReportFSM.waiting_details
    data = await fsm.get_data()
    assert data["report_reason"] == "scam"
    assert data["report_seller_id"] == OTHER_ID
    assert "Shikoyatni tasdiqlang" in message_answer.await_args_list[0][0][0]


async def test_report_reason_rejects_unknown_code(test_db, callback_answer, fsm):
    """Noma'lum sabab kodi rad etiladi."""
    listing = await _make_sold_listing("Mythic Glory", 1_000_000, user_id=OTHER_ID)

    await report_reason(
        make_callback(user=make_user(), data=f"rep_r_baqa_{listing['id']}_{OTHER_ID}"),
        fsm,
    )

    assert callback_answer.await_args.kwargs.get("show_alert") is True
    assert await fsm.get_state() is None


async def test_report_details_saves_and_notifies_admin(
    test_db, message_answer, fsm, fake_bot, monkeypatch
):
    """Shikoyat saqlanadi va adminlar ogohlantiriladi."""
    from handlers import market

    sent: list[str] = []
    monkeypatch.setattr(
        market, "notify_admin", AsyncMock(side_effect=lambda bot, text, markup=None: sent.append(text))
    )

    listing = await _make_sold_listing("Mythic Glory", 1_000_000, user_id=OTHER_ID)
    await fsm.set_state(ReportFSM.waiting_details)
    await fsm.update_data(
        report_listing_id=listing["id"],
        report_seller_id=OTHER_ID,
        report_reason="scam",
    )

    await report_details(make_message(user=make_user(), text="Pulni olib bermadi"), fsm, fake_bot)

    stored = await db.get_reports(status="new")
    assert len(stored) == 1
    assert stored[0]["details"] == "Pulni olib bermadi"
    assert stored[0]["target_id"] == OTHER_ID
    assert sent, "adminlar ogohlantirilmadi"
    assert await fsm.get_state() is None


async def test_report_details_can_skip_text(test_db, message_answer, fsm, fake_bot, monkeypatch):
    """Izohsiz ham shikoyat yuboriladi."""
    from handlers import market

    monkeypatch.setattr(market, "notify_admin", AsyncMock())
    listing = await _make_sold_listing("Mythic Glory", 1_000_000, user_id=OTHER_ID)
    await fsm.set_state(ReportFSM.waiting_details)
    await fsm.update_data(
        report_listing_id=listing["id"],
        report_seller_id=OTHER_ID,
        report_reason="spam",
    )

    await report_details(make_message(user=make_user(), text="   "), fsm, fake_bot)

    assert len(await db.get_reports(status="new")) == 1


async def test_report_details_prevents_duplicates(test_db, message_answer, fsm, fake_bot):
    """Bitta foydalanuvchi bir sotuvchiga faqat bir marta shikoyat qila oladi."""
    listing = await _make_sold_listing("Mythic Glory", 1_000_000, user_id=OTHER_ID)
    await fsm.set_state(ReportFSM.waiting_details)
    await fsm.update_data(
        report_listing_id=listing["id"],
        report_seller_id=OTHER_ID,
        report_reason="scam",
    )
    await report_details(make_message(user=make_user(), text="birinchi"), fsm, fake_bot)

    await fsm.set_state(ReportFSM.waiting_details)
    await fsm.update_data(
        report_listing_id=listing["id"],
        report_seller_id=OTHER_ID,
        report_reason="scam",
    )
    await report_details(make_message(user=make_user(), text="ikkinchi"), fsm, fake_bot)

    assert len(await db.get_reports(status="new")) == 1


async def test_report_details_cancel(test_db, message_answer, fsm, fake_bot):
    """«Bekor qilish» shikoyat yaratmaydi."""
    from keyboards import BTN_CANCEL

    await fsm.set_state(ReportFSM.waiting_details)
    await report_details(make_message(user=make_user(), text=BTN_CANCEL), fsm, fake_bot)

    assert await db.get_reports(status=None) == []
    assert await fsm.get_state() is None


def test_report_admin_kb_has_actions(test_db):
    """Admin uchun ko'rish, rad etish va xabar tugmalari bor."""
    callbacks = _callbacks(report_admin_kb(3, OTHER_ID))
    assert "rep_ok_3" in callbacks
    assert "rep_no_3" in callbacks
    assert f"adm_dm_{OTHER_ID}" in callbacks


# ---------------------------------------------------------------------------
# Shikoyatlarni admin boshqaruvi
# ---------------------------------------------------------------------------
async def test_adm_reports_lists_new_only(test_db, message_edits):
    """Faqat ko'rilmagan shikoyatlar ro'yxatga tushadi."""
    await db.create_report(USER_ID, OTHER_ID, 1, "Firibgarlik", "birinchisi")
    await db.create_report(USER_ID, OTHER_ID, 1, "Spam", "ikkinchisi")
    await db.update_report_status(2, "done")

    await adm_reports(make_callback(user=make_user(user_id=ADMIN_ID), data="adm_reports"))

    text = message_edits.edit_text.await_args_list[0][0][0]
    assert "Firibgarlik" in text
    assert "Spam" not in text


async def test_adm_reports_requires_admin(callback_answer):
    """Admin bo'lmagan foydalanuvchi ro'yxatni ko'ra olmaydi."""
    await adm_reports(make_callback(user=make_user(user_id=777), data="adm_reports"))

    assert callback_answer.await_count == 1
    assert "⛔️" in callback_answer.await_args.args[0]


async def test_adm_reports_empty_state(test_db, message_edits):
    """Shikoyat bo'lmasa bo'sh holat ko'rsatiladi."""
    await adm_reports(make_callback(user=make_user(user_id=ADMIN_ID), data="adm_reports"))

    assert "yoʻq" in message_edits.edit_text.await_args_list[0][0][0]


async def test_adm_report_by_id_shows_details(test_db, message_answer):
    """Shikoyat tanlanganda to'liq ma'lumot chiqadi."""
    report_id = await db.create_report(USER_ID, OTHER_ID, 5, "Firibgarlik", "Pulsiz akkaunt")

    await adm_report_by_id(
        make_callback(user=make_user(user_id=ADMIN_ID), data=f"vrep_{report_id}")
    )

    text = message_answer.await_args_list[0][0][0]
    assert "Firibgarlik" in text
    assert "Pulsiz akkaunt" in text
    assert f"rep_ok_{report_id}" in _callbacks(message_answer.await_args.kwargs["reply_markup"])


async def test_adm_report_done_closes_report(test_db, message_answer, callback_answer):
    """«Ko'rildi» shikoyatni yopadi."""
    report_id = await db.create_report(USER_ID, OTHER_ID, 5, "Spam")

    await adm_report_done(
        make_callback(user=make_user(user_id=ADMIN_ID), data=f"rep_ok_{report_id}")
    )

    assert await db.get_reports(status="new") == []
    assert (await db.get_reports(status="done"))[0]["id"] == report_id


async def test_adm_report_done_rejects_bad_id(callback_answer):
    """Noto'g'ri shikoyat raqami rad etiladi."""
    await adm_report_done(
        make_callback(user=make_user(user_id=ADMIN_ID), data="rep_ok_abc")
    )

    assert callback_answer.await_args.kwargs.get("show_alert") is True


def test_admin_panel_has_reports_button(test_db):
    """Admin panelida shikoyatlar tugmasi bor."""
    assert "adm_reports" in _callbacks(admin_panel_kb())


# ---------------------------------------------------------------------------
# ✅ Sotuvchini tasdiqlash
# ---------------------------------------------------------------------------
async def test_verify_badge_appears_after_admin_action(test_db):
    """Admin tasdiqlagach e'lon kartasida `✅` belgisi chiqadi."""
    await db.add_user(OTHER_ID, "seller", "Seller")
    listing = {"user_id": OTHER_ID}

    assert not (await seller_label_of(listing)).startswith("✅")

    await db.set_verified(OTHER_ID, True)

    label = await seller_label_of(listing)
    assert label.startswith("✅")
    assert "Seller" in label or "seller" in label


async def test_adm_verify_toggles_badge(test_db, message_answer, callback_answer):
    """Tugma tasdiqlashni yoqadi va olib tashlaydi."""
    await db.add_user(OTHER_ID, "seller", "Seller")

    await adm_verify_seller(
        make_callback(user=make_user(user_id=ADMIN_ID), data=f"vfy_{OTHER_ID}")
    )
    assert await db.is_verified(OTHER_ID) is True
    assert "tasdiqlandi" in message_answer.await_args_list[0][0][0].lower()

    await adm_verify_seller(
        make_callback(user=make_user(user_id=ADMIN_ID), data=f"vfy_{OTHER_ID}")
    )
    assert await db.is_verified(OTHER_ID) is False
    assert "olib tashlandi" in message_answer.await_args_list[1][0][0].lower()


async def test_adm_verify_requires_admin(callback_answer, test_db):
    """Admin bo'lmagan foydalanuvchi tasdiqlay olmaydi."""
    await db.add_user(OTHER_ID, "seller", "Seller")

    await adm_verify_seller(
        make_callback(user=make_user(user_id=777), data=f"vfy_{OTHER_ID}")
    )

    assert await db.is_verified(OTHER_ID) is False


async def test_adm_verify_unknown_user(callback_answer, test_db):
    """Noma'lum foydalanuvchi uchun xato beriladi."""
    await adm_verify_seller(
        make_callback(user=make_user(user_id=ADMIN_ID), data="vfy_999999")
    )

    assert callback_answer.await_args.kwargs.get("show_alert") is True


async def test_verified_sellers_counted(test_db):
    """Tasdiqlangan sotuvchilar soni hisoblanadi."""
    await db.add_user(1, "a", "A")
    await db.add_user(2, "b", "B")
    await db.set_verified(2, True)

    assert await db.count_verified_sellers() == 1


def test_verify_seller_kb_reflects_state(test_db):
    """Tugma matni joriy holatga moslashadi."""
    texts = [b.text for row in verify_seller_kb(OTHER_ID, True).inline_keyboard for b in row]
    assert any("Olib tashlash" in t for t in texts)
    texts = [b.text for row in verify_seller_kb(OTHER_ID, False).inline_keyboard for b in row]
    assert any("Sotuvchini tasdiqlash" in t for t in texts)


# ---------------------------------------------------------------------------
# 💬 E'lon kommentlari
# ---------------------------------------------------------------------------
def test_comment_list_kb(test_db):
    """Komment klaviaturasi yozish va kartaga qaytish tugmalarini beradi."""
    callbacks = _callbacks(comment_list_kb(5))
    assert "cmt_w_5" in callbacks
    assert "view_5" in callbacks


async def test_comment_write_sets_state(test_db, message_answer, callback_answer, fsm):
    """«Komment yozish» matn kutish holatiga o'tadi."""
    listing = await _make_sold_listing("Mythic Glory", 1_000_000, user_id=OTHER_ID)

    await comment_write(
        make_callback(user=make_user(), data=f"cmt_w_{listing['id']}"),
        fsm,
    )

    assert await fsm.get_state() == CommentFSM.waiting_text
    assert (await fsm.get_data())["comment_listing_id"] == listing["id"]


async def test_comment_write_blocks_owner(test_db, callback_answer, fsm):
    """E'lon egasi o'ziga komment yozmaydi."""
    listing = await _make_sold_listing("Mythic Glory", 1_000_000, user_id=USER_ID)

    await comment_write(
        make_callback(user=make_user(user_id=USER_ID), data=f"cmt_w_{listing['id']}"),
        fsm,
    )

    assert await fsm.get_state() is None
    assert "🙂" in callback_answer.await_args.args[0]


async def test_comment_save_stores_text(test_db, message_answer, fsm):
    """Komment saqlanadi."""
    listing = await _make_sold_listing("Mythic Glory", 1_000_000, user_id=OTHER_ID)
    await fsm.set_state(CommentFSM.waiting_text)
    await fsm.update_data(comment_listing_id=listing["id"])

    await comment_save(make_message(user=make_user(), text="Qancha narx?"), fsm)

    items = await db.get_listing_comments(listing["id"])
    assert len(items) == 1
    assert items[0]["text"] == "Qancha narx?"


async def test_comment_save_rejects_too_short(test_db, message_answer, fsm):
    """Juda qisqa komment qabul qilinmaydi."""
    listing = await _make_sold_listing("Mythic Glory", 1_000_000, user_id=OTHER_ID)
    await fsm.set_state(CommentFSM.waiting_text)
    await fsm.update_data(comment_listing_id=listing["id"])

    await comment_save(make_message(user=make_user(), text="a"), fsm)

    assert await db.get_listing_comments(listing["id"]) == []
    assert await fsm.get_state() == CommentFSM.waiting_text


async def test_comment_list_shows_text(test_db, message_answer, callback_answer):
    """Ro'yxatda komment matni ko'rinadi."""
    listing = await _make_sold_listing("Mythic Glory", 1_000_000, user_id=OTHER_ID)
    await db.add_listing_comment(listing["id"], USER_ID, "Qancha narx?")

    await comment_list(
        make_callback(user=make_user(), data=f"cmt_{listing['id']}")
    )

    assert "Qancha narx?" in message_answer.await_args_list[0][0][0]


async def test_comment_count(test_db):
    """Kommentlar soni to'g'ri hisoblanadi."""
    listing = await _make_sold_listing("Mythic Glory", 1_000_000, user_id=OTHER_ID)
    for i in range(3):
        await db.add_listing_comment(listing["id"], USER_ID, f"izoh {i}")

    assert await db.count_listing_comments(listing["id"]) == 3


# ---------------------------------------------------------------------------
# ⭐️ Botga 1–10 baho
# ---------------------------------------------------------------------------
def test_bot_rating_button_in_menu():
    """Bot bahosi tugmasi asosiy menyuda bor."""
    from keyboards import MAIN_MENU_ROWS

    flat = [button for row in MAIN_MENU_ROWS for button in row]
    assert BTN_BOT_RATING in flat


def test_bot_rating_kb_offers_ten_scores(test_db):
    """1 dan 10 gacha barcha baholar mavjud."""
    assert sorted(_callbacks(bot_rating_kb())) == sorted(f"botr_{n}" for n in range(1, 11))


def test_stars_bar_length_is_ten():
    """Chiziqcha har doim 10 ta belgidan iborat."""
    assert len(stars_bar(7)) == 10
    assert stars_bar(0).count("▰") == 0
    assert stars_bar(20).count("▰") == 10


async def test_bot_rating_start_sets_state(test_db, message_answer, fsm):
    """Tugma baho tanash holatini ochadi."""
    await bot_rating_start(make_message(user=make_user(), text=BTN_BOT_RATING), fsm)

    assert await fsm.get_state() == BotRatingFSM.rating
    assert "Botga baho bering" in message_answer.await_args_list[0][0][0]


async def test_bot_rating_rejects_out_of_range(test_db, callback_answer, fsm):
    """1–10 dan tashqari baho rad etiladi."""
    await fsm.set_state(BotRatingFSM.rating)

    await bot_rating_pick(
        make_callback(user=make_user(), data="botr_42"), fsm
    )

    assert callback_answer.await_args.kwargs.get("show_alert") is True
    assert await fsm.get_state() == BotRatingFSM.rating


async def test_bot_rating_stores_score(test_db, message_answer, fsm, fake_bot, monkeypatch):
    """Baho saqlanadi va o'rtacha ko'rsatiladi."""
    from handlers import bot_rating as module

    monkeypatch.setattr(module, "notify_admin", AsyncMock())
    await fsm.set_state(BotRatingFSM.rating)

    await bot_rating_pick(make_callback(user=make_user(), data="botr_9"), fsm)
    assert await fsm.get_state() == BotRatingFSM.comment

    await bot_rating_skip(
        make_callback(user=make_user(), data="botr_skip", message=make_message()),
        fsm,
        fake_bot,
    )

    stored = await db.get_user_bot_rating(USER_ID)
    assert stored["rating"] == 9
    assert await db.get_bot_rating() == (9.0, 1)


async def test_bot_rating_updates_existing_score(test_db, message_answer, fsm, fake_bot, monkeypatch):
    """Bitta foydalanuvchi bahosini yangilaydi — ikkinchi qator qo'shilmaydi."""
    from handlers import bot_rating as module

    monkeypatch.setattr(module, "notify_admin", AsyncMock())
    await db.set_bot_rating(USER_ID, 4, "yomon")

    await fsm.set_state(BotRatingFSM.rating)
    await bot_rating_pick(make_callback(user=make_user(), data="botr_10"), fsm)
    await bot_rating_skip(
        make_callback(user=make_user(), data="botr_skip", message=make_message()),
        fsm,
        fake_bot,
    )

    assert await db.get_bot_rating() == (10.0, 1)
    assert (await db.get_user_bot_rating(USER_ID))["rating"] == 10


async def test_low_score_notifies_admin(test_db, message_answer, fsm, fake_bot, monkeypatch):
    """Past baho adminlarga yuboriladi."""
    from handlers import bot_rating as module

    sent: list[str] = []
    monkeypatch.setattr(
        module,
        "notify_admin",
        AsyncMock(side_effect=lambda bot, text, markup=None: sent.append(text)),
    )

    await fsm.set_state(BotRatingFSM.rating)
    await bot_rating_pick(make_callback(user=make_user(), data="botr_2"), fsm)
    await bot_rating_skip(
        make_callback(user=make_user(), data="botr_skip", message=make_message()),
        fsm,
        fake_bot,
    )

    assert sent, "past baho haqida admin xabardor qilinmadi"
    assert "2/10" in sent[0]


async def test_good_score_does_not_notify_admin(test_db, message_answer, fsm, fake_bot, monkeypatch):
    """Yaxshi baho adminlarni bezovta qilmaydi."""
    from handlers import bot_rating as module

    sent: list[str] = []
    monkeypatch.setattr(module, "notify_admin", AsyncMock(side_effect=lambda bot, text, markup=None: sent.append(text)))
    await fsm.set_state(BotRatingFSM.rating)
    await bot_rating_pick(make_callback(user=make_user(), data="botr_8"), fsm)
    await bot_rating_skip(
        make_callback(user=make_user(), data="botr_skip", message=make_message()),
        fsm,
        fake_bot,
    )

    assert sent == []


async def test_bot_rating_average_computed(test_db):
    """O'rtacha baho bir necha foydalanuvchi bo'yanda to'g'ri chiqadi."""
    await db.set_bot_rating(1, 10)
    await db.set_bot_rating(2, 8)
    await db.set_bot_rating(3, 9)

    assert await db.get_bot_rating() == (9.0, 3)
