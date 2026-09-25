"""Ikkinchi to'plam yangi funksiyalar uchun testlar.

Qamrov:
* Baza kengaytmalari: sharhlar, obunalar, takliflar, bitimlar, referal,
  e'lon muddati va zaxira nusxa.
* Kartochkada reyting va amal muddati.
* Klaviaturalar: o'xshash e'lonlar, sharh, tahrirlash, yangilash, analitika.
* Handlerlar: sharh qoldirish, takliflar inbox, obuna, e'lon yangilash/
  tahrirlash, o'xshash e'lonlar, referal, admin analitika/zaxira.
* Fon vazifalari: muddat tekshiruvi, kunning tanlovi, kunlik zaxira.

Barcha testlar tarmoqqa murojaat qilmaydi.
"""

from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

import config
import keyboards
from database import db
from handlers.admin import (
    adm_analytics,
    adm_backup,
    approve_listing,
    deal_status_cb,
)
from handlers.common import (
    blacklist_warning,
    format_listing_caption,
    handle_referral_start,
    show_referral,
)
from handlers.inbox import offer_accept, offer_reject, show_inbox
from handlers.my_listings import (
    edit_contact_apply,
    edit_field_start,
    edit_listing_start,
    edit_price_apply,
    renew_listing,
)
from handlers.offers import offer_amount
from handlers.reviews import review_comment, review_rating, review_start
from handlers.sell import sell_finish
from handlers.subscriptions import (
    notify_subscribers,
    saved_delete,
    saved_keyword,
    saved_new,
    saved_price,
)
from keyboards import (
    BTN_INBOX,
    BTN_REFERRAL,
    BTN_SAVED_SEARCH,
    MAIN_MENU_ROWS,
    admin_panel_kb,
    listing_action_kb,
    my_listing_kb,
    saved_search_label,
    vip_kb,
)
from main import (
    expire_overdue_listings,
    listing_expiry_task,
    run_backup,
    send_featured_post,
)
from states import AdminFSM, EditFSM, OfferFSM, ReviewFSM, SavedSearchFSM, SellFSM

from conftest import ADMIN_ID, USER_ID, make_callback, make_message, make_user

TEST_BOT_USERNAME = "mlbb_market_test_bot"


# ---------------------------------------------------------------------------
# Fixture'lar
# ---------------------------------------------------------------------------
@pytest.fixture
async def test_db(tmp_path):
    """Vaqtinchalik SQLite baza bilan global `db` singletonini ishlatadi."""
    old_path = db.path
    old_admins = set(db.admin_ids)
    db.path = str(tmp_path / "features2.sqlite3")

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
    """`Message.edit_*` chaqiruvlarini soxtalashtiradi va kuzatish imkonini beradi."""
    mocks = SimpleNamespace(
        edit_text=AsyncMock(return_value=True),
        edit_reply_markup=AsyncMock(return_value=True),
        edit_caption=AsyncMock(return_value=True),
    )
    monkeypatch.setattr("aiogram.types.Message.edit_text", mocks.edit_text)
    monkeypatch.setattr("aiogram.types.Message.edit_reply_markup", mocks.edit_reply_markup)
    monkeypatch.setattr("aiogram.types.Message.edit_caption", mocks.edit_caption)
    return mocks


async def _make_sell_listing(
    *,
    user_id: int = USER_ID,
    price: int = 2_000_000,
    mode: str = "sell",
    status: str = "active",
    photos: list[str] | None = None,
    channel_msg_id: int | None = None,
    rank: str = "Mythic Glory",
) -> dict:
    """Test uchun e'lon yaratadi va qaytaradi."""
    listing_id = await db.create_listing(
        user_id=user_id,
        listing_type="sell",
        listing_mode=mode,
        trade_wanted="Ling Collector" if mode == "trade" else None,
        rank_info=rank,
        skins_info="45 ta skin, 8 collector",
        price_numeric=None if mode == "trade" else price,
        price_display="" if mode == "trade" else f"{price:,} soʻm".replace(",", " "),
        contact="@seller",
        description="Test eʼlon",
        is_vip=0,
        photos=photos if photos is not None else ["AAA"],
        status=status,
    )
    if channel_msg_id:
        await db.set_channel_message_id(listing_id, channel_msg_id)
    listing = await db.get_listing(listing_id)
    assert listing is not None
    return listing


def _callbacks(markup) -> list[str]:
    """Klaviaturdagi callback_data ro'yxati."""
    return [
        btn.callback_data
        for row in markup.inline_keyboard
        for btn in row
        if btn.callback_data
    ]


# ---------------------------------------------------------------------------
# 1. Baza: jadvallar, migratsiyalar va yangi metodlar
# ---------------------------------------------------------------------------
async def test_new_tables_and_columns_exist(test_db):
    """Yangi jadvallar va ustunlar mavjud, qayta ulanish xatolik bermaydi."""
    async with db.conn.execute("PRAGMA table_info(listings)") as cursor:
        listing_columns = {row["name"] for row in await cursor.fetchall()}
    async with db.conn.execute("PRAGMA table_info(users)") as cursor:
        user_columns = {row["name"] for row in await cursor.fetchall()}
    async with db.conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    ) as cursor:
        tables = {row["name"] for row in await cursor.fetchall()}

    assert "expires_at" in listing_columns
    assert {"referred_by", "free_vip"} <= user_columns
    assert {"reviews", "saved_searches", "offers", "deals"} <= tables

    # Migratsiya idempotent
    await db.close()
    await db.connect()
    async with db.conn.execute("PRAGMA table_info(users)") as cursor:
        again = {row["name"] for row in await cursor.fetchall()}
    assert {"referred_by", "free_vip"} <= again


async def test_create_listing_sets_expiry(test_db):
    """Yangi e'londa amal muddati avtomatik belgilanadi."""
    listing = await _make_sell_listing()
    assert listing["expires_at"]

    await db.touch_listing_expiry(int(listing["id"]), days=1)
    refreshed = await db.get_listing(int(listing["id"]))
    assert refreshed["expires_at"] != listing["expires_at"]


async def test_add_user_reports_new_flag(test_db):
    """`add_user` yangi foydalanuvchi uchun True, takroriy uchun False."""
    assert await db.add_user(1001, "yangi", "Yangi") is True
    assert await db.add_user(1001, "yangi", "Yangi") is False


async def test_referral_flow(test_db):
    """Referal bir marta qayd etiladi va VIP kredit beriladi."""
    await db.add_user(2001, "taklif", "Taklif qiluvchi")
    await db.add_user(2002, "dost", "Doʻst")

    assert await db.set_referrer(2002, 2001) is True
    assert await db.set_referrer(2002, 9999) is False  # allaqachon biriktirilgan
    assert await db.set_referrer(2001, 2001) is False  # o'zini taklif qilish

    assert await db.count_referrals(2001) == 1
    assert await db.add_free_vip(2001, 2) == 2
    assert await db.consume_free_vip(2001) is True
    assert await db.get_free_vip(2001) == 1
    assert await db.consume_free_vip(2001) is True
    assert await db.consume_free_vip(2001) is False


async def test_seller_rating_updates_on_second_review(test_db):
    """Bir foydalanuvchi sharhi yangilanadi va o'rtacha baho qayta hisoblanadi."""
    listing = await _make_sell_listing()
    listing_id = int(listing["id"])

    assert await db.add_review(listing_id, USER_ID, 3001, 5, "zoʻr") is True
    assert await db.add_review(listing_id, USER_ID, 3002, 1, "yomon") is True
    score, count = await db.get_seller_rating(USER_ID)
    assert count == 2
    assert score == 3.0

    # Takroriy sharh — yangilanadi, count oshmaydi
    assert await db.add_review(listing_id, USER_ID, 3001, 4, "oʻzgardi") is True
    score, count = await db.get_seller_rating(USER_ID)
    assert count == 2
    assert score == 2.5
    assert await db.has_reviewed(3001, USER_ID) is True
    assert await db.has_reviewed(3009, USER_ID) is False
    assert len(await db.get_seller_reviews(USER_ID)) == 2


