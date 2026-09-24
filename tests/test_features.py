"""Yangi funksiyalar uchun testlar.

Qamrov:
* Barter (almashish) rejimi — DB ustunlari, kartochka matni, anketaning to'liq oqimi.
* Narx tushirish — `old_price` saqlanadi, kanal tahrirlanadi, sevimlilarga xabar ketadi.
* Ulashish tugmasi va «❓ Qoʻllanma» menyusi.
* Admin panel — kanallar (e'lon/majburiy) va admin qo'shish/o'chirish.
* Kunlik hisobot — vaqt hisobi, matn formati va fon sikli.

Barcha testlar tarmoqqa murojaat qilmaydi.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
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
    add_admin,
    adm_post_channel,
    adm_required_channel,
    remove_admin,
    set_channel,
)
from handlers.common import GUIDE_TEXT, format_listing_caption, is_trade, show_guide
from handlers.my_listings import drop_price_apply, drop_price_start
from handlers.sell import (
    sell_contact,
    sell_description_skip,
    sell_finish,
    sell_mode_cb,
    sell_price,
    sell_rank_text,
    sell_skins,
    sell_trade_wanted,
    sell_vip,
    start_sell,
)
from keyboards import (
    BTN_GUIDE,
    MAIN_MENU_ROWS,
    listing_action_kb,
    my_listing_kb,
    share_url,
)
from main import daily_digest_task, seconds_until_digest, send_daily_digest
from middlewares import build_anti_flood
from states import AdminFSM, PriceDropFSM, SellFSM

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
    db.path = str(tmp_path / "features.sqlite3")

    await db.close()
    await db.connect()
    yield db
    await db.close()

    db.path = old_path
    db.admin_ids.clear()
    db.admin_ids.update(old_admins)


@pytest.fixture
def fsm() -> FSMContext:
    """Shaxsiy chat uchun FSM konteksti (MemoryStorage)."""
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
    """Tarmoqqa murojaat qilmaydigan bot (barcha chaqiruvlar yoziladi)."""
    bot = AsyncMock()
    bot.send_message = AsyncMock(return_value=SimpleNamespace(message_id=900))
    bot.send_photo = AsyncMock(return_value=SimpleNamespace(message_id=901))
    bot.send_media_group = AsyncMock(return_value=[SimpleNamespace(message_id=902)])
    bot.edit_message_caption = AsyncMock(return_value=True)
    bot.edit_message_text = AsyncMock(return_value=True)
    bot.delete_message = AsyncMock(return_value=True)
    bot.copy_message = AsyncMock(return_value=SimpleNamespace(message_id=903))
    bot.get_me = AsyncMock(return_value=SimpleNamespace(id=42, username=TEST_BOT_USERNAME))
    bot.get_chat = AsyncMock(
        return_value=SimpleNamespace(
            id=-100555,
            username="pytest_post_channel",
            title="Test kanal",
            invite_link=None,
        )
    )
    bot.get_chat_member = AsyncMock(return_value=SimpleNamespace(status="administrator"))
    return bot


@pytest.fixture
def bot_username(monkeypatch):
    """Share havolalari uchun bot username o'rnatadi."""
    old = keyboards.BOT_USERNAME
    keyboards.set_bot_username(TEST_BOT_USERNAME)
    yield TEST_BOT_USERNAME
    keyboards.set_bot_username(old)


@pytest.fixture(autouse=True)
def _block_message_edits(monkeypatch: pytest.MonkeyPatch):
    """Handlerlardagi `edit_*` chaqiruvlarini ham soxtalashtiradi."""
    edit_text = AsyncMock(return_value=True)
    edit_reply_markup = AsyncMock(return_value=True)
    edit_caption = AsyncMock(return_value=True)
    monkeypatch.setattr("aiogram.types.Message.edit_text", edit_text)
    monkeypatch.setattr("aiogram.types.Message.edit_reply_markup", edit_reply_markup)
    monkeypatch.setattr("aiogram.types.Message.edit_caption", edit_caption)


