"""Umumiy handlerlar va yordamchi funksiyalar.

Bu modul boshqa barcha handlerlar ishlatadigan yordamchilarni ham
saqlaydi (matn formatlash, e'lon kartochkasini yuborish/tahrirlash,
narxni tahlil qilish va h.k.).
"""

from __future__ import annotations

import html
import logging
import re
from typing import Any, Optional

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InputMediaPhoto, Message

import config
from database import db, parse_dt
from middlewares import messages as message_registry
from middlewares import permanent, sweep_chat, temporary
from keyboards import (
    admin_panel_kb,
    main_menu_kb,
    subscribe_kb,
    BTN_CANCEL,
    BTN_STATS,
)

logger = logging.getLogger(__name__)

router = Router(name="common")

# Bu router Dispatcher'ga ENG OXIRIDA ulanadi — shunda boshqa
# routerlardagi barcha handlerlar undan oldin ishlaydi.
fallback_router = Router(name="fallback")

PHOTO_CAPTION_LIMIT = 1024
TEXT_LIMIT = 4096

# ---------------------------------------------------------------------------
# Doimiy matnlar
# ---------------------------------------------------------------------------
WELCOME_TEXT = (
    "👋 Assalomu alaykum, <b>{name}</b>!\n\n"
    "🤖 <b>MLBB Market</b> — Mobile Legends akkauntlarini xavfsiz sotish va "
    "sotib olish uchun bot.\n\n"
    "Bu yerda siz:\n"
    "• 🔍 oʻzingizga mos akkauntni topishingiz\n"
    "• 💰 oʻz akkauntingizni sotasiz\n"
    "• 🧮 real narxni hisoblaysiz\n"
    "• 🛡️ firibgarlardan himoyalanasiz\n\n"
    "Kerakli boʻlimni menyudan tanlang 👇"
)

UNSUB_TEXT = (
    "🔒 <b>Botdan foydalanish uchun avval kanalga aʼzo boʻling!</b>\n\n"
    "📣 Kanal: <b>{channel}</b>\n\n"
    "Aʼzo boʻlgach, <b>«✅ Aʼzo boʻldim»</b> tugmasini bosing."
)

BANNED_TEXT = (
    "🚫 <b>Siz botdan foydalanishdan bloklangansiz.</b>\n\n"
    "Sababi boʻyicha administratorga murojaat qiling."
)

ADMIN_PANEL_TEXT = (
    "🛠️ <b>Administrator paneli</b>\n\n"
    "Kerakli amalni tanlang 👇"
)


# ---------------------------------------------------------------------------
# Yordamchi funksiyalar
# ---------------------------------------------------------------------------
def esc(value: Any) -> str:
    """Matnni HTML uchun xavfsiz holga keltiradi."""
    return html.escape(str(value if value is not None else ""), quote=False)


def user_label(user_id: int, username: Optional[str] = None, full_name: Optional[str] = None) -> str:
    """Foydalanuvchi uchun o'qishga qulay nom."""
    if username:
        return f"@{username}"
    if full_name:
        return full_name
    return f"ID: {user_id}"


def user_link(user_id: int, full_name: Optional[str] = None) -> str:
    """Telegram HTML havolasi ko'rinishidagi foydalanuvchi nomi."""
    name = esc(full_name) if full_name else f"ID {user_id}"
    return f'<a href="tg://user?id={user_id}">{name}</a>'


def format_price(value: Optional[int]) -> str:
    """Narxni chiroyli ko'rinishda chiqaradi."""
    if not value or value <= 0:
        return "Kelishilgan"
    return f"{int(value):,}".replace(",", " ") + " soʻm"