async def test_saved_search_matching(test_db):
    """Obuna narx oralig'i va kalit so'z bo'yicha mos e'lonni topadi."""
    listing = await _make_sell_listing(price=1_000_000)

    await db.add_saved_search(4001, 500_000, 1_500_000, "mythic")
    await db.add_saved_search(4002, 500_000, 900_000, "")   # narx mos emas
    await db.add_saved_search(4003, None, None, "kof")       # kalit so'z yo'q
    await db.add_saved_search(USER_ID, None, None, "")       # e'lon egasi -> e'tiborsiz

    matches = await db.match_saved_searches(listing)
    assert [m["user_id"] for m in matches] == [4001]

    # Narx tushsa ham mos keladi
    await db.update_listing_price(int(listing["id"]), 700_000, "700 000 soʻm")
    updated = await db.get_listing(int(listing["id"]))
    assert {m["user_id"] for m in await db.match_saved_searches(updated)} == {4001, 4002}


async def test_saved_search_delete(test_db):
    """Obunani o'chirish faqat egasi uchun ishlaydi."""
    search_id = await db.add_saved_search(4100, None, None, "")
    assert await db.remove_saved_search(search_id, user_id=9999) is False
    assert await db.remove_saved_search(search_id, user_id=4100) is True
    assert await db.get_saved_searches(4100) == []


async def test_offer_lifecycle(test_db):
    """Taklif saqlanadi, holati o'zgaradi va tomonlar bo'yicha o'qiladi."""
    listing = await _make_sell_listing()
    listing_id = int(listing["id"])

    offer_id = await db.create_offer(listing_id, 5001, USER_ID, amount=1_500_000)
    offer = await db.get_offer(offer_id)
    assert offer is not None
    assert offer["status"] == "pending"
    assert offer["amount"] == 1_500_000
    assert offer["is_trade"] == 0

    assert await db.count_pending_offers(USER_ID) == 1
    assert await db.update_offer_status(offer_id, "accepted") is not None
    assert await db.count_pending_offers(USER_ID) == 0
    assert [o["id"] for o in await db.get_user_offers(5001, "buyer")] == [offer_id]
    assert [o["id"] for o in await db.get_user_offers(USER_ID, "seller")] == [offer_id]

    # Barter taklifi matn ko'rinishida saqlanadi
    trade_offer = await db.create_offer(
        listing_id, 5002, USER_ID, offer_text="Mythic Glory 90kof", is_trade=True
    )
    stored = await db.get_offer(trade_offer)
    assert stored["is_trade"] == 1
    assert stored["amount"] is None


async def test_deal_lifecycle(test_db):
    """Bitim yaratiladi, holati o'zgaradi va ishtirokchilar ko'radi."""
    listing = await _make_sell_listing()
    listing_id = int(listing["id"])

    deal_id = await db.create_deal(listing_id, USER_ID, 6001, 2_000_000)
    deal = await db.get_deal(deal_id)
    assert deal is not None
    assert deal["status"] == "new"

    updated = await db.update_deal_status(deal_id, "garant")
    assert updated is not None
    assert updated["status"] == "garant"

    assert [d["id"] for d in await db.get_user_deals(6001)] == [deal_id]
    assert [d["id"] for d in await db.get_user_deals(USER_ID)] == [deal_id]
    assert await db.update_deal_status(9_999, "done") is None


async def test_expired_and_featured_listings(test_db):
    """Muddati o'tgan e'lonlar topiladi va tanlov VIP e'lonni tanlaydi."""
    normal = await _make_sell_listing(price=900_000)
    vip = await _make_sell_listing(price=3_000_000)

    # VIP belgisini to'g'ridan-to'g'ri o'rnatamiz
    await db.conn.execute("UPDATE listings SET is_vip = 1 WHERE id = ?", (int(vip["id"]),))
    await db.conn.commit()

    assert await db.get_expired_listings() == []

    await db.conn.execute(
        "UPDATE listings SET expires_at = '2020-01-01T00:00:00+00:00' WHERE id = ?",
        (int(normal["id"]),),
    )
    await db.conn.commit()
    assert [item["id"] for item in await db.get_expired_listings()] == [int(normal["id"])]

    featured = await db.get_featured_listing()
    assert featured is not None
    assert featured["id"] == vip["id"]


async def test_similar_listings_by_price_and_rank(test_db):
    """O'xshash e'lonlar narx oralig'i bo'yicha tanlanadi."""
    base = await _make_sell_listing(price=1_000_000)
    close = await _make_sell_listing(price=1_200_000)
    far = await _make_sell_listing(price=9_000_000)

    similar = await db.get_similar_listings(int(base["id"]))
    ids = [item["id"] for item in similar]
    assert close["id"] in ids
    assert far["id"] not in ids
    assert base["id"] not in ids


async def test_daily_activity_and_top_sellers(test_db):
    """Kunlik faollik va eng faol sotuvchilar hisobotlari."""
    await db.add_user(7001, "a", "A")
    listing = await _make_sell_listing(user_id=7001)

    activity = await db.get_daily_activity(days=7)
    assert len(activity) == 7
    assert activity[-1]["users"] == 1
    assert activity[-1]["listings"] == 1
    assert activity[-1]["sold"] == 0

    await db.update_listing_status(int(listing["id"]), "sold")
    top = await db.get_top_sellers(days=30, limit=5)
    assert top == [{"user_id": 7001, "count": 1}]

    after = await db.get_daily_activity(days=7)
    assert after[-1]["sold"] == 1


async def test_backup_to_creates_file(test_db, tmp_path):
    """`backup_to` haqiqiy nusxa faylini yaratadi."""
    await db.add_user(8001, "b", "B")
    dest = str(tmp_path / "nested" / "backup.sqlite3")

    assert await db.backup_to(dest) is True
    assert os.path.exists(dest)
    assert os.path.getsize(dest) > 0


# ---------------------------------------------------------------------------
# 2. Kartochka matni: reyting va muddat
# ---------------------------------------------------------------------------
async def test_caption_shows_rating_and_expiry(test_db):
    """Kartochkada sotuvchi reytingi va amal muddati ko'rinadi."""
    listing = await _make_sell_listing()
    caption = format_listing_caption(
        listing, seller_label="@seller", seller_rating=(4.5, 10)
    )

    assert "👤 Sotuvchi: @seller" in caption
    assert "⭐️ Reyting: <b>4.5 ★★★★☆ (10 ta sharh)</b>" in caption
    assert "⏳ Amal muddati:" in caption

    fresh = format_listing_caption(listing, seller_label="@seller", seller_rating=(0.0, 0))
    assert "yangi sotuvchi" in fresh


async def test_caption_hides_rating_for_buy_requests(test_db):
    """Xaridor so'rovlarida sotuvchi reytingi ko'rsatilmaydi."""
    listing_id = await db.create_listing(
        user_id=USER_ID,
        listing_type="buy",
        rank_info="Sotib olish: Mythic Glory kerak",
        photos=[],
        status="active",
    )
    listing = await db.get_listing(listing_id)
    caption = format_listing_caption(listing, seller_label="@buyer", seller_rating=(4.0, 3))
    assert "Reyting" not in caption