async def _make_sell_listing(
    *,
    user_id: int = USER_ID,
    price: int = 2_000_000,
    mode: str = "sell",
    status: str = "active",
    photos: list[str] | None = None,
) -> dict:
    """Test uchun e'lon yaratadi va qaytaradi."""
    listing_id = await db.create_listing(
        user_id=user_id,
        listing_type="sell",
        listing_mode=mode,
        trade_wanted="Ling Collector" if mode == "trade" else None,
        rank_info="Mythic Glory",
        skins_info="45 ta skin, 8 collector",
        price_numeric=None if mode == "trade" else price,
        price_display="" if mode == "trade" else f"{price:,} soʻm".replace(",", " "),
        contact="@seller",
        description="Test eʼlon",
        is_vip=0,
        photos=photos if photos is not None else ["AAA"],
        status=status,
    )
    listing = await db.get_listing(listing_id)
    assert listing is not None
    return listing


# ---------------------------------------------------------------------------
# 1. Bazaviy kengaytirmalar
# ---------------------------------------------------------------------------
async def test_new_columns_exist_and_are_migratable(test_db):
    """`listings` jadvalida yangi ustunlar mavjud (migratsiya idempotent)."""
    async with db.conn.execute("PRAGMA table_info(listings)") as cursor:
        columns = {row["name"] for row in await cursor.fetchall()}

    assert {"listing_mode", "trade_wanted", "old_price", "sold_at"} <= columns

    # Qayta ulanishda migratsiya xatolik bermaydi
    await db.close()
    await db.connect()
    async with db.conn.execute("PRAGMA table_info(listings)") as cursor:
        again = {row["name"] for row in await cursor.fetchall()}
    assert {"listing_mode", "trade_wanted", "old_price", "sold_at"} <= again


async def test_create_trade_listing_persists_mode(test_db):
    """Barter rejimi to'g'ri saqlanadi va `sell` dan ajratiladi."""
    trade = await _make_sell_listing(mode="trade")
    sell = await _make_sell_listing(mode="sell")

    assert trade["listing_mode"] == "trade"
    assert trade["trade_wanted"] == "Ling Collector"
    assert trade["price_numeric"] is None

    assert sell["listing_mode"] == "sell"
    assert sell["trade_wanted"] is None
    assert sell["price_numeric"] == 2_000_000


async def test_update_listing_price_keeps_old_price(test_db):
    """Narx tushirilganda eski narx `old_price` ga o'tadi."""
    listing = await _make_sell_listing(price=2_000_000)

    updated = await db.update_listing_price(int(listing["id"]), 1_500_000, "1 500 000 soʻm")

    assert updated is not None
    assert updated["price_numeric"] == 1_500_000
    assert updated["price_display"] == "1 500 000 soʻm"
    assert updated["old_price"] == "2 000 000 soʻm"

    # Ikkinchi marta tushirsak — `old_price` avvalgi (yuqori) narxni emas,
    # tushirishdan oldingi narxni saqlaydi
    await db.update_listing_price(int(listing["id"]), 1_000_000, "1 000 000 soʻm")
    again = await db.get_listing(int(listing["id"]))
    assert again["old_price"] == "1 500 000 soʻm"
    assert again["price_numeric"] == 1_000_000


async def test_update_listing_price_unknown_id_returns_none(test_db):
    assert await db.update_listing_price(99_999, 1, "1") is None


async def test_favorited_user_ids(test_db):
    """Sevimlilar ro'yxati e'lon bo'yicha to'g'ri qaytadi."""
    listing = await _make_sell_listing()

    assert await db.get_favorited_user_ids(int(listing["id"])) == []

    assert await db.add_favorite(111, int(listing["id"])) is True
    assert await db.add_favorite(222, int(listing["id"])) is True
    assert await db.add_favorite(111, int(listing["id"])) is False  # takror

    assert await db.get_favorited_user_ids(int(listing["id"])) == [111, 222]

    await db.remove_favorite(111, int(listing["id"]))
    assert await db.get_favorited_user_ids(int(listing["id"])) == [222]