def parse_price(text: Optional[str]) -> Optional[int]:
    """Erkin matndan narxni ajratib oladi (500k, 1.5mln, 1 500 000 va h.k.)."""
    if not text:
        return None

    value = str(text).lower().strip()
    for junk in ("soʻm", "so'm", "so`m", "сум", "сўм", "sum", "руб", "rub", "$"):
        value = value.replace(junk, " ")
    value = value.replace("\u00a0", "").replace(" ", "").replace("_", "")

    multiplier = 1
    for suffix, mult in (
        ("million", 1_000_000),
        ("mln", 1_000_000),
        ("млн", 1_000_000),
        ("ming", 1_000),
        ("min", 1_000),
        ("к", 1_000),
        ("k", 1_000),
    ):
        if value.endswith(suffix) and len(value) > len(suffix):
            multiplier = mult
            value = value[: -len(suffix)]
            break

    if multiplier > 1:
        match = re.fullmatch(r"(\d+(?:[.,]\d+)?)", value)
        if match:
            number = float(match.group(1).replace(",", "."))
            return int(round(number * multiplier))

    digits = re.sub(r"\D", "", value)
    if not digits:
        return None

    number = int(digits)
    if multiplier > 1:
        number *= multiplier
    return number


def status_label(status: str) -> str:
    """E'lon holati uchun o'zbekcha yorliq."""
    return {
        "pending": "⏳ Moderatsiya kutilmoqda",
        "active": "🟢 Aktiv",
        "sold": "🔴 Sotilgan",
        "found": "✅ Topilgan",
        "rejected": "🚫 Rad etilgan",
    }.get(status or "", "❔ Nomaʼlum")


def _hashtag(text: str) -> str:
    """Matndan Telegram uchun to'g'ri hashtag yasaydi."""
    cleaned = re.sub(r"[^0-9A-Za-z_]+", "", text or "")
    return f"#{cleaned}" if cleaned else ""