async def test_expired_listing_banner(test_db):
    """Muddati tugagan e'lon alohida ogohlantirish ko'rsatadi."""
    listing = await _make_sell_listing()
    await db.update_listing_status(int(listing["id"]), "expired")
    updated = await db.get_listing(int(listing["id"]))

    caption = format_listing_caption(updated)
    assert "amal muddati tugagan" in caption


# ---------------------------------------------------------------------------
# 3. Klaviaturalar
# ---------------------------------------------------------------------------
async def test_listing_action_kb_has_similar_and_review(test_db, bot_username):
    """Aktiv e'lon kartochnasida sharh tugmasi yo'q, sharhlarni ko'rish bor."""
    listing = await _make_sell_listing()
    callbacks = _callbacks(listing_action_kb(listing))

    assert f"sim_{listing['id']}" in callbacks
    assert f"rvw_{listing['id']}" not in callbacks, "savdo tugagandan keyin emas"
    assert f"rvws_{USER_ID}" in callbacks


async def test_sold_listing_has_review_button(test_db, bot_username):
    """Sotilgan e'lon kartochnasida baho qo'yish tugmasi chiqadi."""
    listing = await _make_sell_listing(status="sold")
    callbacks = _callbacks(listing_action_kb(listing))

    assert f"rvw_{listing['id']}" in callbacks
    assert f"rvws_{USER_ID}" in callbacks


async def test_buy_listing_has_no_review_button(test_db, bot_username):
    """Xaridor so'rovida sharh tugmasi yo'q, o'xshashlar tugmasi bor."""
    listing_id = await db.create_listing(
        user_id=USER_ID, listing_type="buy", rank_info="Kerak", photos=[], status="active"
    )
    listing = await db.get_listing(listing_id)
    callbacks = _callbacks(listing_action_kb(listing))

    assert f"sim_{listing_id}" in callbacks
    assert not any(cb.startswith("rvw_") for cb in callbacks)


async def test_my_listing_kb_renew_for_expired(test_db, bot_username):
    """Muddati tugagan e'londa «Yangilash» tugmasi chiqadi."""
    listing = await _make_sell_listing(status="expired")
    callbacks = _callbacks(my_listing_kb(listing))

    assert f"renew_{listing['id']}" in callbacks
    assert not any(cb.startswith("bump_") for cb in callbacks)


async def test_my_listing_kb_edit_and_bump_for_active(test_db, bot_username):
    """Aktiv e'londa tahrirlash va UP tugmalari bor."""
    listing = await _make_sell_listing(status="active")
    callbacks = _callbacks(my_listing_kb(listing))

    assert f"edit_{listing['id']}" in callbacks
    assert f"bump_{listing['id']}" in callbacks
    assert f"drop_price_{listing['id']}" in callbacks
    assert not any(cb.startswith("renew_") for cb in callbacks)


async def test_my_listing_kb_edit_available_for_pending(test_db, bot_username):
    """Moderatsiyadagi e'lonni ham tahrirlash mumkin (UP esa yo'q)."""
    listing = await _make_sell_listing(status="pending")
    callbacks = _callbacks(my_listing_kb(listing))

    assert f"edit_{listing['id']}" in callbacks
    assert not any(cb.startswith("bump_") for cb in callbacks)


def test_vip_kb_shows_free_credit():
    """Bepul kredit bo'lsa alohida tugma ko'rsatiladi."""
    assert "vip_free" not in _callbacks(vip_kb("vip", 0))
    callbacks = _callbacks(vip_kb("vip", 3))
    assert "vip_free" in callbacks
    assert "vip_yes" in callbacks and "vip_no" in callbacks


def test_admin_panel_has_analytics_and_backup():
    """Admin panelda analitika va zaxira tugmalari bor."""
    callbacks = _callbacks(admin_panel_kb())
    assert "adm_analytics" in callbacks
    assert "adm_backup" in callbacks


def test_main_menu_contains_new_sections():
    """Asosiy menyuda yangi bo'limlar bir marta uchraydi."""
    buttons = [btn for row in MAIN_MENU_ROWS for btn in row]
    for label in (BTN_INBOX, BTN_SAVED_SEARCH, BTN_REFERRAL):
        assert label in buttons
        assert buttons.count(label) == 1


def test_saved_search_label_formats_ranges():
    """Obuna yorlig'i narx oralig'i va kalit so'zni ko'rsatadi."""
    assert saved_search_label({"min_price": None, "max_price": None, "keyword": ""}) == (
        "har qanday narx"
    )
    assert "100 000" in saved_search_label(
        {"min_price": None, "max_price": 100_000, "keyword": "mythic"}
    )
    assert "mythic" in saved_search_label(
        {"min_price": None, "max_price": 100_000, "keyword": "mythic"}
    )
    assert "400 000" in saved_search_label(
        {"min_price": 400_000, "max_price": None, "keyword": ""}
    )


# ---------------------------------------------------------------------------
# 4. Sharh qoldirish oqimi
# ---------------------------------------------------------------------------
async def test_review_flow_saves_and_notifies(
    test_db, fsm, fake_bot, message_answer, callback_answer
):
    """Sharh saqlanadi, sotuvchi va admin xabardor qilinadi."""
    listing = await _make_sell_listing(user_id=USER_ID, status="sold")
    listing_id = int(listing["id"])
    buyer = make_user(user_id=9001, username="buyer")
    # Savdo bo'lgani uchun xaridor e'lonni xaridor sifatida olgan bo'lsin
    await db.create_deal(listing_id=listing_id, seller_id=USER_ID, buyer_id=9001)

    await review_start(make_callback(user=buyer, data=f"rvw_{listing_id}"), fsm)
    assert await fsm.get_state() == ReviewFSM.rating

    await review_rating(make_callback(user=buyer, data="rvwr_5"), fsm)
    assert await fsm.get_state() == ReviewFSM.comment

    await review_comment(make_message(user=buyer, text="Tez va ishonchli"), fsm, fake_bot)
    assert await fsm.get_state() is None

    score, count = await db.get_seller_rating(USER_ID)
    assert (score, count) == (5.0, 1)

    # Sotuvchiga xabar ketdi
    assert any(call.args[0] == USER_ID for call in fake_bot.send_message.await_args_list)
    seller_text = next(
        call.args[1] for call in fake_bot.send_message.await_args_list if call.args[0] == USER_ID
    )
    assert "yangi sharh" in seller_text
    answers = [call.args[0] for call in message_answer.await_args_list]
    assert any("Sharhingiz uchun rahmat" in text for text in answers)
    # Joriy reyting va past baho bo'lmagani uchun admin xabari yo'q
    assert any("4.0" in text or "5.0" in text for text in answers)


async def test_review_skips_comment_and_handles_missing_state(test_db, fsm, fake_bot):
    """Izohsiz sharh ham saqlanadi; holat yo'qolsa xato ko'rsatiladi."""
    listing = await _make_sell_listing(user_id=USER_ID)
    await fsm.set_state(ReviewFSM.comment)
    await fsm.update_data(review_listing_id=int(listing["id"]))

    from handlers.reviews import _save_review

    await _save_review(make_message(user=make_user(user_id=9002)), fsm, fake_bot, comment="")
    _, count = await db.get_seller_rating(USER_ID)
    assert count == 0  # reyting tanlanmagan — saqlanmaydi


async def test_review_blocked_until_sale_completes(test_db, fsm, callback_answer):
    """Savdo tugagandan oldin sharh qoldirib bo'lmaydi."""
    listing = await _make_sell_listing(user_id=USER_ID, status="active")
    buyer = make_user(user_id=9010, username="buyer")

    await review_start(make_callback(user=buyer, data=f"rvw_{listing['id']}"), fsm)

    assert await fsm.get_state() is None
    assert "savdo tugagandan keyin" in callback_answer.await_args.args[0].lower()