async def test_today_stats_counts_created_items(test_db):
    """Bugungi ko'rsatkichlar yaratilgan ma'lumotlarni sanaydi."""
    new_users, new_listings, sold_before = await db.get_today_stats()
    assert (new_users, new_listings, sold_before) == (0, 0, 0)

    await db.add_user(301, "uzb", "O'zbek Foydalanuvchi")
    await db.add_user(302, "ikkinchi", "Ikkinchi")
    listing = await _make_sell_listing(user_id=301)

    users, listings, sold = await db.get_today_stats()
    assert users == 2
    assert listings == 1
    assert sold == 0

    await db.update_listing_status(int(listing["id"]), "sold")
    _, _, sold_after = await db.get_today_stats()
    assert sold_after == 1
    assert sold_after == sold + 1


async def test_update_listing_status_sets_sold_at(test_db):
    """Yopilgan e'londa `sold_at` paydo bo'ladi, qayta yopilsa o'zgarmaydi."""
    listing = await _make_sell_listing()

    await db.update_listing_status(int(listing["id"]), "active")
    assert (await db.get_listing(int(listing["id"])))["sold_at"] is None

    await db.update_listing_status(int(listing["id"]), "sold")
    first = (await db.get_listing(int(listing["id"])))["sold_at"]
    assert first

    await db.update_listing_status(int(listing["id"]), "sold")
    second = (await db.get_listing(int(listing["id"])))["sold_at"]
    assert second == first


# ---------------------------------------------------------------------------
# 2. Kanallar va adminlar
# ---------------------------------------------------------------------------
async def test_post_and_required_channels_are_separate(test_db):
    """E'lon kanali va majburiy kanal mustaqil saqlanadi."""
    await db.set_channel("post", "@posting", "https://t.me/posting")
    await db.set_channel("required", "-100123", "https://t.me/joinchat/x")

    assert await db.get_post_channel() == "@posting"
    assert await db.get_post_channel_link() == "https://t.me/posting"
    assert await db.get_required_channel() == "-100123"
    assert await db.get_required_channel_link() == "https://t.me/joinchat/x"


async def test_channel_falls_back_to_defaults(test_db):
    """Sozlanmagan kanal `.env` qiymatiga tushadi."""
    assert await db.get_post_channel() == config.DEFAULT_CHANNEL_ID
    assert await db.get_required_channel() == config.DEFAULT_CHANNEL_ID


async def test_admin_management(test_db):
    """Admin qo'shish/o'chirish bazada saqlanadi, asosiy admin himoyalangan."""
    await db.add_user(777, "newadmin", "Yangi Admin")
    assert db.is_admin(777) is False

    assert await db.add_admin(777) is True
    assert await db.add_admin(777) is False  # takror
    assert db.is_admin(777) is True
    assert 777 in db.get_admin_ids()

    # Bazadan qayta o'qilsa ham saqlanadi
    await db.refresh_admins()
    assert db.is_admin(777) is True

    # Asosiy adminni o'chirib bo'lmaydi
    assert await db.remove_admin(ADMIN_ID) is False
    assert db.is_admin(ADMIN_ID) is True

    # Oddiy adminni o'chirish mumkin
    assert await db.remove_admin(777) is True
    assert await db.remove_admin(777) is False
    assert db.is_admin(777) is False


# ---------------------------------------------------------------------------
# 3. Kartochka matni
# ---------------------------------------------------------------------------
async def test_trade_caption_header_and_demand(test_db):
    """Barter e'loni to'g'ri sarlavha va «Talab» qatorini ko'rsatadi."""
    listing = await _make_sell_listing(mode="trade")
    caption = format_listing_caption(listing)

    assert is_trade(listing) is True
    assert "AKKAUNT ALMASHISH (BARTER)" in caption
    assert "🎯 Talab: <b>Ling Collector</b>" in caption
    assert "💵 Narx" not in caption
    assert "#Almashish" in caption


async def test_sell_caption_header(test_db):
    listing = await _make_sell_listing(mode="sell")
    caption = format_listing_caption(listing)

    assert "AKKAUNT SOTILADI" in caption
    assert "💵 Narx: <b>2 000 000 soʻm</b>" in caption
    assert "NARX TUSHDI" not in caption