def build_hashtags(listing: dict[str, Any]) -> str:
    """E'lon uchun avtomatik hashtaglar."""
    tags: list[str] = []
    if listing.get("is_vip"):
        tags.append("#VIP")
    if listing.get("listing_type") == "buy":
        tags.append("#Xaridor")
    else:
        tags.append("#Sotiladi")

    rank_tag = _hashtag(listing.get("rank_info") or "")
    if rank_tag:
        tags.append(rank_tag)

    numbers = re.findall(r"\d+", str(listing.get("skins_info") or ""))
    if numbers:
        tags.append(f"#{numbers[0]}kof")

    price = listing.get("price_numeric")
    if price:
        thousands = max(1, int(price) // 1000)
        tags.append(f"#{thousands}k")

    tags.append("#Mlbb")
    tags.append("#Savdo")
    return " ".join(tags)


def format_listing_caption(
    listing: dict[str, Any],
    header: Optional[str] = None,
    seller_label: Optional[str] = None,
) -> str:
    """E'lon kartochkasi matnini tayyorlaydi."""
    listing_type = listing.get("listing_type", "sell")
    is_buy = listing_type == "buy"

    lines: list[str] = []
    if header:
        lines.append(header)
        lines.append("")

    lines.append(f"🆔 Eʼlon raqami: <b>#{listing.get('id')}</b>")
    lines.append(f"📌 Turi: <b>{'🛒 Sotib olinadi' if is_buy else '💰 Sotiladi'}</b>")
    if listing.get("is_vip"):
        lines.append("💎 <b>VIP eʼlon</b>")
    lines.append(f"🏆 Rank: {esc(listing.get('rank_info') or '—')}")
    lines.append(f"🎭 Skinlar: {esc(listing.get('skins_info') or '—')}")
    lines.append(
        "💵 Narx: <b>{}</b>".format(
            esc(listing.get("price_display") or format_price(listing.get("price_numeric")))
        )
    )
    if listing.get("description"):
        lines.append(f"📝 Izoh: {esc(listing['description'])}")
    if seller_label:
        role = "Xaridor" if is_buy else "Sotuvchi"
        lines.append(f"👤 {role}: {esc(seller_label)}")
    if listing.get("contact"):
        lines.append(f"🔗 Aloqa: {esc(listing['contact'])}")

    if listing.get("status") in ("sold", "found"):
        lines.append("")
        lines.append("🚫 <b>Bu eʼlon allaqachon yopilgan.</b>")

    tags = build_hashtags(listing)
    if tags:
        lines.append("")
        lines.append(tags)

    return "\n".join(lines)


async def get_channel_id() -> str:
    """E'lonlar joylanadigan kanal ID si."""
    stored = await db.get_setting("required_channel")
    return (stored or config.DEFAULT_CHANNEL_ID or "").strip()


async def get_channel_link() -> str:
    """Majburiy kanal uchun havola."""
    stored = await db.get_setting("required_channel_link")
    if stored:
        return stored.strip()

    channel = await get_channel_id()
    if channel.startswith("@"):
        return f"https://t.me/{channel.lstrip('@')}"
    return ""


async def check_sub(bot: Bot, user_id: int) -> bool:
    """Foydalanuvchi majburiy kanalga a'zo ekanligini tekshiradi."""
    if user_id == config.ADMIN_ID:
        return True

    channel = await get_channel_id()
    if not channel:
        return True

    try:
        member = await bot.get_chat_member(chat_id=channel, user_id=user_id)
    except TelegramAPIError as exc:
        logger.warning("Aʼzolikni tekshirib boʻlmadi (%s): %s", channel, exc)
        return True

    status = str(getattr(member, "status", ""))
    if status in ("creator", "administrator", "member"):
        return True
    if status == "restricted":
        return bool(getattr(member, "is_member", True))
    return False


async def seller_label_of(listing: dict[str, Any]) -> str:
    """E'lon egasi uchun yorliq."""
    user = await db.get_user(int(listing["user_id"]))
    if user:
        return user_label(
            int(listing["user_id"]), user.get("username"), user.get("full_name")
        )
    return f"ID: {listing['user_id']}"


async def send_listing_card(
    bot: Bot,
    chat_id: int | str,
    listing: dict[str, Any],
    markup: Any = None,
    header: Optional[str] = None,
    seller_label: Optional[str] = None,
) -> Optional[Message]:
    """E'lonni rasm(lar) va izoh bilan yuboradi. Asosiy xabarni qaytaradi."""
    photos: list[str] = list(listing.get("photos") or [])
    caption = format_listing_caption(listing, header=header, seller_label=seller_label)

    if not photos:
        return await bot.send_message(
            chat_id,
            caption[:TEXT_LIMIT],
            reply_markup=markup,
            disable_web_page_preview=True,
        )

    photos = photos[: config.MAX_PHOTOS]
    caption = caption[:PHOTO_CAPTION_LIMIT]

    if len(photos) == 1:
        return await bot.send_photo(chat_id, photos[0], caption=caption, reply_markup=markup)

    media = [
        InputMediaPhoto(media=file_id, caption=caption if index == 0 else None)
        for index, file_id in enumerate(photos)
    ]
    messages = await bot.send_media_group(chat_id=chat_id, media=media)

    # Telegram media-guruhga inline tugma biriktirishga ruxsat bermaydi,
    # shu sababli tugmalar alohida xabar sifatida yuboriladi.
    if markup is not None:
        await bot.send_message(
            chat_id,
            "🛒 <b>Quyidagi tugmalar orqali amalni tanlang:</b>",
            reply_markup=markup,
        )
    return messages[0] if messages else None


async def edit_listing_card(
    bot: Bot,
    chat_id: int | str,
    message_id: int,
    listing: dict[str, Any],
    markup: Any = None,
    header: Optional[str] = None,
    seller_label: Optional[str] = None,
) -> bool:
    """Kanalga joylangan e'lon kartochkasini tahrirlaydi."""
    photos: list[str] = list(listing.get("photos") or [])
    text = format_listing_caption(listing, header=header, seller_label=seller_label)

    try:
        if photos:
            await bot.edit_message_caption(
                chat_id=chat_id,
                message_id=message_id,
                caption=text[:PHOTO_CAPTION_LIMIT],
                reply_markup=markup,
            )
        else:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text[:TEXT_LIMIT],
                reply_markup=markup,
                disable_web_page_preview=True,
            )
        return True
    except TelegramBadRequest as exc:
        logger.warning("Kartochkani tahrirlab boʻlmadi (#%s): %s", listing.get("id"), exc)
        return False
    except TelegramAPIError as exc:
        logger.warning("Kartochkani tahrirlashda xatolik (#%s): %s", listing.get("id"), exc)
        return False