async def test_review_rejects_non_buyer(test_db, fsm, callback_answer):
    """Sotib olmagan foydalanuvchi sharh qoldira olmaydi."""
    listing = await _make_sell_listing(user_id=USER_ID, status="sold")
    stranger = make_user(user_id=9011, username="stranger")

    await review_start(make_callback(user=stranger, data=f"rvw_{listing['id']}"), fsm)

    assert await fsm.get_state() is None
    assert "xaridor sifatida olmagan" in callback_answer.await_args.args[0]


async def test_review_rejects_cancelled_deal(test_db, fsm, callback_answer):
    """Bekor qilingan bitim bo'yicha sharh qoldirilmaydi."""
    listing = await _make_sell_listing(user_id=USER_ID, status="sold")
    buyer = make_user(user_id=9012, username="buyer")
    deal_id = await db.create_deal(
        listing_id=int(listing["id"]), seller_id=USER_ID, buyer_id=9012
    )
    await db.update_deal_status(deal_id, "cancelled")

    await review_start(make_callback(user=buyer, data=f"rvw_{listing['id']}"), fsm)

    assert await fsm.get_state() is None


async def test_buyer_deal_and_listing_buyers(test_db):
    """Bitimni xaridor bo'yicha va e'lon xaridorlarini topadi."""
    listing = await _make_sell_listing(user_id=USER_ID, status="sold")
    listing_id = int(listing["id"])
    await db.create_deal(listing_id=listing_id, seller_id=USER_ID, buyer_id=9101)
    await db.create_deal(listing_id=listing_id, seller_id=USER_ID, buyer_id=9101)
    await db.create_deal(listing_id=listing_id, seller_id=USER_ID, buyer_id=9102)

    deal = await db.get_buyer_deal(listing_id, 9101)
    assert deal is not None
    assert int(deal["buyer_id"]) == 9101
    assert await db.get_buyer_deal(listing_id, 9999) is None

    assert sorted(await db.get_listing_buyers(listing_id)) == [9101, 9102]


async def test_recent_reviews_feed_paginates(test_db):
    """Oxirgi sharhlar ro'yxati sahifalab ko'rsatiladi."""
    listing = await _make_sell_listing(user_id=USER_ID, status="sold")
    listing_id = int(listing["id"])
    for index in range(7):
        await db.add_review(listing_id, USER_ID, 9200 + index, 4, f"sharh {index}")

    first = await db.get_recent_reviews(limit=5, offset=0)
    second = await db.get_recent_reviews(limit=5, offset=5)
    assert len(first) == 5
    assert len(second) == 2
    # Eng yangisi birinchi turadi
    assert first[0]["comment"] == "sharh 6"


async def test_reviews_menu_shows_feed(test_db, message_answer):
    """Menyu tugmasi oxirgi sharhlarni ko'rsatadi."""
    from handlers.reviews import reviews_menu
    from keyboards import BTN_REVIEWS

    listing = await _make_sell_listing(user_id=USER_ID, status="sold")
    await db.add_review(int(listing["id"]), USER_ID, 9301, 5, "Zo'r xizmat")

    await reviews_menu(make_message(user=make_user(user_id=9302), text=BTN_REVIEWS))

    assert "Oxirgi sharhlar" in message_answer.await_args.args[0]
    assert "Zo'r xizmat" in message_answer.await_args.args[0]


async def test_reviews_menu_handles_empty(test_db, message_answer):
    """Hali sharh yo'q bo'lsa tushunarli xabar chiqadi."""
    from handlers.reviews import reviews_menu
    from keyboards import BTN_REVIEWS

    await reviews_menu(make_message(user=make_user(user_id=9303), text=BTN_REVIEWS))

    assert "Sharhlar" in message_answer.await_args.args[0]
    assert "hech kim sharh qoldirmagan" in message_answer.await_args.args[0]


async def test_seller_stats_counts_sales_and_reviews(test_db):
    """Sotuvchi statistikasi: reyting, sharhlar va sotilganlar soni."""
    listing = await _make_sell_listing(user_id=USER_ID, status="sold")
    await _make_sell_listing(user_id=USER_ID, status="active")
    await db.add_review(int(listing["id"]), USER_ID, 9401, 5, "zoʻr")
    await db.add_review(int(listing["id"]), USER_ID, 9402, 4, "yaxshi")

    stats = await db.get_seller_stats(USER_ID)
    assert stats["reviews"] == 2
    assert stats["rating"] == 4.5
    assert stats["sold"] == 1
    assert stats["active"] == 1


async def test_seller_stats_for_new_seller(test_db):
    """Hali hech nima sotmagan sotuvchi uchun reyting yo'q."""
    stats = await db.get_seller_stats(9501)
    assert stats["rating"] == 0.0
    assert stats["reviews"] == 0
    assert stats["sold"] == 0


# ---------------------------------------------------------------------------
# Doimiy disk tekshiruvi
# ---------------------------------------------------------------------------
def test_storage_is_persistent_false_on_shared_mount(monkeypatch):
    """Baza kod bilan bir xil mountda bo'lsa — vaqtincha disk (ephemeral)."""
    from database import storage_is_persistent

    monkeypatch.setattr("database._longest_mount", lambda path: "/")
    assert storage_is_persistent("/var/data/market.sqlite3") is False


def test_storage_is_persistent_true_on_separate_disk(monkeypatch):
    """Baza alohida mountda bo'lsa — doimiy disk ulangan."""
    from database import storage_is_persistent

    mounts = {"/var/data/market.sqlite3": "/var/data", "/opt/render/project/src": "/"}
    monkeypatch.setattr("database._longest_mount", lambda path: mounts.get(path, "/"))
    assert storage_is_persistent("/var/data/market.sqlite3") is True


def test_storage_report_warns_on_render_without_disk(monkeypatch):
    """Render'da disk yo'q bo'lsa — xavfli ogohlantirish chiqadi."""
    from database import storage_report

    monkeypatch.setattr("database.on_render", lambda: True)
    monkeypatch.setattr("database._longest_mount", lambda path: "/")
    report = storage_report("/var/data/market.sqlite3")
    assert "DOIMIY DISK ULanmagan" in report
    assert "eʼlonlar" in report


def test_storage_report_ok_on_render_with_disk(monkeypatch):
    """Render'da disk ulangan bo'lsa — xatolik xabari chiqmaydi."""
    from database import storage_report

    monkeypatch.setattr("database.on_render", lambda: True)
    mounts = {"/var/data/market.sqlite3": "/var/data", "/opt/render/project/src": "/"}
    monkeypatch.setattr("database._longest_mount", lambda path: mounts.get(path, "/"))
    report = storage_report("/var/data/market.sqlite3")
    assert "DOIMIY DISK ULanmagan" not in report
    assert "Doimiy diskka ulangan" in report


def test_storage_report_is_calm_outside_render(monkeypatch):
    """Render'dan tashqarida xavfli ogohlantirish ko'rsatilmaydi."""
    from database import storage_report

    monkeypatch.setattr("database.on_render", lambda: False)
    monkeypatch.setattr("database._longest_mount", lambda path: "/")
    assert "DOIMIY DISK ULanmagan" not in storage_report("/tmp/market.sqlite3")