async def test_discount_caption_shows_old_and_new(test_db):
    """Narx tushganda e'lon matnida chegirma qatori paydo bo'ladi."""
    listing = await _make_sell_listing(price=2_000_000)
    await db.update_listing_price(int(listing["id"]), 1_500_000, "1 500 000 soʻm")
    updated = await db.get_listing(int(listing["id"]))

    caption = format_listing_caption(updated)
    assert "🔥 NARX TUSHDI: ~2 000 000 soʻm~ ➔ <b>1 500 000 soʻm</b>" in caption
    assert "💵 Narx" not in caption
    assert "👑" not in caption


async def test_closed_listing_shows_banner(test_db):
    listing = await _make_sell_listing()
    await db.update_listing_status(int(listing["id"]), "sold")
    updated = await db.get_listing(int(listing["id"]))

    assert "allaqachon yopilgan" in format_listing_caption(updated)


# ---------------------------------------------------------------------------
# 4. Klaviaturalar: ulashish va narx tushirish
# ---------------------------------------------------------------------------
async def test_share_button_present_on_every_listing(test_db, bot_username):
    listing = await _make_sell_listing()
    listing_id = int(listing["id"])

    action_rows = listing_action_kb(listing).inline_keyboard
    urls = [btn.url for row in action_rows for btn in row if btn.url]

    share = next((u for u in urls if "t.me/share/url" in u), None)
    assert share is not None
    assert f"view_{listing_id}" in share
    assert TEST_BOT_USERNAME in share
    assert "Mobile%20Legends%20akkaunt%20sotilmoqda" in share

    my_rows = my_listing_kb(listing).inline_keyboard
    my_urls = [btn.url for row in my_rows for btn in row if btn.url]
    assert any(f"view_{listing_id}" in u for u in my_urls)

    # share_url to'g'ri ishlaydi va boshqa e'lon uchun boshqacha
    other = share_url(listing_id + 1)
    assert f"view_{listing_id + 1}" in other


async def test_drop_price_button_only_for_active_sell_listing(test_db, bot_username):
    active_sell = await _make_sell_listing(status="active")
    trade = await _make_sell_listing(mode="trade")
    closed = await _make_sell_listing(status="sold")

    def callbacks(listing):
        return [
            btn.callback_data
            for row in my_listing_kb(listing).inline_keyboard
            for btn in row
            if btn.callback_data
        ]

    assert f"drop_price_{active_sell['id']}" in callbacks(active_sell)
    assert f"drop_price_{trade['id']}" not in callbacks(trade)
    assert not any(cb.startswith("drop_price_") for cb in callbacks(closed))


def test_main_menu_contains_guide_button():
    buttons = [btn for row in MAIN_MENU_ROWS for btn in row]
    assert BTN_GUIDE in buttons
    assert buttons.count(BTN_GUIDE) == 1


# ---------------------------------------------------------------------------
# 5. Kunlik hisobot
# ---------------------------------------------------------------------------
def test_seconds_until_digest_before_target():
    """Maqsaddan 1 daqiqa oldin ~60 soniya qoladi."""
    now = datetime(2026, 1, 1, 18, 58, 0, tzinfo=timezone.utc)  # UTC+5 → 23:58
    delay = seconds_until_digest(now)
    assert 55 <= delay <= 65


def test_seconds_until_digest_after_target_moves_to_next_day():
    """Maqsaddan keyin hisobot ertangi kunga ko'chadi."""
    now = datetime(2026, 1, 1, 19, 0, 0, tzinfo=timezone.utc)  # UTC+5 → 00:00
    delay = seconds_until_digest(now)
    assert delay > 86_000
    assert delay <= 86_400