async def notify_admin(bot: Bot, text: str, markup: Any = None) -> Optional[Message]:
    """Adminga xabar yuboradi (xatolikni yutadi)."""
    try:
        return await bot.send_message(
            config.ADMIN_ID,
            text[:TEXT_LIMIT],
            reply_markup=markup,
            disable_web_page_preview=True,
        )
    except TelegramAPIError as exc:
        logger.error("Adminga xabar yuborilmadi: %s", exc)
        return None


async def safe_delete(bot: Bot, chat_id: int | str, message_id: Optional[int]) -> None:
    """Xabarni o'chirishga urinadi (xatolikni yutadi)."""
    if not message_id:
        return
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except TelegramAPIError:
        pass


def is_bump_available(listing: dict[str, Any]) -> tuple[bool, str]:
    """E'lonni ko'tarish mumkinmi? (24 soatlik chegara)."""
    from datetime import datetime, timedelta, timezone

    last = parse_dt(listing.get("last_bumped")) or parse_dt(listing.get("created_at"))
    if last is None:
        return True, ""

    now = datetime.now(timezone.utc)
    cooldown = timedelta(hours=config.BUMP_COOLDOWN_HOURS)
    elapsed = now - last
    if elapsed >= cooldown:
        return True, ""

    remaining = cooldown - elapsed
    total_minutes = int(remaining.total_seconds() // 60)
    hours, minutes = divmod(total_minutes, 60)
    return False, f"{hours} soat {minutes} daqiqa"


def menu_button_guard(message: Message) -> bool:
    """Holat ichida menyu tugmasi bosilganini aniqlaydi."""
    from keyboards import ALL_MENU_BUTTONS

    return bool(message.text and message.text in ALL_MENU_BUTTONS)


# ---------------------------------------------------------------------------
# Handlerlar
# ---------------------------------------------------------------------------
@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, bot: Bot) -> None:
    """/start — foydalanuvchini ro'yxatga oladi va menyuni ko'rsatadi."""
    await state.clear()
    user = message.from_user
    if user is None:
        return

    await db.add_user(user.id, user.username, user.full_name)
    record = await db.get_user(user.id)

    if record and record.get("is_banned"):
        await message.answer(BANNED_TEXT)
        return

    if not await check_sub(bot, user.id):
        channel = await get_channel_id()
        channel_name = channel if channel.startswith("@") else "kanal"
        await message.answer(
            UNSUB_TEXT.format(channel=esc(channel_name)),
            reply_markup=subscribe_kb(await get_channel_link()),
        )
        return

    with permanent():
        await message.answer(
            WELCOME_TEXT.format(name=esc(user.full_name or user.first_name or "doʻstim")),
            reply_markup=main_menu_kb(),
        )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    """/help — yordam xabari."""
    with permanent():
        await message.answer(
            "ℹ️ <b>Yordam</b>\n\n"
            "• Eʼlon berish uchun «💰 Akkaunt sotish» boʻlimidan foydalaning.\n"
            "• Eʼloningiz moderator tekshiruvidan soʻng kanalga chiqadi.\n"
            "• Xarid qilishda xavfsizlik uchun «🛡️ Garant xizmati»dan foydalaning.\n"
            "• Savol boʻlsa administrator bilan bogʻlaning.\n\n"
            "Buyruqlar:\n"
            "/start — asosiy menyu\n"
            "/cancel — joriy amalni bekor qilish\n"
            "/clean — chatdagi xabarlarni tozalash",
            reply_markup=main_menu_kb(),
        )