def _fake_proc_mounts(content: str):
    """`open` o'rniga beriladigan soxta `/proc/mounts` o'quvchi."""
    import io

    class _Reader:
        def __init__(self, *args, **kwargs):
            self._buffer = io.StringIO(content)

        def __enter__(self):
            return self._buffer

        def __exit__(self, *args):
            return False

    return _Reader


def test_longest_mount_picks_deepest_match(tmp_path, monkeypatch):
    """Eng chuqur mos mount tanlanadi."""
    from database import _longest_mount

    deep = tmp_path / "data"
    deep.mkdir()
    target = deep / "market.sqlite3"
    target.touch()
    # Ikkita mount: yuqorisi va aniqroq pastkisi — chuqurroq bo'lishi kerak
    monkeypatch.setattr("builtins.open", _fake_proc_mounts(f"dev1 / ext4 rw\ndev2 {deep} ext4 rw\n"))
    assert _longest_mount(str(target)) == str(deep)


def test_longest_mount_handles_missing_proc(tmp_path, monkeypatch):
    """`/proc/mounts` yo'q bo'lsa — bo'sh satr qaytariladi (xatoma emas)."""
    from database import _longest_mount

    def _boom(*args, **kwargs):
        raise OSError("yo'q")

    monkeypatch.setattr("builtins.open", _boom)
    assert _longest_mount(str(tmp_path / "x.db")) == ""


async def test_seller_profile_shows_rating_and_stats(test_db, callback_answer, message_answer):
    """Sotuvchi profili reyting va statistikani ko'rsatadi."""
    from handlers.reviews import seller_profile

    listing = await _make_sell_listing(user_id=USER_ID, status="sold")
    await _make_sell_listing(user_id=USER_ID, status="active")
    for index, rating in enumerate((5, 5, 4)):
        await db.add_review(int(listing["id"]), USER_ID, 9601 + index, rating, "Juda ishonchli")

    await seller_profile(make_callback(data=f"sp_{USER_ID}"))

    text = message_answer.await_args.args[0]
    assert "Reyting" in text
    assert "Juda ishonchli" in text
    assert "Sotilgan eʼlonlar" in text
    assert "Ishonchli sotuvchi" in text, "3+ ta yuqori sharh ishonchli belgisini beradi"


async def test_seller_profile_for_unrated_seller(test_db, message_answer):
    """Reytingi yo'q sotuvchi uchun tushunarli holat ko'rsatiladi."""
    from handlers.reviews import seller_profile

    await seller_profile(make_callback(data="sp_9701"))

    text = message_answer.await_args.args[0]
    assert "Hali reyting yoʻq" in text
    assert "yangi sotuvchi" in text


async def test_listing_card_has_seller_profile_button(test_db, bot_username):
    """Kartochkada sotuvchi reytingini ochish tugmasi bor."""
    listing = await _make_sell_listing()
    assert f"sp_{USER_ID}" in _callbacks(listing_action_kb(listing))


async def test_my_listings_shows_own_rating(test_db, fsm, fake_bot, message_answer):
    """Sotuvchi o'z reytingini «Mening e'lonlarim» da ko'radi."""
    from handlers.my_listings import show_my_listings
    from keyboards import BTN_MY_LISTINGS

    listing = await _make_sell_listing(user_id=USER_ID, status="sold")
    await db.add_review(int(listing["id"]), USER_ID, 9801, 5, "Zo'r")

    await show_my_listings(
        make_message(user=make_user(user_id=USER_ID, username="seller"), text=BTN_MY_LISTINGS),
        fake_bot,
    )

    header = message_answer.await_args_list[0].args[0]
    assert "Sizning reytingiz" in header
    assert "Sotilgan" in header


async def test_review_rejects_own_listing(test_db, fsm, callback_answer):
    """O'z e'loniga sharh qoldirib bo'lmaydi."""
    listing = await _make_sell_listing(user_id=USER_ID)

    await review_start(make_callback(data=f"rvw_{listing['id']}"), fsm)

    assert await fsm.get_state() is None
    assert callback_answer.await_args.kwargs.get("show_alert") is True


async def test_review_rejects_trade_listing(test_db, fsm, callback_answer):
    """Barter e'loniga sharh qoldirilmaydi."""
    listing = await _make_sell_listing(mode="trade", user_id=USER_ID)
    stranger = make_user(user_id=9003)

    await review_start(make_callback(user=stranger, data=f"rvw_{listing['id']}"), fsm)

    assert await fsm.get_state() is None
    assert callback_answer.await_args.kwargs.get("show_alert") is True


# ---------------------------------------------------------------------------
# 5. Takliflar va bitimlar
# ---------------------------------------------------------------------------
async def test_offer_flow_persists_and_gives_seller_buttons(
    test_db, fsm, fake_bot, message_answer
):
    """Taklif bazaga saqlanadi va sotuvchiga javob tugmalari boradi."""
    listing = await _make_sell_listing(price=2_000_000, user_id=USER_ID)
    buyer = make_user(user_id=9101, username="xaridor")

    await fsm.set_state(OfferFSM.waiting_amount)
    await fsm.update_data(offer_listing_id=int(listing["id"]))

    await offer_amount(make_message(user=buyer, text="1700000"), fsm, fake_bot)

    assert await fsm.get_state() is None
    offers = await db.get_user_offers(USER_ID, "seller")
    assert len(offers) == 1
    assert offers[0]["amount"] == 1_700_000

    seller_call = next(
        call for call in fake_bot.send_message.await_args_list if call.args[0] == USER_ID
    )
    markup = seller_call.kwargs["reply_markup"]
    assert f"off_ok_{offers[0]['id']}" in _callbacks(markup)
    assert "Taklifingiz" in message_answer.await_args.args[0]


async def test_offer_accept_and_reject(
    test_db, fake_bot, callback_answer, message_answer
):
    """Sotuvchi taklifni qabul qiladi yoki rad etadi, xaridor xabardor bo'ladi."""
    listing = await _make_sell_listing(user_id=USER_ID)
    listing_id = int(listing["id"])
    offer_id = await db.create_offer(listing_id, 9201, USER_ID, amount=1_800_000)
    seller = make_user(user_id=USER_ID)

    await offer_accept(make_callback(user=seller, data=f"off_ok_{offer_id}"), fake_bot)
    assert (await db.get_offer(offer_id))["status"] == "accepted"
    assert any(call.args[0] == 9201 for call in fake_bot.send_message.await_args_list)

    # Ikkinchi marta javob berib bo'lmaydi
    await offer_accept(make_callback(user=seller, data=f"off_ok_{offer_id}"), fake_bot)
    assert callback_answer.await_args.kwargs.get("show_alert") is True

    second = await db.create_offer(listing_id, 9202, USER_ID, amount=1_500_000)
    await offer_reject(make_callback(user=seller, data=f"off_no_{second}"), fake_bot)
    assert (await db.get_offer(second))["status"] == "rejected"


async def test_offer_accept_rejects_stranger(test_db, fake_bot, callback_answer):
    """Boshqa foydalanuvchi taklifni qabul qila olmaydi."""
    listing = await _make_sell_listing(user_id=USER_ID)
    offer_id = await db.create_offer(int(listing["id"]), 9301, USER_ID, amount=1_000_000)
    stranger = make_user(user_id=9302)

    await offer_accept(make_callback(user=stranger, data=f"off_ok_{offer_id}"), fake_bot)

    assert (await db.get_offer(offer_id))["status"] == "pending"
    assert callback_answer.await_args.kwargs.get("show_alert") is True


