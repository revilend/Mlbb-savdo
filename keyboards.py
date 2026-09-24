"""Klaviaturalar va tugma matnlari.

Barcha tugma matnlari shu yerda doimiy qiymat sifatida saqlanadi —
shu tufayli handlerlardagi filtrlar bilan hech qachon mos kelmay qolmaydi.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

import config

# ---------------------------------------------------------------------------
# Reply tugmalar matni
# ---------------------------------------------------------------------------
BTN_SEARCH = "🔍 Akkaunt qidirish"
BTN_SELL = "💰 Akkaunt sotish"
BTN_RANDOM = "🎲 Tasodifiy akkaunt"
BTN_PRICE_FILTER = "💵 Narx boʻyicha saralash"
BTN_FAVORITES = "⭐️ Sevimlilarim"
BTN_CALC = "🧮 Narx kalkulyatori"
BTN_SCAM = "🛡️ Firibgarni tekshirish"
BTN_MY_LISTINGS = "📋 Mening eʼlonlarim"
BTN_GARANT = "🛡️ Garant xizmati"
BTN_STATS = "📊 Statistika"

BTN_CANCEL = "❌ Bekor qilish"
BTN_DONE = "✅ Tayyor"

MAIN_MENU_ROWS: list[list[str]] = [
    [BTN_SEARCH, BTN_SELL],
    [BTN_RANDOM, BTN_PRICE_FILTER],
    [BTN_FAVORITES, BTN_CALC],
    [BTN_SCAM, BTN_MY_LISTINGS],
    [BTN_GARANT, BTN_STATS],
]

ALL_MENU_BUTTONS: set[str] = {button for row in MAIN_MENU_ROWS for button in row}

RANKS: list[str] = [
    "Mythic Glory",
    "Mythic",
    "Legend",
    "Epic",
    "Grandmaster",
    "Master va undan past",
]


# ---------------------------------------------------------------------------
# Yordamchi funksiyalar
# ---------------------------------------------------------------------------
def contact_url(contact: str, fallback_username: str = "") -> str:
    """Aloqa ma'lumotidan bosiladigan havola yasaydi."""
    raw = (contact or "").strip()
    if raw.startswith(("http://", "https://", "tg://")):
        return raw

    clean = raw.lstrip("@").strip()
    if clean.isdigit():
        return f"tg://user?id={clean}"
    if re.fullmatch(r"[A-Za-z0-9_]{4,32}", clean or ""):
        return f"https://t.me/{clean}"

    username = (fallback_username or config.GARANT_USERNAME).lstrip("@").strip()
    return f"https://t.me/{username}"


# ---------------------------------------------------------------------------
# Reply klaviaturalar
# ---------------------------------------------------------------------------
def main_menu_kb() -> ReplyKeyboardMarkup:
    """Asosiy menyu."""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=text) for text in row] for row in MAIN_MENU_ROWS],
        resize_keyboard=True,
        input_field_placeholder="Kerakli boʻlimni tanlang…",
    )


def cancel_kb() -> ReplyKeyboardMarkup:
    """Faqat bekor qilish tugmasi."""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=BTN_CANCEL)]],
        resize_keyboard=True,
        input_field_placeholder="Bekor qilish uchun tugmani bosing",
    )


def photos_kb() -> ReplyKeyboardMarkup:
    """Rasmlar bosqichi uchun klaviatura."""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=BTN_DONE), KeyboardButton(text=BTN_CANCEL)]],
        resize_keyboard=True,
        input_field_placeholder="Rasm yuboring yoki tayyor tugmasini bosing",
    )


# ---------------------------------------------------------------------------
# Inline klaviaturalar
# ---------------------------------------------------------------------------
def subscribe_kb(channel_link: str = "") -> InlineKeyboardMarkup:
    """Majburiy a'zolik klaviaturasi."""
    rows: list[list[InlineKeyboardButton]] = []
    if channel_link:
        rows.append(
            [InlineKeyboardButton(text="➕ Kanalga aʼzo boʻlish", url=channel_link)]
        )
    rows.append(
        [InlineKeyboardButton(text="✅ Aʼzo boʻldim", callback_data="check_sub_cb")]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def listing_action_kb(listing: dict[str, Any]) -> InlineKeyboardMarkup:
    """Katalog va kanal uchun e'lon amallari klaviaturasi."""
    listing_id = listing["id"]
    listing_type = listing.get("listing_type", "sell")

    if listing_type == "buy":
        first_text = "🛡️ Admin orqali bogʻlanish"
        contact_text = "👤 Xaridor bilan aloqa"
    else:
        first_text = "🛡️ Admin orqali sotib olish"
        contact_text = "👤 Sotuvchi bilan aloqa"

    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text=first_text, callback_data=f"deal_{listing_id}")],
        [InlineKeyboardButton(text="💬 Narx taklif qilish", callback_data=f"offer_{listing_id}")],
        [
            InlineKeyboardButton(text="⭐️ Saqlab qoʻyish", callback_data=f"fav_{listing_id}"),
            InlineKeyboardButton(
                text=contact_text,
                url=contact_url(str(listing.get("contact") or "")),
            ),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def price_filter_kb() -> InlineKeyboardMarkup:
    """Narx bo'yicha saralash klaviaturasi."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🟢 100k gacha", callback_data="f_100"),
                InlineKeyboardButton(text="🟡 100k - 400k", callback_data="f_400"),
                InlineKeyboardButton(text="🔴 400k+", callback_data="f_max"),
            ]
        ]
    )


def my_listing_kb(listing_id: int) -> InlineKeyboardMarkup:
    """Mening e'lonlarim uchun amallar."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Sotildi deb belgilash", callback_data=f"sold_{listing_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔄 Eʼlonni koʻtarish (UP)", callback_data=f"bump_{listing_id}"
                )
            ],
        ]
    )