async def test_send_daily_digest_format(test_db):
    """Hisobot matni spetsifikatsiyadagi ko'rinishda bo'ladi."""
    await db.add_user(401, "bugun", "Bugun")
    await _make_sell_listing(user_id=401)

    bot = AsyncMock()
    bot.send_message = AsyncMock(return_value=SimpleNamespace(message_id=1))

    await send_daily_digest(bot)

    assert bot.send_message.await_count == 1
    args, kwargs = bot.send_message.await_args
    assert args[0] == ADMIN_ID

    text = args[1]
    assert "📊 <b>KUNLIK HISOBOT:</b>" in text
    assert "━━━━━━━━━━━━━━━━━━━━" in text
    assert "👥 Bugungi yangi a'zolar: <b>+1</b>" in text
    assert "📝 Yangi eʼlonlar: <b>1</b>" in text
    assert "✅ Sotilgan akkauntlar: <b>0</b>" in text
    assert "Tizim 24/7 rejimida faol." in text


async def test_daily_digest_task_runs_in_background(test_db, monkeypatch):
    """Fon sikli uyg'onib, hisobot yuboradi va bekor qilinsa to'xtaydi."""
    monkeypatch.setattr("main.seconds_until_digest", lambda now=None: 0.05)

    bot = AsyncMock()
    bot.send_message = AsyncMock(return_value=SimpleNamespace(message_id=1))

    task = asyncio.ensure_future(daily_digest_task(bot))
    try:
        await asyncio.sleep(0.25)
        assert bot.send_message.await_count >= 1
        assert "KUNLIK HISOBOT" in bot.send_message.await_args.args[1]
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert task.cancelled()


# ---------------------------------------------------------------------------
# 6. Anti-flood: jonli admin to'plami
# ---------------------------------------------------------------------------
def test_live_bypass_set_is_dynamic(monkeypatch):
    """`db.admin_ids` ga qo'shilgan id darhol cheklovdan chiqadi."""
    monkeypatch.setattr(config, "FLOOD_PROTECTION", True)
    monkeypatch.setattr(config, "FLOOD_BYPASS_ADMIN", True)

    live: set[int] = set()
    middleware = build_anti_flood(live)
    assert middleware is not None
    assert middleware.live_bypass_user_ids is live

    live.add(99_999)
    assert 99_999 in middleware.live_bypass_user_ids


async def test_live_bypass_allows_event(monkeypatch):
    """Jonli to'plamdan foydalanuvchi hodisasi cheklanmaydi."""
    monkeypatch.setattr(config, "FLOOD_PROTECTION", True)
    monkeypatch.setattr(config, "FLOOD_BYPASS_ADMIN", True)
    monkeypatch.setattr(config, "FLOOD_MAX_EVENTS", 1)
    monkeypatch.setattr(config, "FLOOD_VIOLATION_LIMIT", 99)

    live: set[int] = set()
    middleware = build_anti_flood(live)
    assert middleware is not None

    handler = AsyncMock(return_value="handled")
    fresh_id = 77_777
    user = make_user(user_id=fresh_id)

    for index in range(20):
        result = await middleware(
            handler,
            make_message(user=user, message_id=index),
            {"event_from_user": user},
        )
        if index == 0:
            assert result == "handled"

    # Hozircha cheklov qo'llanadi
    assert handler.await_count == 1

    live.add(fresh_id)
    result = await middleware(
        handler, make_message(user=user, message_id=500), {"event_from_user": user}
    )
    assert result == "handled"
    assert handler.await_count == 2


# ---------------------------------------------------------------------------
# 7. Sotish anketasi: rejim tanlash va barter
# ---------------------------------------------------------------------------
async def test_sell_flow_starts_in_mode_state(fsm, message_answer):
    """Sotish anketasi avval rejimni (sotish/almashish) so'raydi."""
    await start_sell(make_message(text="💰 Akkaunt sotish"), fsm)
    assert await fsm.get_state() == SellFSM.mode
    data = await fsm.get_data()
    assert data["listing_mode"] == "sell"
    assert data["photos"] == []