async def test_offer_reply_reaches_buyer(test_db, fsm, fake_bot, message_answer):
    """Sotuvchi yozgan javob xaridorga yetib boradi."""
    from handlers.inbox import offer_reply_send, offer_reply_start

    listing = await _make_sell_listing(user_id=USER_ID)
    offer_id = await db.create_offer(int(listing["id"]), 9401, USER_ID, amount=1_500_000)
    seller = make_user(user_id=USER_ID)

    await offer_reply_start(make_callback(user=seller, data=f"off_msg_{offer_id}"), fsm)
    assert await fsm.get_state() == OfferFSM.waiting_reply

    await offer_reply_send(make_message(user=seller, text="1600000 boʻlsa kelishamiz"), fsm, fake_bot)

    assert await fsm.get_state() is None
    buyer_calls = [
        call for call in fake_bot.send_message.await_args_list if call.args[0] == 9401
    ]
    assert len(buyer_calls) == 1
    assert "1600000" in buyer_calls[0].args[1]
    assert "yuborildi" in message_answer.await_args.args[0]


async def test_show_inbox_lists_offers_and_deals(test_db, fake_bot, message_answer):
    """Inbox kelgan/yuborilgan takliflarni va bitimlarni ko'rsatadi."""
    listing = await _make_sell_listing(user_id=USER_ID)
    listing_id = int(listing["id"])
    await db.create_offer(listing_id, 9501, USER_ID, amount=1_200_000)
    await db.create_offer(listing_id, USER_ID, 9502, amount=1_100_000)
    await db.create_deal(listing_id, USER_ID, 9503, 1_000_000)

    await show_inbox(make_message(), fake_bot)

    texts = [call.args[1] for call in fake_bot.send_message.await_args_list]
    assert any("Kelgan taklif" in text for text in texts)
    assert any("Yuborilgan taklif" in text for text in texts)

    answers = [call.args[0] for call in message_answer.await_args_list]
    assert any("Bitimlarim" in text for text in answers)
    assert any("Bitim #" in text for text in answers)
    # Kelgan taklifda javob tugmalari bo'ladi
    received = next(
        call for call in fake_bot.send_message.await_args_list if "Kelgan taklif" in call.args[1]
    )
    assert "off_ok_" in "".join(_callbacks(received.kwargs["reply_markup"]))


async def test_show_inbox_empty_state(test_db, fake_bot, message_answer):
    """Taklif va bitim bo'lmasa tushunarli xabar chiqadi."""
    await show_inbox(make_message(), fake_bot)
    assert "taklif yoki bitim yoʻq" in message_answer.await_args.args[0].lower()


# ---------------------------------------------------------------------------
# 6. Saqlangan qidiruv (obuna)
# ---------------------------------------------------------------------------
async def test_saved_search_flow(test_db, fsm, message_answer, callback_answer):
    """Narx oralig'i va kalit so'z bo'yicha obuna yaratiladi."""
    await saved_new(make_callback(data="saved_new"), fsm)
    assert "narx oraligʻini" in message_answer.await_args.args[0].lower()

    await saved_price(make_callback(data="saved_p_400"), fsm)
    assert await fsm.get_state() == SavedSearchFSM.waiting_keyword

    await saved_keyword(make_message(text="Mythic Glory"), fsm)
    assert await fsm.get_state() is None

    searches = await db.get_saved_searches(USER_ID)
    assert len(searches) == 1
    assert searches[0]["min_price"] == 100_000
    assert searches[0]["max_price"] == 400_000
    assert searches[0]["keyword"] == "Mythic Glory"


async def test_saved_search_delete_callback(test_db, message_answer, callback_answer):
    """Obuna tugma orqali o'chiriladi."""
    search_id = await db.add_saved_search(USER_ID, None, None, "kof")

    await saved_delete(make_callback(data=f"saved_del_{search_id}"))

    assert await db.get_saved_searches(USER_ID) == []
    assert "oʻchirildi" in callback_answer.await_args.args[0]


async def test_notify_subscribers_sends_matching_listing(test_db, fake_bot):
    """Yangi e'lon obunaga mos kelsa foydalanuvchiga yuboriladi."""
    listing = await _make_sell_listing(price=1_000_000)
    await db.add_saved_search(9601, 500_000, 1_500_000, "mythic")
    await db.add_saved_search(9602, 5_000_000, None, "")

    sent = await notify_subscribers(fake_bot, listing)

    assert sent == 1
    assert any(call.args[0] == 9601 for call in fake_bot.send_message.await_args_list)
    assert not any(call.args[0] == 9602 for call in fake_bot.send_message.await_args_list)


async def test_approve_listing_notifies_subscribers(test_db, fake_bot):
    """E'lon tasdiqlanganda obunachilar xabardor qilinadi."""
    await db.add_saved_search(9701, None, None, "mythic")
    pending = await _make_sell_listing(status="pending", rank="Mythic Glory")

    ok, message = await approve_listing(fake_bot, int(pending["id"]))

    assert ok is True
    assert "chiqarildi" in message
    assert any(call.args[0] == 9701 for call in fake_bot.send_message.await_args_list)


# ---------------------------------------------------------------------------
# 7. Muddati tugagan e'lonni yangilash
# ---------------------------------------------------------------------------
async def test_renew_listing_reactivates_and_reposts(
    test_db, fake_bot, callback_answer, message_answer, bot_username
):
    """Muddati tugagan e'lon aktivlashadi va kanalga qayta joylanadi."""
    listing = await _make_sell_listing(status="expired", channel_msg_id=55)
    listing_id = int(listing["id"])
    await db.conn.execute(
        "UPDATE listings SET expires_at = '2020-01-01T00:00:00+00:00', status = 'expired'"
        " WHERE id = ?",
        (listing_id,),
    )
    await db.conn.commit()

    await renew_listing(make_callback(data=f"renew_{listing_id}"), fake_bot)

    updated = await db.get_listing(listing_id)
    assert updated["status"] == "active"
    assert updated["expires_at"] > "2025-01-01"
    assert updated["channel_msg_id"] == 901

    # Bitta rasmlik eski xabar o'chirildi
    assert any(
        call.kwargs.get("message_id") == 55
        for call in fake_bot.delete_message.await_args_list
    )
    assert "yangilandi" in message_answer.await_args.args[0]


async def test_renew_rejects_non_owner(test_db, fake_bot, callback_answer):
    """Boshqa foydalanuvchi e'lonni yangilay olmaydi."""
    listing = await _make_sell_listing(status="expired")
    await db.update_listing_status(int(listing["id"]), "expired")
    stranger = make_user(user_id=9801)

    await renew_listing(make_callback(user=stranger, data=f"renew_{listing['id']}"), fake_bot)

    assert callback_answer.await_args.kwargs.get("show_alert") is True


async def test_renew_rejects_active_listing(test_db, fake_bot, callback_answer):
    """Aktiv e'lonni «yangilash» mumkin emas."""
    listing = await _make_sell_listing(status="active")

    await renew_listing(make_callback(data=f"renew_{listing['id']}"), fake_bot)

    assert callback_answer.await_args.kwargs.get("show_alert") is True


# ---------------------------------------------------------------------------
# 8. E'lonni tahrirlash
# ---------------------------------------------------------------------------
async def test_edit_listing_menu_and_price_update(
    test_db, fsm, fake_bot, message_answer, callback_answer
):
    """Narx tahrirlanadi va kanal kartochkasi yangilanadi."""
    listing = await _make_sell_listing(price=2_000_000, channel_msg_id=77)
    listing_id = int(listing["id"])

    await edit_listing_start(make_callback(data=f"edit_{listing_id}"), fsm)
    assert "Qaysi maydonni" in message_answer.await_args.args[0]

    await edit_field_start(make_callback(data=f"editf_price_{listing_id}"), fsm)
    assert await fsm.get_state() == EditFSM.waiting_price

    await edit_price_apply(make_message(text="1800000"), fsm, fake_bot)

    updated = await db.get_listing(listing_id)
    assert updated["price_numeric"] == 1_800_000
    assert updated["price_display"] == "1 800 000 soʻm"
    assert updated["old_price"] is None

    edit_kwargs = fake_bot.edit_message_caption.await_args.kwargs
    assert edit_kwargs["message_id"] == 77
    assert "1 800 000 soʻm" in edit_kwargs["caption"]
    assert "tahrirlandi" in message_answer.await_args.args[0]


