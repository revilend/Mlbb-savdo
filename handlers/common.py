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
from settings import settings
from states import ScamCheckFSM
from keyboards import (
    BTN_CANCEL,
    BTN_GUIDE,
    BTN_REFERRAL,
    BTN_STATS,
    admin_panel_kb,
    guide_kb,
    listing_action_kb,
    main_menu_kb,
    referral_kb,
    referral_link,
    subscribe_kb,
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
    "• 🔍 akkauntingizni admin yordamida baholaysiz\n"
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

GUIDE_TEXT = (
    "❓ <b>QOʻLLANMA — xavfsiz savdo qoidalari</b>\n"
    "━━━━━━━━━━━━━━━━━━━━\n\n"
    "<b>1️⃣ Akkauntni xavfsiz sotib olish va topshirish</b>\n"
    "Moonton akkaunti <b>email</b> ga bogʻlangan, shu sababli topshirish tartibi:\n"
    "• Sotuvchi xaridorga akkauntning <b>email</b> va parolini beradi;\n"
    "• Xaridor darhol Moonton saytida (yoki oʻyinda) <b>parolni</b> va "
    "<b>email</b> ni oʻziga oʻzgartiradi;\n"
    "• <b>Barcha 3-tomon tarmoqlarini uzish</b>: Google, Facebook, TikTok/Discord va "
    "boshqa bogʻlanishlarni «Account Settings → Linked accounts» boʻlimidan "
    "uzib chiqing;\n"
    "• Emailga keladigan tasdiqlash kodlari xaridorga oʻtishi shart;\n"
    "• Akkauntni <b>faqat bitta qurilmada</b> sinab koʻring va 24 soat "
    "kuzatib turing — bu vaqt ichida egasi tiklab olishga urinishi mumkin.\n\n"
    "<b>2️⃣ Garant xizmatidan foydalanish qoidalari</b>\n"
    "• Kelishuv puli avval <b>garant</b>ga (vositachi) topshiriladi;\n"
    "• Garant pulni olgach, sotuvchi akkauntni topshiradi;\n"
    "• Xaridor akkauntni tekshirib tasdiqlagach, garant pulni sotuvchiga beradi;\n"
    "• Nizo boʻlsa, garant yozishmalar va dalillar asosida qaror qabul qiladi;\n"
    "• Garantsiz oldindan toʻlov qilish — eng koʻp uchraydigan firibgarlik sababi.\n\n"
    "<b>3️⃣ Botda eʼlon berish va narx tushirish</b>\n"
    "• «💰 Akkaunt sotish» → <b>Sotish</b> yoki <b>Almashish (Barter)</b> rejimini tanlang;\n"
    "• Anketani toʻldiring: rank → skinlar → narx → VIP → aloqa → izoh → rasmlar;\n"
    "• Moderator tasdiqlagach eʼlon kanalga chiqadi;\n"
    "• «📋 Mening eʼlonlarim» boʻlimida narxni <b>tushirishingiz</b> mumkin — "
    "eski narx ustidan chizilib, yangisi ajratib koʻrsatiladi va eʼlonni "
    "sevimlilarga saqlaganlarga darhol xabar boradi;\n"
    "• Eʼlonni <b>24 soatda bir marta</b> koʻtarish (UP) mumkin;\n"
    "• <b>✏️ Tahrirlash</b> orqali narx/izoh/aloqani oʻzgartirishingiz mumkin;\n"
    "• Eʼlon <b>14 kun</b> amal qiladi, muddati tugasa «🔄 Yangilash» tugmasi chiqadi;\n"
    "• Sotilgach «✅ Sotildi deb belgilash» tugmasini bosishni unutmang.\n\n"
    "<b>4️⃣ Takliflar, reyting va obunalar</b>\n"
    "• «📥 Takliflar va bitimlar» — kelgan/ketgan takliflarni qabul qilish yoki "
    "rad etish va bitim holatini kuzatish;\n"
    "• Bitimni faqat <b>garant</b> orqali yakunlang — holat oʻzgarishini ikkala "
    "tomon ham koʻradi;\n"
    "• Bitimdan keyin eʼlon kartochkasidagi «⭐️ Sharh qoldirish» tugmasi orqali "
    "sotuvchiga 1–5 baho bering — reyting boshqa xaridorlarga yordam beradi;\n"
    "• «🔔 Qidiruv obunasi» — kerakli narx/rank boʻyicha yangi eʼlon chiqsa, "
    "bot sizga oʻzi xabar beradi;\n"
    "• «🎁 Referal» — doʻstlarni taklif qilib bepul VIP eʼlon oling.\n\n"
    "━━━━━━━━━━━━━━━━━━━━\n"
    "🛡️ Shubhali foydalanuvchini «🛡️ Firibgarni tekshirish» boʻlimida tekshiring."
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


def is_admin(user_id: Optional[int]) -> bool:
    """Foydalanuvchi administrator ekanmi (bot ichida qo'shilganlar ham)."""
    return db.is_admin(user_id)


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
        "expired": "⌛️ Muddati tugagan",
    }.get(status or "", "❔ Nomaʼlum")


def stars(score: float) -> str:
    """O'rtacha bahoni yulduzchalarga aylantiradi (masalan 4.3 → ★★★★☆)."""
    rounded = max(0, min(5, int(round(float(score or 0)))))
    return "★" * rounded + "☆" * (5 - rounded)


def format_rating(score: float, count: int) -> str:
    """Reytingni matn ko'rinishida chiqaradi."""
    if not count:
        return "yangi sotuvchi"
    return f"{float(score):.1f} {stars(score)} ({count} ta sharh)"


def format_expiry(listing: dict[str, Any]) -> str:
    """E'lonning amal muddati (mahalliy vaqtda, KK.OO)."""
    expires = parse_dt(listing.get("expires_at"))
    if expires is None:
        return ""
    local = expires.astimezone(_tz_offset(int(settings.get("TZ_OFFSET_HOURS"))))
    return local.strftime("%d.%m.%Y")


def _tz_offset(hours: int):
    """Soat siljishi uchun timezone obyekti."""
    from datetime import timedelta, timezone as _timezone

    return _timezone(timedelta(hours=int(hours)))


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
    elif is_trade(listing):
        tags.append("#Almashish")
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


def default_header(listing: dict[str, Any]) -> str:
    """E'lon turiga mos sarlavha."""
    if listing.get("listing_type") == "buy":
        return "🛒 <b>AKKAUNT SOTIB OLINADI</b>"
    if is_trade(listing):
        return "🔄 <b>AKKAUNT ALMASHISH (BARTER)</b>"
    return "💰 <b>AKKAUNT SOTILADI</b>"


def is_trade(listing: dict[str, Any]) -> bool:
    """E'lon barter (almashish) rejimidami?"""
    return str(listing.get("listing_mode") or "sell").lower() == "trade"


def format_listing_caption(
    listing: dict[str, Any],
    header: Optional[str] = None,
    seller_label: Optional[str] = None,
    seller_rating: Optional[tuple[float, int]] = None,
) -> str:
    """E'lon kartochkasi matnini tayyorlaydi.

    :param seller_rating: `(o'rtacha baho, sharhlar soni)` — berilmasa
        reyting qatori ko'rsatilmaydi.
    """
    listing_type = listing.get("listing_type", "sell")
    is_buy = listing_type == "buy"
    trade = is_trade(listing)

    lines: list[str] = []
    lines.append(header or default_header(listing))
    lines.append("")

    lines.append(f"🆔 Eʼlon raqami: <b>#{listing.get('id')}</b>")
    if not trade:
        lines.append(f"📌 Turi: <b>{'🛒 Sotib olinadi' if is_buy else '💰 Sotiladi'}</b>")
    if listing.get("is_vip"):
        lines.append("💎 <b>VIP eʼlon</b>")
    lines.append(f"🏆 Rank: {esc(listing.get('rank_info') or '—')}")
    lines.append(f"🎭 Skinlar: {esc(listing.get('skins_info') or '—')}")

    new_price = esc(
        listing.get("price_display") or format_price(listing.get("price_numeric"))
    )
    if trade:
        lines.append(f"🎯 Talab: <b>{esc(listing.get('trade_wanted') or 'Kelishiladi')}</b>")
    elif listing.get("old_price"):
        # Narx tushirilganda eski narx ustidan chizilib, yangisi ajratiladi
        lines.append(f"🔥 NARX TUSHDI: ~{esc(listing.get('old_price'))}~ ➔ <b>{new_price}</b>")
    else:
        lines.append(f"💵 Narx: <b>{new_price}</b>")

    if listing.get("description"):
        lines.append(f"📝 Izoh: {esc(listing['description'])}")
    if seller_label:
        if is_buy:
            role = "Xaridor"
        elif trade:
            role = "Egasi"
        else:
            role = "Sotuvchi"
        lines.append(f"👤 {role}: {esc(seller_label)}")
    if seller_rating is not None and not is_buy:
        score, count = seller_rating
        if count:
            lines.append(f"⭐️ Reyting: <b>{esc(format_rating(score, count))}</b>")
        else:
            lines.append("⭐️ Reyting: yangi sotuvchi")
    if listing.get("contact"):
        lines.append(f"🔗 Aloqa: {esc(listing['contact'])}")

    expires_text = format_expiry(listing)
    if expires_text and listing.get("status") in ("active", "expired"):
        lines.append(f"⏳ Amal muddati: <b>{esc(expires_text)}</b> gacha")

    if listing.get("status") in ("sold", "found"):
        lines.append("")
        lines.append("🚫 <b>Bu eʼlon allaqachon yopilgan.</b>")
    elif listing.get("status") == "expired":
        lines.append("")
        lines.append("⌛️ <b>Bu eʼlonning amal muddati tugagan.</b>")

    tags = build_hashtags(listing)
    if tags:
        lines.append("")
        lines.append(tags)

    return "\n".join(lines)


async def get_channel_id() -> str:
    """E'lonlar joylanadigan kanal (admin panelda sozlanadi)."""
    return await db.get_post_channel()


async def get_channel_link() -> str:
    """E'lon kanali uchun havola."""
    return await db.get_post_channel_link()


async def get_required_channel() -> str:
    """Majburiy a'zolik kanali."""
    return await db.get_required_channel()


async def get_required_channel_link() -> str:
    """Majburiy kanal uchun havola."""
    return await db.get_required_channel_link()


async def check_sub(bot: Bot, user_id: int) -> bool:
    """Foydalanuvchi majburiy kanalga a'zo ekanligini tekshiradi."""
    if db.is_admin(user_id):
        return True

    channel = await get_required_channel()
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


#: Sotuvchi tasdiqlanganligini belgilovchi nishon
VERIFIED_BADGE = "✅"


async def seller_label_of(listing: dict[str, Any]) -> str:
    """E'lon egasi uchun yorliq (tasdiqlangan bo'lsa `✅` belgisi bilan)."""
    user = await db.get_user(int(listing["user_id"]))
    if user:
        label = user_label(
            int(listing["user_id"]), user.get("username"), user.get("full_name")
        )
        return f"{VERIFIED_BADGE} {label}" if user.get("is_verified") else label
    return f"ID: {listing['user_id']}"


async def seller_card_rating(listing: dict[str, Any]) -> Optional[tuple[float, int]]:
    """E'lon egasining reytingi (kartochkada ko'rsatish uchun)."""
    if listing.get("listing_type") == "buy":
        return None
    return await db.get_seller_rating(int(listing["user_id"]))


def start_payload(message: Message) -> str:
    """/start buyrug'idan keyingi parametrni qaytaradi (masalan `ref_123`)."""
    parts = (message.text or "").split(maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else ""


async def blacklist_warning(
    user_id: int,
    username: Optional[str] = None,
    contact: str = "",
) -> Optional[str]:
    """Foydalanuvchi/aloqa qora ro'yxatda bo'lsa ogohlantirish matnini qaytaradi."""
    candidates = [str(user_id)]
    if username:
        candidates.append(str(username))
    clean = db.normalize_identifier(contact or "")
    if clean:
        candidates.append(clean)

    for candidate in candidates:
        if not candidate:
            continue
        record = await db.is_blacklisted(candidate)
        if record is not None:
            return (
                "⚠️ <b>Diqqat — qora roʻyxat!</b>\n\n"
                f"🔎 Topilgan moslik: <code>{esc(candidate)}</code>\n"
                f"📝 Sabab: {esc(record.get('reason') or 'koʻrsatilmagan')}"
            )
    return None


async def send_listing_card(
    bot: Bot,
    chat_id: int | str,
    listing: dict[str, Any],
    markup: Any = None,
    header: Optional[str] = None,
    seller_label: Optional[str] = None,
    seller_rating: Optional[tuple[float, int]] = None,
) -> Optional[Message]:
    """E'lonni rasm(lar) va izoh bilan yuboradi. Asosiy xabarni qaytaradi."""
    photos: list[str] = list(listing.get("photos") or [])
    caption = format_listing_caption(
        listing, header=header, seller_label=seller_label, seller_rating=seller_rating
    )

    if not photos:
        return await bot.send_message(
            chat_id,
            caption[:TEXT_LIMIT],
            reply_markup=markup,
            disable_web_page_preview=True,
        )

    photos = photos[: int(settings.get("MAX_PHOTOS"))]
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
    seller_rating: Optional[tuple[float, int]] = None,
) -> bool:
    """Kanalga joylangan e'lon kartochkasini tahrirlaydi."""
    photos: list[str] = list(listing.get("photos") or [])
    text = format_listing_caption(
        listing, header=header, seller_label=seller_label, seller_rating=seller_rating
    )

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
    """Barcha adminlarga xabar yuboradi (xatoliklarni yutadi)."""
    first: Optional[Message] = None
    for admin_id in db.get_admin_ids():
        try:
            message = await bot.send_message(
                admin_id,
                text[:TEXT_LIMIT],
                reply_markup=markup,
                disable_web_page_preview=True,
            )
            if first is None:
                first = message
        except TelegramAPIError as exc:
            logger.error("Adminga (%s) xabar yuborilmadi: %s", admin_id, exc)
    return first


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
    cooldown = timedelta(hours=int(settings.get("BUMP_COOLDOWN_HOURS")))
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
    """/start — foydalanuvchini ro'yxatga oladi va menyuni ko'rsatadi.

    `?start=view_{id}` ko'rinishidagi havola (ulashish tugmasi) bosilsa,
    foydalanuvchiga o'sha e'lon ko'rsatiladi.
    """
    await state.clear()
    user = message.from_user
    if user is None:
        return

    is_new = await db.add_user(user.id, user.username, user.full_name)
    record = await db.get_user(user.id)

    if record and record.get("is_banned"):
        await message.answer(BANNED_TEXT)
        return

    if not await check_sub(bot, user.id):
        channel = await get_required_channel()
        channel_name = channel if channel.startswith("@") else "kanal"
        await message.answer(
            UNSUB_TEXT.format(channel=esc(channel_name)),
            reply_markup=subscribe_kb(await get_required_channel_link()),
        )
        return

    payload = start_payload(message)
    if payload == "garant":
        from handlers.garant import GARANT_TEXT
        from keyboards import garant_kb

        with permanent():
            await message.answer(
                GARANT_TEXT,
                reply_markup=garant_kb(),
                disable_web_page_preview=True,
            )
        return
    if payload == "scam":
        from handlers.scam_check import ASK_TEXT
        from keyboards import cancel_kb

        await state.set_state(ScamCheckFSM.waiting_query)
        await message.answer(ASK_TEXT, reply_markup=cancel_kb())
        return

    with permanent():
        await message.answer(
            WELCOME_TEXT.format(name=esc(user.full_name or user.first_name or "doʻstim")),
            reply_markup=main_menu_kb(),
        )

    await handle_referral_start(message, bot, is_new)
    await send_shared_listing(message, bot)


async def handle_referral_start(message: Message, bot: Bot, is_new: bool) -> None:
    """/start ref_{id} havolasi orqali kelgan foydalanuvchini qayd etadi."""
    user = message.from_user
    if user is None:
        return

    payload = start_payload(message)
    if not payload.startswith("ref_"):
        return

    raw_id = payload.split("_", 1)[-1]
    if not raw_id.isdigit():
        return

    referrer_id = int(raw_id)
    if referrer_id == user.id:
        return

    # Taklif qiluvchi haqiqiy foydalanuvchi bo'lishi shart
    if await db.get_user(referrer_id) is None:
        return

    if not await db.set_referrer(user.id, referrer_id):
        return

    reward = int(settings.get("REFERRAL_REWARD_VIP"))
    if reward > 0 and is_new:
        await db.add_free_vip(referrer_id, reward)

    total = await db.count_referrals(referrer_id)
    nickname = esc(user.full_name or user.first_name or "Yangi doʻst")
    reward_line = (
        f"\n🎁 Sizga <b>{reward}</b> ta bepul VIP eʼlon qoʻshildi!"
        if reward > 0 and is_new
        else ""
    )
    try:
        await bot.send_message(
            referrer_id,
            "🎉 <b>Yangi doʻstingiz qoʻshildi!</b>\n\n"
            f"👤 {nickname} sizning havolangiz orqali botga kirdi.\n"
            f"📈 Jami taklif qilganlaringiz: <b>{total}</b>"
            f"{reward_line}",
            disable_web_page_preview=True,
        )
    except TelegramAPIError as exc:
        logger.warning("Referal xabari yuborilmadi (user=%s): %s", referrer_id, exc)


async def send_shared_listing(message: Message, bot: Bot) -> None:
    """Ulashilgan havola (`/start view_{id}`) orqali kelgan e'lonni ko'rsatadi."""
    command_args = (message.text or "").split(maxsplit=1)
    payload = command_args[1].strip() if len(command_args) > 1 else ""
    if not payload.startswith("view_"):
        return

    raw_id = payload.split("_", 1)[-1]
    if not raw_id.isdigit():
        return

    listing = await db.get_listing(int(raw_id))
    if listing is None or listing.get("status") not in ("active", "sold", "found"):
        await message.answer(
            "😔 Afsuski, bu eʼlon topilmadi yoki allaqachon olib tashlangan.\n\n"
            "«🎲 Tasodifiy akkaunt» boʻlimida boshqa eʼlonlarni koʻrishingiz mumkin.",
            reply_markup=main_menu_kb(),
        )
        return

    markup = listing_action_kb(listing) if listing.get("status") == "active" else None
    try:
        await send_listing_card(
            bot,
            message.chat.id,
            listing,
            markup=markup,
            seller_label=await seller_label_of(listing),
            seller_rating=await seller_card_rating(listing),
        )
    except TelegramAPIError as exc:
        logger.warning("Ulashilgan eʼlon #%s yuborilmadi: %s", raw_id, exc)


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
            "Yangi boʻlimlar:\n"
            "📥 Takliflar va bitimlar — kelgan takliflarga javob berish\n"
            "🔔 Qidiruv obunasi — mos eʼlon chiqsa xabar beradi\n"
            "🎁 Referal — doʻstlarni taklif qilib VIP olish\n\n"
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


@router.message(StateFilter(None), F.text == BTN_GUIDE)
async def show_guide(message: Message) -> None:
    """«❓ Qoʻllanma» — xavfsiz savdo qo'llanmasi."""
    with permanent():
        await message.answer(
            GUIDE_TEXT,
            reply_markup=guide_kb(),
            disable_web_page_preview=True,
        )


@router.message(StateFilter(None), F.text == BTN_REFERRAL)
async def show_referral(message: Message) -> None:
    """«🎁 Referal» — taklif havolasi va bonuslar."""
    user = message.from_user
    if user is None:
        return

    count = await db.count_referrals(user.id)
    credits = await db.get_free_vip(user.id)
    link = referral_link(user.id) or "havola mavjud emas"

    text = (
        "🎁 <b>Referal dasturi</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "Doʻstlaringizni botga taklif qiling va <b>bepul VIP eʼlon</b> oling!\n\n"
        f"🔗 Sizning havolangiz:\n<code>{esc(link)}</code>\n\n"
        f"👥 Siz taklif qilgan doʻstlar: <b>{count}</b>\n"
        f"💎 Bepul VIP eʼlonlar: <b>{credits}</b>\n"
        f"🎯 Har bir yangi doʻst uchun: <b>+{settings.get('REFERRAL_REWARD_VIP')} VIP</b>\n\n"
        "ℹ️ VIP eʼlon roʻyxatda yuqorida turadi. Kredit keyingi eʼlon "
        "joylashtirishda avtomatik taklif qilinadi."
    )

    with permanent():
        await message.answer(
            text, reply_markup=referral_kb(user.id), disable_web_page_preview=True
        )


@router.message(Command("guide"))
async def cmd_guide(message: Message) -> None:
    """/guide — qo'llanmani ko'rsatadi."""
    with permanent():
        await message.answer(GUIDE_TEXT, reply_markup=guide_kb(), disable_web_page_preview=True)


@router.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext) -> None:
    """/admin — admin panelni ochadi."""
    user = message.from_user
    if user is None or not is_admin(user.id):
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