@router.callback_query(F.data == "check_sub_cb")
async def cb_check_sub(callback: CallbackQuery, bot: Bot) -> None:
    """«A'zo bo'ldim» tugmasi."""
    user = callback.from_user
    if await check_sub(bot, user.id):
        await callback.answer("✅ Aʼzolik tasdiqlandi!")
        if isinstance(callback.message, Message):
            try:
                await callback.message.edit_text("✅ Aʼzolik tasdiqlandi. Rahmat!")
            except TelegramBadRequest:
                pass
            with permanent():
                await callback.message.answer(
                    WELCOME_TEXT.format(name=esc(user.full_name or "doʻstim")),
                    reply_markup=main_menu_kb(),
                )
        return

    await callback.answer(
        "❌ Siz hali kanalga aʼzo boʻlmadingiz. Aʼzo boʻlib, qaytadan urinib koʻring.",
        show_alert=True,
    )


@router.message(StateFilter("*"), F.text.in_([BTN_CANCEL, "/cancel"]))
async def cancel_any(message: Message, state: FSMContext) -> None:
    """Har qanday holatda amalni bekor qiladi."""
    current_state = await state.get_state()
    await state.clear()

    with temporary():
        if current_state is None:
            await message.answer(
                "ℹ️ Hozircha bekor qilinadigan amal yoʻq.", reply_markup=main_menu_kb()
            )
            return
        await message.answer("✅ Amal bekor qilindi.", reply_markup=main_menu_kb())


@router.message(Command("clean"))
async def cmd_clean(message: Message, bot: Bot) -> None:
    """/clean — chatdagi bot xabarlarini tozalaydi."""
    chat_id = message.chat.id

    if chat_id <= 0:
        await message.answer("ℹ️ Bu buyruq faqat shaxsiy chatda ishlaydi.")
        return

    if not config.SELF_DESTRUCT_ENABLED:
        await message.answer(
            "ℹ️ Chat tozalash xizmati oʻchirilgan.\n"
            "Administrator `.env` faylida <code>SELF_DESTRUCT_ENABLED=true</code> qilib yoqishi mumkin."
        )
        return

    tracked = message_registry.count(chat_id)
    deleted = await sweep_chat(bot, chat_id, message_registry)
    await safe_delete(bot, chat_id, message.message_id)

    with temporary(config.SELF_DESTRUCT_NOTICE_TTL):
        await message.answer(
            "🧹 <b>Chat tozalandi!</b>\n\n"
            f"🗑 Oʻchirilgan xabarlar: <b>{deleted}</b>"
            + (f" / {tracked}" if tracked else "")
            + "\n\nAsosiy menyu pastdagi tugmalarda qoladi 👇",
            reply_markup=main_menu_kb(),
        )


@router.message(StateFilter(None), F.text == BTN_STATS)
async def show_stats(message: Message) -> None:
    """Umumiy statistika."""
    total_users, active_listings, sold_listings = await db.get_stats()
    await message.answer(
        "📊 <b>Bot statistikasi</b>\n\n"
        f"👥 Foydalanuvchilar: <b>{total_users}</b>\n"
        f"🟢 Aktiv eʼlonlar: <b>{active_listings}</b>\n"
        f"🤝 Sotilgan akkauntlar: <b>{sold_listings}</b>",
        reply_markup=main_menu_kb(),
    )


@router.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext) -> None:
    """/admin — admin panelni ochadi."""
    user = message.from_user
    if user is None or user.id != config.ADMIN_ID:
        await message.answer("⛔️ Bu buyruq faqat administrator uchun.")
        return

    await state.clear()
    with permanent():
        await message.answer(ADMIN_PANEL_TEXT, reply_markup=admin_panel_kb())


@fallback_router.message(StateFilter(None))
async def fallback(message: Message) -> None:
    """Tushunarsiz xabarlar uchun yumshoq javob."""
    if not message.text:
        await message.answer("🤔 Bu turdagi xabarni tushunmadim.", reply_markup=main_menu_kb())
        return
    await message.answer(
        "🤔 Kechirasiz, bu buyruqni tushunmadim.\n\n"
        "Iltimos, menyudagi tugmalardan foydalaning 👇",
        reply_markup=main_menu_kb(),
    )