async def test_sell_trade_flow_creates_barter_listing(test_db, fsm, fake_bot):
    """Barter anketasi narxni so'ramasdan yakunlanadi."""
    await start_sell(make_message(text="💰 Akkaunt sotish"), fsm)
    assert await fsm.get_state() == SellFSM.mode

    cb = make_callback(data="mode_trade")
    await sell_mode_cb(cb, fsm)
    assert await fsm.get_state() == SellFSM.rank
    data = await fsm.get_data()
    assert data["listing_mode"] == "trade"

    await sell_rank_text(make_message(text="Mythic Glory"), fsm)
    assert await fsm.get_state() == SellFSM.skins

    await sell_skins(make_message(text="45 ta skin, 8 collector"), fsm)
    # Narx so'ralmaydi — barter talabiga o'tamiz
    assert await fsm.get_state() == SellFSM.trade_wanted

    await sell_trade_wanted(make_message(text="Ling Collector yoki KOF boʻlsa alishaman"), fsm)
    assert await fsm.get_state() == SellFSM.is_vip

    await sell_vip(make_callback(data="vip_no"), fsm)
    assert await fsm.get_state() == SellFSM.contact

    await sell_contact(make_message(text="@seller"), fsm)
    assert await fsm.get_state() == SellFSM.description

    await sell_description_skip(make_callback(data="desc_skip"), fsm)
    assert await fsm.get_state() == SellFSM.photos

    await fsm.update_data(photos=["AAA", "BBB"])
    await sell_finish(make_message(text="✅ Tayyor"), fsm, fake_bot)

    assert await fsm.get_state() is None

    listings = await db.get_user_listings(USER_ID)
    assert len(listings) == 1

    listing = listings[0]
    assert listing["listing_mode"] == "trade"
    assert listing["trade_wanted"].startswith("Ling Collector")
    assert listing["price_numeric"] is None
    assert listing["status"] == "pending"

    caption = format_listing_caption(listing)
    assert "AKKAUNT ALMASHISH (BARTER)" in caption
    assert "🎯 Talab:" in caption

    # Eʼlon adminga moderatsiyaga yuborilgan (2 ta rasm → media-guruh)
    assert fake_bot.send_media_group.await_count >= 1


async def test_sell_price_flow_asks_price(test_db, fsm, fake_bot):
    """«💰 Sotish» rejimida narx so'ralsa, barter savoli chiqmaydi."""
    await start_sell(make_message(text="💰 Akkaunt sotish"), fsm)
    await sell_mode_cb(make_callback(data="mode_sell"), fsm)
    await sell_rank_text(make_message(text="Legend"), fsm)
    await sell_skins(make_message(text="12 ta skin"), fsm)

    assert await fsm.get_state() == SellFSM.price

    await sell_price(make_message(text="1.5mln"), fsm)
    data = await fsm.get_data()
    assert data["price_numeric"] == 1_500_000
    assert await fsm.get_state() == SellFSM.is_vip


async def test_trade_wanted_rejects_too_short(fsm, message_answer):
    await fsm.set_state(SellFSM.trade_wanted)
    await sell_trade_wanted(make_message(text="ab"), fsm)
    assert await fsm.get_state() == SellFSM.trade_wanted
    assert message_answer.await_count >= 1


# ---------------------------------------------------------------------------
# 8. Narx tushirish
# ---------------------------------------------------------------------------
async def test_drop_price_flow_updates_channel_and_favorites(
    test_db, fsm, fake_bot, message_answer, bot_username
):
    """Narx tushirilganda DB, kanal posti va sevimlilar yangilanadi."""
    listing = await _make_sell_listing(price=2_000_000, status="active")
    listing_id = int(listing["id"])
    await db.set_channel_message_id(listing_id, 55)

    await db.add_favorite(901, listing_id)
    await db.add_favorite(902, listing_id)

    await drop_price_start(make_callback(data=f"drop_price_{listing_id}"), fsm)
    assert await fsm.get_state() == PriceDropFSM.waiting_new_price
    prompt = message_answer.await_args.args[0]
    assert "2 000 000 soʻm" in prompt

    await drop_price_apply(make_message(text="1500000"), fsm, fake_bot)
    assert await fsm.get_state() is None

    updated = await db.get_listing(listing_id)
    assert updated["price_numeric"] == 1_500_000
    assert updated["old_price"] == "2 000 000 soʻm"

    # Kanal posti tahrirlandi va chegirma qatori bor
    assert fake_bot.edit_message_caption.await_count == 1
    edit_kwargs = fake_bot.edit_message_caption.await_args.kwargs
    assert edit_kwargs["message_id"] == 55
    assert "NARX TUSHDI" in edit_kwargs["caption"]
    assert "1 500 000 soʻm" in edit_kwargs["caption"]

    # Sevimlilarga xabar ketdi
    notified = {
        call.args[0] for call in fake_bot.send_message.await_args_list
    }
    assert {901, 902} <= notified
    favorites_text = next(
        call.args[1]
        for call in fake_bot.send_message.await_args_list
        if call.args[0] == 901
    )
    assert "Aksiyadorlik xabari" in favorites_text
    assert f"#{listing_id}" in favorites_text

    # Foydalanuvchiga yakuniy hisobot chiqdi
    summary = message_answer.await_args.args[0]
    assert "Narx yangilandi" in summary