async def test_edit_contact_update(test_db, fsm, fake_bot, message_answer):
    """Aloqa ma'lumoti tahrirlanadi."""
    listing = await _make_sell_listing()
    listing_id = int(listing["id"])

    await edit_field_start(make_callback(data=f"editf_contact_{listing_id}"), fsm)
    assert await fsm.get_state() == EditFSM.waiting_contact

    await edit_contact_apply(make_message(text="@yangi_aloqa"), fsm, fake_bot)

    assert (await db.get_listing(listing_id))["contact"] == "@yangi_aloqa"


async def test_edit_description_too_short_rejected(test_db, fsm, message_answer):
    """Juda qisqa izoh qabul qilinmaydi va holat saqlanadi."""
    listing = await _make_sell_listing()
    await fsm.set_state(EditFSM.waiting_description)
    await fsm.update_data(edit_listing_id=int(listing["id"]), edit_field="desc")

    from handlers.my_listings import edit_description_apply

    await edit_description_apply(make_message(text="ab"), fsm, AsyncMock())

    assert await fsm.get_state() == EditFSM.waiting_description
    assert "juda qisqa" in message_answer.await_args.args[0]


async def test_edit_rejects_non_owner(test_db, fsm, callback_answer):
    """Boshqa foydalanuvchi e'lonni tahrirlay olmaydi."""
    listing = await _make_sell_listing()
    stranger = make_user(user_id=9901)

    await edit_listing_start(make_callback(user=stranger, data=f"edit_{listing['id']}"), fsm)

    assert callback_answer.await_args.kwargs.get("show_alert") is True


async def test_edit_price_not_available_for_trade(test_db, fsm, callback_answer):
    """Barter e'lonida narx tahrirlanmaydi."""
    listing = await _make_sell_listing(mode="trade")

    await edit_field_start(make_callback(data=f"editf_price_{listing['id']}"), fsm)

    assert await fsm.get_state() is None
    assert callback_answer.await_args.kwargs.get("show_alert") is True


# ---------------------------------------------------------------------------
# 9. O'xshash e'lonlar
# ---------------------------------------------------------------------------
async def test_similar_callback_sends_matches(test_db, fake_bot, callback_answer):
    """«🔎 O'xshash e'lonlar» tugmasi mos e'lonlarni yuboradi."""
    from handlers.catalog import similar_cb

    base = await _make_sell_listing(price=1_000_000)
    await _make_sell_listing(price=1_100_000)
    await _make_sell_listing(price=20_000_000)

    await similar_cb(make_callback(data=f"sim_{base['id']}"), fake_bot)

    captions = [
        call.kwargs["caption"] for call in fake_bot.send_photo.await_args_list
    ]
    assert len(captions) == 1
    assert "1 100 000 soʻm" in captions[0]
    assert "20 000 000" not in captions[0]


async def test_similar_callback_handles_no_matches(test_db, fake_bot, callback_answer):
    """Mos e'lon bo'lmasa foydalanuvchiga xabar beriladi."""
    from handlers.catalog import similar_cb

    alone = await _make_sell_listing(price=1_000_000)

    await similar_cb(make_callback(data=f"sim_{alone['id']}"), fake_bot)

    assert fake_bot.send_photo.await_count == 0
    assert callback_answer.await_args.kwargs.get("show_alert") is True


# ---------------------------------------------------------------------------
# 10. Referal
# ---------------------------------------------------------------------------
async def test_handle_referral_start_grants_credit(test_db, fake_bot):
    """Referal havolasi orqali kelgan do'st uchun VIP kredit beriladi."""
    await db.add_user(10_001, "referrer", "Taklif qiluvchi")
    newcomer = make_user(user_id=10_002, username="newbie")

    message = make_message(user=newcomer, text="/start ref_10001")
    await handle_referral_start(message, fake_bot, is_new=True)

    assert (await db.get_user(10_002))["referred_by"] == 10_001
    assert await db.get_free_vip(10_001) == config.REFERRAL_REWARD_VIP
    assert any(call.args[0] == 10_001 for call in fake_bot.send_message.await_args_list)


async def test_handle_referral_ignores_bad_payloads(test_db, fake_bot):
    """Noto'g'ri yoki mavjud bo'lmagan referal havolasi e'tiborsiz qoldiriladi."""
    await db.add_user(10_101, "a", "A")
    await db.add_user(10_102, "b", "B")
    user = make_user(user_id=10_102)

    for payload in ("/start", "/start ref_abc", "/start ref_999999", "/start other_5"):
        await handle_referral_start(make_message(user=user, text=payload), fake_bot, True)

    assert (await db.get_user(10_102))["referred_by"] is None
    assert fake_bot.send_message.await_count == 0

    # O'zini taklif qilish ham e'tiborsiz qoldiriladi
    self_user = make_user(user_id=10_101)
    await handle_referral_start(
        make_message(user=self_user, text="/start ref_10101"), fake_bot, True
    )
    assert (await db.get_user(10_101))["referred_by"] is None
    assert await db.get_free_vip(10_101) == 0


async def test_show_referral_text(test_db, message_answer, bot_username):
    """«🎁 Referal» bo'limi havola va statistikani ko'rsatadi."""
    await db.add_user(USER_ID, "tester", "Test User")
    await db.add_free_vip(USER_ID, 2)

    await show_referral(make_message())

    text = message_answer.await_args.args[0]
    assert "Referal dasturi" in text
    assert f"ref_{USER_ID}" in text
    assert "Bepul VIP eʼlonlar: <b>2</b>" in text


# ---------------------------------------------------------------------------
# 11. Firibgarlikka qarshi avtomatik tekshiruv
# ---------------------------------------------------------------------------
async def test_blacklist_warning_detects_identifier(test_db):
    """Qora ro'yxatdagi aloqa/username aniqlanadi."""
    await db.add_to_blacklist("@scammer_uz", "Pulni olib qochdi")

    by_username = await blacklist_warning(1, "scammer_uz", "")
    by_contact = await blacklist_warning(2, None, "@SCAMMER_UZ")
    by_id = await blacklist_warning(3, None, "")

    assert by_username is not None and "qora roʻyxat" in by_username.lower()
    assert by_contact is not None
    assert by_id is None


async def test_sell_finish_warns_admin_about_blacklisted_contact(test_db, fsm, fake_bot):
    """Shubhali aloqa bilan e'lon joylansa adminlarga ogohlantirish boradi."""
    await db.add_to_blacklist("@scammer_uz", "Firibgar")

    await fsm.set_state(SellFSM.photos)
    await fsm.update_data(
        rank_info="Mythic Glory",
        skins_info="40 skin",
        listing_mode="sell",
        price_numeric=1_000_000,
        price_display="1 000 000 soʻm",
        is_vip=0,
        contact="@scammer_uz",
        description="test",
        photos=["AAA"],
    )

    await sell_finish(make_message(text="✅ Tayyor"), fsm, fake_bot)

    warnings = [
        call.args[1]
        for call in fake_bot.send_message.await_args_list
        if "shubhali sotuvchi" in str(call.args[1]).lower()
    ]
    assert len(warnings) == 1
    assert "Firibgar" in warnings[0]