def moderation_kb(listing_id: int) -> InlineKeyboardMarkup:
    """Admin moderatsiyasi klaviaturasi."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Kanalga chiqarish", callback_data=f"app_{listing_id}"
                ),
                InlineKeyboardButton(text="❌ Rad etish", callback_data=f"rej_{listing_id}"),
            ]
        ]
    )


def admin_panel_kb() -> InlineKeyboardMarkup:
    """Admin panel klaviaturasi."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📢 Xabar tarqatish", callback_data="adm_broadcast"),
                InlineKeyboardButton(text="📊 Toʻliq statistika", callback_data="adm_stats"),
            ],
            [
                InlineKeyboardButton(text="⚙️ Majburiy kanal", callback_data="adm_sub_channel"),
                InlineKeyboardButton(text="👤 Foydalanuvchi qidirish", callback_data="adm_lookup"),
            ],
            [
                InlineKeyboardButton(text="🚫 Qora roʻyxatga kiritish", callback_data="adm_ban"),
                InlineKeyboardButton(text="📋 Qora roʻyxat", callback_data="adm_blacklist"),
            ],
        ]
    )


def rank_kb(prefix: str = "srank") -> InlineKeyboardMarkup:
    """Rank tanlash klaviaturasi."""
    rows = [
        [InlineKeyboardButton(text=rank, callback_data=f"{prefix}_{index}")]
        for index, rank in enumerate(RANKS)
    ]
    rows.append(
        [InlineKeyboardButton(text="✍️ Boshqa (oʻzim yozaman)", callback_data=f"{prefix}_custom")]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def vip_kb(prefix: str = "vip") -> InlineKeyboardMarkup:
    """VIP tanlash klaviaturasi."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="💎 Ha, VIP qilib qoʻying", callback_data=f"{prefix}_yes"),
                InlineKeyboardButton(text="🙂 Yoʻq", callback_data=f"{prefix}_no"),
            ]
        ]
    )


def search_type_kb() -> InlineKeyboardMarkup:
    """Xaridor so'rovi turini tanlash."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🛒 Sotib olaman", callback_data="stype_buy")],
            [InlineKeyboardButton(text="🔄 Almashtiraman", callback_data="stype_swap")],
        ]
    )


def single_button_kb(text: str, callback_data: str) -> InlineKeyboardMarkup:
    """Bitta inline tugma."""
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=text, callback_data=callback_data)]]
    )


def skip_kb(callback_data: str = "desc_skip", text: str = "⏭ Oʻtkazib yuborish") -> InlineKeyboardMarkup:
    """O'tkazib yuborish tugmasi."""
    return single_button_kb(text, callback_data)


def garant_kb() -> InlineKeyboardMarkup:
    """Garant xizmati klaviaturasi."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"🛡️ Garant: @{config.GARANT_USERNAME}",
                    url=config.GARANT_URL,
                )
            ]
        ]
    )


def deal_admin_kb(buyer_id: int, seller_id: int, username_buyer: Optional[str] = None,
                  username_seller: Optional[str] = None) -> InlineKeyboardMarkup:
    """Admin uchun: xaridor va sotuvchi bilan tez bog'lanish."""
    rows: list[list[InlineKeyboardButton]] = []

    buyer_username = (username_buyer or "").lstrip("@").strip()
    seller_username = (username_seller or "").lstrip("@").strip()

    buyer_button = (
        InlineKeyboardButton(text="💬 Xaridor", url=f"https://t.me/{buyer_username}")
        if buyer_username
        else InlineKeyboardButton(text="💬 Xaridor", url=f"tg://user?id={buyer_id}")
    )
    seller_button = (
        InlineKeyboardButton(text="💬 Sotuvchi", url=f"https://t.me/{seller_username}")
        if seller_username
        else InlineKeyboardButton(text="💬 Sotuvchi", url=f"tg://user?id={seller_id}")
    )
    rows.append([buyer_button, seller_button])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def dm_user_kb(user_id: int) -> InlineKeyboardMarkup:
    """Admin panelda foydalanuvchiga xabar yuborish tugmasi."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✉️ Xabar yuborish", callback_data=f"adm_dm_{user_id}")]
        ]
    )