async def test_drop_price_rejects_higher_price(test_db, fsm, message_answer, bot_username):
    """Yangi narx eskisidan katta bo'lsa qabul qilinmaydi."""
    listing = await _make_sell_listing(price=2_000_000, status="active")
    listing_id = int(listing["id"])

    await drop_price_start(make_callback(data=f"drop_price_{listing_id}"), fsm)
    await drop_price_apply(make_message(text="3000000"), fsm, AsyncMock())

    assert await fsm.get_state() == PriceDropFSM.waiting_new_price
    updated = await db.get_listing(listing_id)
    assert updated["price_numeric"] == 2_000_000
    assert updated["old_price"] is None
    assert message_answer.await_args.args[0].find("eskisidan past") != -1


async def test_drop_price_rejects_non_owner(test_db, fsm, callback_answer):
    listing = await _make_sell_listing(user_id=USER_ID, status="active")
    stranger = make_user(user_id=31_337, username="begona")
    cb = make_callback(user=stranger, data=f"drop_price_{listing['id']}")

    await drop_price_start(cb, fsm)

    assert await fsm.get_state() is None
    assert callback_answer.await_count == 1
    assert callback_answer.await_args.kwargs.get("show_alert") is True


async def test_drop_price_not_available_for_trade_listing(test_db, fsm, callback_answer):
    listing = await _make_sell_listing(mode="trade", status="active")
    cb = make_callback(data=f"drop_price_{listing['id']}")

    await drop_price_start(cb, fsm)

    assert await fsm.get_state() is None
    assert callback_answer.await_count == 1


# ---------------------------------------------------------------------------
# 9. Qoʻllanma
# ---------------------------------------------------------------------------
async def test_guide_button_sends_formatted_guide(message_answer):
    await show_guide(make_message(text=BTN_GUIDE))

    assert message_answer.await_count == 1
    text = message_answer.await_args.args[0]
    assert text == GUIDE_TEXT
    assert "Akkauntni xavfsiz sotib olish" in text
    assert "3-tomon tarmoqlarini uzish" in text
    assert "Garant xizmatidan foydalanish qoidalari" in text
    assert "narx tushirish" in text


# ---------------------------------------------------------------------------
# 10. Admin panel: kanallar va adminlar
# ---------------------------------------------------------------------------
async def test_admin_sets_post_and_required_channels(
    test_db, admin_fsm, fake_bot, message_answer
):
    """Har ikki kanal panel orqali alohida sozlanadi."""
    admin_user = make_user(user_id=ADMIN_ID, username="boss")

    await adm_post_channel(
        make_callback(user=admin_user, data="adm_post_channel"), admin_fsm
    )
    assert await admin_fsm.get_state() == AdminFSM.set_channel_input
    assert (await admin_fsm.get_data())["channel_kind"] == "post"

    await set_channel(make_message(user=admin_user, text="@pytest_post_channel"), admin_fsm, fake_bot)
    assert await admin_fsm.get_state() is None
    assert await db.get_post_channel() == "@pytest_post_channel"
    assert await db.get_required_channel() == config.DEFAULT_CHANNEL_ID  # o'zgarmadi

    await adm_required_channel(
        make_callback(user=admin_user, data="adm_sub_required"), admin_fsm
    )
    assert (await admin_fsm.get_data())["channel_kind"] == "required"

    fake_bot.get_chat = AsyncMock(
        return_value=SimpleNamespace(
            id=-100777, username=None, title="Majburiy kanal", invite_link=None
        )
    )
    await set_channel(make_message(user=admin_user, text="-100777"), admin_fsm, fake_bot)

    assert await db.get_required_channel() == "-100777"
    assert await db.get_post_channel() == "@pytest_post_channel"
    assert message_answer.await_count >= 2