# ---------------------------------------------------------------------------
# 12. Admin: analitika, zaxira nusxa, bitim holati
# ---------------------------------------------------------------------------
async def test_adm_analytics_text(test_db, message_edits, callback_answer):
    """Analitika bo'limi kunlik ko'rsatkichlarni chiqaradi."""
    admin_user = make_user(user_id=ADMIN_ID, username="boss")
    await db.add_user(11_001, "sotuvchi", "Sotuvchi")
    await _make_sell_listing(user_id=11_001, status="active")

    await adm_analytics(make_callback(user=admin_user, data="adm_analytics"))

    text = message_edits.edit_text.await_args.args[0]
    assert "Analitika — oxirgi 7 kun" in text
    assert "Yangi aʼzolar" in text
    assert len(text.splitlines()) >= 8


async def test_adm_backup_sends_document(
    test_db, fake_bot, monkeypatch, tmp_path, message_edits
):
    """Zaxira nusxa tugmasi fayl yuboradi."""
    monkeypatch.setattr(config, "BACKUP_DIR", str(tmp_path))
    admin_user = make_user(user_id=ADMIN_ID)
    await db.add_user(11_101, "x", "X")

    await adm_backup(make_callback(user=admin_user, data="adm_backup"), fake_bot)

    assert fake_bot.send_document.await_count == 1
    document_call = fake_bot.send_document.await_args
    assert document_call.args[0] == ADMIN_ID
    assert "Zaxira nusxa" in document_call.kwargs["caption"]


async def test_deal_status_updates_and_notifies_both_parties(
    test_db, fake_bot, callback_answer
):
    """Admin bitim holatini o'zgartiradi va ikkala tomon xabardor bo'ladi."""
    listing = await _make_sell_listing(user_id=USER_ID)
    deal_id = await db.create_deal(int(listing["id"]), USER_ID, 12_001, 1_500_000)
    admin_user = make_user(user_id=ADMIN_ID)

    await deal_status_cb(make_callback(user=admin_user, data=f"dstat_{deal_id}_garant"), fake_bot)

    assert (await db.get_deal(deal_id))["status"] == "garant"
    recipients = {call.args[0] for call in fake_bot.send_message.await_args_list}
    assert {USER_ID, 12_001} <= recipients


async def test_deal_status_rejects_unknown_deal(test_db, fake_bot, callback_answer):
    """Mavjud bo'lmagan bitim uchun ogohlantirish chiqadi."""
    admin_user = make_user(user_id=ADMIN_ID)

    await deal_status_cb(make_callback(user=admin_user, data="dstat_999_bogus"), fake_bot)

    assert callback_answer.await_args.kwargs.get("show_alert") is True


async def test_non_admin_cannot_use_analytics_or_backup(
    test_db, fake_bot, callback_answer, message_edits
):
    """Ruxsatsiz foydalanuvchi yangi admin tugmalarini ishlata olmaydi."""
    intruder = make_user(user_id=13_001)

    await adm_analytics(make_callback(user=intruder, data="adm_analytics"))
    await adm_backup(make_callback(user=intruder, data="adm_backup"), fake_bot)

    assert callback_answer.await_count == 2
    assert all(call.kwargs.get("show_alert") for call in callback_answer.await_args_list)
    assert message_edits.edit_text.await_count == 0
    assert fake_bot.send_document.await_count == 0


# ---------------------------------------------------------------------------
# 13. Fon vazifalari
# ---------------------------------------------------------------------------
async def test_expire_overdue_listings_marks_and_notifies(
    test_db, fake_bot, bot_username
):
    """Muddati o'tgan e'lon arxivlanadi, kanal yangilanadi va egasi xabardor bo'ladi."""
    with_channel = await _make_sell_listing(channel_msg_id=66)
    without = await _make_sell_listing()
    await db.conn.execute(
        "UPDATE listings SET expires_at = '2020-01-01T00:00:00+00:00' WHERE id IN (?, ?)",
        (int(with_channel["id"]), int(without["id"])),
    )
    await db.conn.commit()

    count = await expire_overdue_listings(fake_bot)

    assert count == 2
    assert (await db.get_listing(int(with_channel["id"])))["status"] == "expired"
    assert (await db.get_listing(int(without["id"])))["status"] == "expired"

    # Kanal xabari yangilandi (muddati tugagan banner bilan)
    edit_kwargs = fake_bot.edit_message_caption.await_args.kwargs
    assert edit_kwargs["message_id"] == 66
    assert "MUDDATI TUGADI" in edit_kwargs["caption"]

    renew_calls = [
        call
        for call in fake_bot.send_message.await_args_list
        if call.kwargs.get("reply_markup") is not None
    ]
    assert renew_calls
    assert f"renew_{with_channel['id']}" in _callbacks(renew_calls[0].kwargs["reply_markup"])


async def test_expire_overdue_listings_noop_when_nothing_expired(test_db, fake_bot):
    """Muddati o'tgan e'lon bo'lmasa hech narsa qilinmaydi."""
    await _make_sell_listing()
    assert await expire_overdue_listings(fake_bot) == 0


async def test_listing_expiry_task_runs_in_background(test_db, fake_bot, monkeypatch):
    """Fon sikli darhol tekshiradi va bekor qilinsa to'xtaydi."""
    listing = await _make_sell_listing()
    await db.conn.execute(
        "UPDATE listings SET expires_at = '2020-01-01T00:00:00+00:00' WHERE id = ?",
        (int(listing["id"]),),
    )
    await db.conn.commit()

    task = asyncio.ensure_future(listing_expiry_task(fake_bot))
    try:
        await asyncio.sleep(0.2)
        assert (await db.get_listing(int(listing["id"])))["status"] == "expired"
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert task.cancelled()


async def test_send_featured_post_uses_channel(test_db, fake_bot, bot_username):
    """Kunning tanlovi kanalga joylanadi va VIP e'lonni afzal ko'radi."""
    await _make_sell_listing(price=1_000_000)
    vip = await _make_sell_listing(price=2_000_000)
    await db.conn.execute("UPDATE listings SET is_vip = 1 WHERE id = ?", (int(vip["id"]),))
    await db.conn.commit()

    assert await send_featured_post(fake_bot) is True

    call = fake_bot.send_photo.await_args
    assert call.args[0] == config.DEFAULT_CHANNEL_ID
    assert "KUNNING TANLOVI" in call.kwargs["caption"]
    assert "2 000 000 soʻm" in call.kwargs["caption"]


async def test_send_featured_post_without_listings(test_db, fake_bot):
    """Aktiv e'lon bo'lmasa post yuborilmaydi."""
    assert await send_featured_post(fake_bot) is False
    assert fake_bot.send_photo.await_count == 0


async def test_run_backup_creates_and_prunes(test_db, monkeypatch, tmp_path):
    """Zaxira olinadi va eski nusxalar tozalanadi."""
    monkeypatch.setattr(config, "BACKUP_DIR", str(tmp_path))
    monkeypatch.setattr(config, "BACKUP_KEEP", 2)
    await db.add_user(14_001, "z", "Z")

    for index in range(3):
        stale = tmp_path / f"market_backup_2020-01-0{index + 1}_00-00-00.sqlite3"
        stale.write_text("eski", encoding="utf-8")

    created = await run_backup()

    assert created is not None and os.path.exists(created)
    remaining = sorted(p.name for p in tmp_path.glob("market_backup_*.sqlite3"))
    assert len(remaining) == 2
    assert os.path.basename(created) in remaining