async def test_channel_rejected_when_bot_is_not_admin(test_db, admin_fsm, fake_bot):
    """Bot administrator bo'lmasa kanal saqlanmaydi."""
    admin_user = make_user(user_id=ADMIN_ID)
    await adm_post_channel(
        make_callback(user=admin_user, data="adm_post_channel"), admin_fsm
    )

    fake_bot.get_chat_member = AsyncMock(return_value=SimpleNamespace(status="member"))
    await set_channel(make_message(user=admin_user, text="@nope"), admin_fsm, fake_bot)

    assert await admin_fsm.get_state() == AdminFSM.set_channel_input
    assert await db.get_post_channel() == config.DEFAULT_CHANNEL_ID


async def test_admin_add_and_remove_via_fsm(test_db, admin_fsm, fake_bot, message_answer):
    """Panel orqali admin qo'shish va o'chirish ishlaydi."""
    admin_user = make_user(user_id=ADMIN_ID)
    await db.add_user(777, "newadmin", "Yangi Admin")

    from handlers.admin import adm_add_admin

    await adm_add_admin(make_callback(user=admin_user, data="adm_add_admin"), admin_fsm)
    assert await admin_fsm.get_state() == AdminFSM.add_admin_id

    await add_admin(make_message(user=admin_user, text="777"), admin_fsm, fake_bot)
    assert await admin_fsm.get_state() is None
    assert db.is_admin(777) is True
    # Yangi adminga xabar ketgan
    assert any(
        call.args[0] == 777 for call in fake_bot.send_message.await_args_list
    )

    # O'chirish
    from handlers.admin import adm_remove_admin

    await adm_remove_admin(make_callback(user=admin_user, data="adm_remove_admin"), admin_fsm)
    assert await admin_fsm.get_state() == AdminFSM.remove_admin_id

    await remove_admin(make_message(user=admin_user, text="777"), admin_fsm)
    assert db.is_admin(777) is False

    # Asosiy adminni o'chirish urinishi rad etiladi
    await adm_remove_admin(make_callback(user=admin_user, data="adm_remove_admin"), admin_fsm)
    await remove_admin(make_message(user=admin_user, text=str(ADMIN_ID)), admin_fsm)
    assert db.is_admin(ADMIN_ID) is True


async def test_admin_add_rejects_unknown_user(test_db, admin_fsm, fake_bot, message_answer):
    """Boshilmagan foydalanuvchi admin qilib qo'shilmaydi."""
    admin_user = make_user(user_id=ADMIN_ID)
    await admin_fsm.set_state(AdminFSM.add_admin_id)

    await add_admin(make_message(user=admin_user, text="@topilmagan"), admin_fsm, fake_bot)

    assert db.is_admin(4_242) is False
    # State saqlanib qoladi — admin xato ID bilan qayta urina oladi
    assert await admin_fsm.get_state() == AdminFSM.add_admin_id
    assert message_answer.await_count >= 1
    assert "topilmadi" in message_answer.await_args.args[0]


async def test_non_admin_cannot_open_panel(message_answer, admin_fsm, callback_answer):
    """Ruxsatsiz foydalanuvchi admin tugmalarini ishlata olmaydi."""
    from handlers.admin import adm_admins, adm_stats

    intruder = make_user(user_id=31_337)

    await adm_admins(make_callback(user=intruder, data="adm_admins"), admin_fsm)
    await adm_stats(make_callback(user=intruder, data="adm_stats"))

    assert callback_answer.await_count == 2
    assert all(
        call.kwargs.get("show_alert") for call in callback_answer.await_args_list
    )
