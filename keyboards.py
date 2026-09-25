"""Klaviaturalar va tugma matnlari.

Barcha tugma matnlari shu yerda doimiy qiymat sifatida saqlanadi —
shu tufayli handlerlardagi filtrlar bilan hech qachon mos kelmay qolmaydi.
"""

from __future__ import annotations

import re
from typing import Any, Optional
from urllib.parse import quote

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

import config
from settings import GROUPS, Setting, settings

# ---------------------------------------------------------------------------
# Bot username'i
# ---------------------------------------------------------------------------
#: `main.py` ishga tushganda `bot.get_me()` natijasi bilan to'ldiriladi.
#: Ulashish (share) havolalari shu qiymatga tayanadi.
BOT_USERNAME: str = config.BOT_USERNAME


def set_bot_username(username: Optional[str]) -> None:
    """Botning username ini o'rnatadi (ishga tushishda chaqiriladi)."""
    global BOT_USERNAME
    BOT_USERNAME = (username or "").lstrip("@").strip()


def bot_deep_link(payload: str) -> str:
    """Bot uchun deep-link yasaydi (`?start=payload`)."""
    if not BOT_USERNAME:
        return ""
    return f"https://t.me/{BOT_USERNAME}?start={payload}"


def share_url(listing_id: int) -> str:
    """E'lonni do'stlarga ulashish uchun Telegram share havolasi.

    `https://t.me/share/url?url=...&text=...` ko'rinishida — bo'shliqlar
    `%20`, `!` esa o'z joyida qoladi (Telegram aynan shunday kutadi).
    """
    text = "Mobile Legends akkaunt sotilmoqda!"
    deep_link = bot_deep_link(f"view_{listing_id}")
    encoded_text = quote(text, safe="!")
    if deep_link:
        # Deep-link ichidagi `?` va `=` belgilarini ham kodlaymiz
        return f"https://t.me/share/url?url={quote(deep_link, safe='')}&text={encoded_text}"
    # Username hali noma'lum bo'lsa — faqat matn bilan ulashamiz
    return f"https://t.me/share/url?text={encoded_text}"


# ---------------------------------------------------------------------------
# Reply tugmalar matni
# ---------------------------------------------------------------------------
BTN_SEARCH = "🔍 Akkaunt qidirish"
BTN_SELL = "💰 Akkaunt sotish"
BTN_RANDOM = "🎲 Tasodifiy akkaunt"
BTN_PRICE_FILTER = "💵 Narx boʻyicha saralash"
BTN_FAVORITES = "⭐️ Sevimlilarim"
BTN_APPRAISAL = "🔍 Akkauntni baholatish"
# Eski nom saqlanadi: boshqa kengaytmalar import qilsa ham, menyu matni yangilangan bo'lib qoladi.
BTN_CALC = BTN_APPRAISAL
BTN_SCAM = "🛡️ Firibgarni tekshirish"
BTN_MY_LISTINGS = "📋 Mening eʼlonlarim"
BTN_INBOX = "📥 Takliflar va bitimlar"
BTN_SAVED_SEARCH = "🔔 Qidiruv obunasi"
BTN_REFERRAL = "🎁 Referal"
BTN_GARANT = "🛡️ Garant xizmati"
BTN_STATS = "📊 Statistika"
BTN_GUIDE = "❓ Qoʻllanma"
BTN_REVIEWS = "📖 Sharhlar"
BTN_MARKET = "📈 Narx statistikasi"
BTN_BOT_RATING = "⭐️ Botga baho"

BTN_CANCEL = "❌ Bekor qilish"
BTN_DONE = "✅ Tayyor"

MAIN_MENU_ROWS: list[list[str]] = [
    [BTN_SEARCH, BTN_SELL],
    [BTN_RANDOM, BTN_PRICE_FILTER],
    [BTN_FAVORITES, BTN_APPRAISAL],
    [BTN_SCAM, BTN_MY_LISTINGS],
    [BTN_INBOX, BTN_SAVED_SEARCH],
    [BTN_REFERRAL, BTN_GARANT],
    [BTN_STATS, BTN_GUIDE],
    [BTN_REVIEWS],
    [BTN_MARKET, BTN_BOT_RATING],
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
def garant_username() -> str:
    """Garant akkauntining username'i (bot ichidan o'zgartiriladi)."""
    raw = str(settings.get("GARANT_USERNAME") or "").strip().lstrip("@")
    return raw or config.DEFAULT_GARANT_USERNAME


def garant_url() -> str:
    """Garant bilan bog'lanish havolasi."""
    return f"https://t.me/{garant_username()}"


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

    username = (fallback_username or garant_username()).lstrip("@").strip()
    return f"https://t.me/{username}"


def share_button(listing_id: int) -> InlineKeyboardButton:
    """«Do'stlarga ulashish» tugmasi."""
    return InlineKeyboardButton(
        text="↗️ Doʻstlarga ulashish", url=share_url(listing_id)
    )


def referral_link(user_id: int) -> str:
    """Foydalanuvchining referal havolasi."""
    return bot_deep_link(f"ref_{int(user_id)}")


def referral_share_url(user_id: int) -> str:
    """Referal havolasini do'stlarga ulashish uchun Telegram havolasi."""
    text = "Mobile Legends akkaunt savdosi — MLBB Market botiga qoʻshiling!"
    deep_link = referral_link(user_id)
    encoded_text = quote(text, safe="!")
    if deep_link:
        return f"https://t.me/share/url?url={quote(deep_link, safe='')}&text={encoded_text}"
    return f"https://t.me/share/url?text={encoded_text}"


def referral_share_button(user_id: int) -> InlineKeyboardButton:
    """Referal havolasini ulashish tugmasi."""
    return InlineKeyboardButton(
        text="↗️ Doʻstlarni taklif qilish", url=referral_share_url(user_id)
    )


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


def appraisal_answer_kb(user_id: int) -> InlineKeyboardMarkup:
    """Admin uchun akkaunt baholash javobini kiritish tugmasi."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✍️ Narx aytish (Javob berish)",
                    callback_data=f"eval_ans_{int(user_id)}",
                )
            ]
        ]
    )


def sell_mode_kb() -> InlineKeyboardMarkup:
    """Sotish yoki almashtirish (barter) rejimini tanlash."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💰 Sotish", callback_data="mode_sell")],
            [InlineKeyboardButton(text="🔄 Almashish (Barter)", callback_data="mode_trade")],
        ]
    )


def listing_action_kb(listing: dict[str, Any]) -> InlineKeyboardMarkup:
    """Katalog va kanal uchun e'lon amallari klaviaturasi."""
    listing_id = listing["id"]
    listing_type = listing.get("listing_type", "sell")
    is_trade = listing.get("listing_mode") == "trade"

    if listing_type == "buy":
        first_text = "🛡️ Admin orqali bogʻlanish"
        contact_text = "👤 Xaridor bilan aloqa"
    elif is_trade:
        first_text = "🛡️ Admin orqali almashish"
        contact_text = "👤 Egasi bilan aloqa"
    else:
        first_text = "🛡️ Admin orqali sotib olish"
        contact_text = "👤 Sotuvchi bilan aloqa"

    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text=first_text, callback_data=f"deal_{listing_id}")],
        [
            InlineKeyboardButton(
                text="💬 Taklif yuborish" if is_trade else "💬 Narx taklif qilish",
                callback_data=f"offer_{listing_id}",
            )
        ],
        [
            InlineKeyboardButton(text="⭐️ Saqlab qoʻyish", callback_data=f"fav_{listing_id}"),
            InlineKeyboardButton(
                text=contact_text,
                url=contact_url(str(listing.get("contact") or "")),
            ),
        ],
    ]

    extra: list[InlineKeyboardButton] = [
        InlineKeyboardButton(text="🔎 Oʻxshash eʼlonlar", callback_data=f"sim_{listing_id}")
    ]
    if listing_type != "buy":
        # Sharh faqat sotib olingan e'lon uchun qoldiriladi
        if listing.get("status") == "sold":
            extra.append(
                InlineKeyboardButton(
                    text="⭐️ Sharh qoldirish", callback_data=f"rvw_{listing_id}"
                )
            )
        extra.append(
            InlineKeyboardButton(
                text="📖 Sharhlarni koʻrish",
                callback_data=f"rvws_{int(listing.get('user_id') or 0)}",
            )
        )
        extra.append(
            InlineKeyboardButton(
                text="🚨 Shikoyat qilish", callback_data=f"rep_l_{listing_id}"
            )
        )
    rows.append(extra)
    rows.append(
        [
            InlineKeyboardButton(
                text="💬 Kommentlar", callback_data=f"cmt_{listing_id}"
            )
        ]
    )
    if listing_type != "buy":
        rows.append(
            [
                InlineKeyboardButton(
                    text="👤 Sotuvchi reytingi",
                    callback_data=f"sp_{int(listing.get('user_id') or 0)}",
                )
            ]
        )
    rows.append([share_button(listing_id)])

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


def my_listing_kb(listing: dict[str, Any]) -> InlineKeyboardMarkup:
    """Mening e'lonlarim uchun amallar.

    «📉 Narxni tushirish» faqat aktiv va narxi bo'lgan (barter/so'rov emas)
    e'lonlar uchun ko'rsatiladi.
    """
    listing_id = int(listing["id"])
    status = str(listing.get("status") or "")
    is_sell = (
        listing.get("listing_type", "sell") != "buy"
        and listing.get("listing_mode", "sell") != "trade"
        and bool(listing.get("price_numeric"))
    )

    rows: list[list[InlineKeyboardButton]] = []

    if status == "expired":
        rows.append(
            [
                InlineKeyboardButton(
                    text="🔄 Eʼlonni yangilash", callback_data=f"renew_{listing_id}"
                )
            ]
        )
    else:
        rows.append(
            [InlineKeyboardButton(text="✅ Sotildi deb belgilash", callback_data=f"sold_{listing_id}")]
        )

    if status == "active" and is_sell:
        rows.append(
            [InlineKeyboardButton(text="📉 Narxni tushirish", callback_data=f"drop_price_{listing_id}")]
        )

    if status in ("active", "pending"):
        rows.append(
            [InlineKeyboardButton(text="✏️ Tahrirlash", callback_data=f"edit_{listing_id}")]
        )

    if status == "active":
        rows.append(
            [InlineKeyboardButton(text="🔄 Eʼlonni koʻtarish (UP)", callback_data=f"bump_{listing_id}")]
        )

    rows.append([share_button(listing_id)])

    return InlineKeyboardMarkup(inline_keyboard=rows)


def moderation_kb(listing_id: int) -> InlineKeyboardMarkup:
    """Admin moderatsiyasi klaviaturasi."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Kanalga chiqarish", callback_data=f"app_{listing_id}"
                ),
                InlineKeyboardButton(text="❌ Rad etish", callback_data=f"rej_{listing_id}"),
            ],
            [
                InlineKeyboardButton(
                    text="🤖 AI tekshiruvi (qoʻlda)", callback_data=f"ai_chk_{listing_id}"
                )
            ],
        ]
    )


def ai_panel_kb() -> InlineKeyboardMarkup:
    """«🤖 AI moderatsiya» boshqaruv paneli (admin panel ichida)."""
    enabled = settings.get_bool("AI_ENABLED")
    rows = [
        [
            InlineKeyboardButton(
                text="⛔️ AI tekshiruvni oʻchirish" if enabled else "✅ AI tekshiruvni yoqish",
                callback_data="adm_ai_toggle",
            )
        ],
        [
            InlineKeyboardButton(
                text="🔑 AI API kalitini kiritish", callback_data="cfg_edit|AI_API_KEY"
            )
        ],
        [
            InlineKeyboardButton(text="🔌 Ulanishni tekshirish", callback_data="cfg_ai_test"),
            InlineKeyboardButton(text="📋 Modellarni koʻrish", callback_data="cfg_ai_models"),
        ],
        [InlineKeyboardButton(text="🔎 Kalit qayerda ishlaydi?", callback_data="cfg_ai_find")],
        [InlineKeyboardButton(text="⚙️ Barcha sozlamalar", callback_data="cfg_g|ai")],
        [InlineKeyboardButton(text="⬅️ Admin panel", callback_data="adm_back")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_panel_kb() -> InlineKeyboardMarkup:
    """Admin panel klaviaturasi."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📢 Xabar tarqatish", callback_data="adm_broadcast"),
                InlineKeyboardButton(text="📊 Toʻliq statistika", callback_data="adm_stats"),
            ],
            [
                InlineKeyboardButton(text="📡 Kanallar boshqaruvi", callback_data="adm_sub_channel"),
                InlineKeyboardButton(text="👥 Adminlar", callback_data="adm_admins"),
            ],
            [
                InlineKeyboardButton(text="👤 Foydalanuvchi qidirish", callback_data="adm_lookup"),
                InlineKeyboardButton(text="📊 Bugungi hisobot", callback_data="adm_today"),
            ],
            [
                InlineKeyboardButton(text="🚫 Qora roʻyxatga kiritish", callback_data="adm_ban"),
                InlineKeyboardButton(text="📋 Qora roʻyxat", callback_data="adm_blacklist"),
            ],
            [
                InlineKeyboardButton(
                    text=(
                        "🤖 AI: ✅ yoqilgan"
                        if settings.get_bool("AI_ENABLED")
                        else "🤖 AI: ⛔️ oʻchiq"
                    ),
                    callback_data="adm_ai",
                )
            ],
            [
                InlineKeyboardButton(text="⚙️ Sozlamalar", callback_data="cfg_home"),
                InlineKeyboardButton(text="🤖 AI sozlamalari", callback_data="cfg_g|ai"),
            ],
            [
                InlineKeyboardButton(text="📈 Analitika", callback_data="adm_analytics"),
                InlineKeyboardButton(text="💾 Zaxira nusxa", callback_data="adm_backup"),
            ],
            [InlineKeyboardButton(text="🚨 Shikoyatlar", callback_data="adm_reports")],
            [InlineKeyboardButton(text="♻️ Bazani tiklash", callback_data="adm_restore")],
        ]
    )


# ---------------------------------------------------------------------------
# Sozlamalar paneli
# ---------------------------------------------------------------------------
def _truncate(text: str, limit: int = 58) -> str:
    """Tugma matnini Telegram chegarasiga sig'diradi."""
    return text if len(text) <= limit else text[: limit - 1] + "…"


def settings_groups_kb() -> InlineKeyboardMarkup:
    """Sozlama guruhlari ro'yxati."""
    rows: list[list[InlineKeyboardButton]] = []
    for group, label in GROUPS.items():
        count = len(settings.group_items(group))
        rows.append(
            [InlineKeyboardButton(text=f"{label} ({count})", callback_data=f"cfg_g|{group}")]
        )
    rows.append(
        [InlineKeyboardButton(text="🔌 AI ulanishni tekshirish", callback_data="cfg_ai_test")]
    )
    rows.append(
        [InlineKeyboardButton(text="📋 Modellarni koʻrish", callback_data="cfg_ai_models")]
    )
    rows.append(
        [InlineKeyboardButton(text="🔎 Kalit qayerda ishlaydi?", callback_data="cfg_ai_find")]
    )
    rows.append([InlineKeyboardButton(text="⬅️ Admin panel", callback_data="adm_back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def settings_items_kb(group: str) -> InlineKeyboardMarkup:
    """Guruhdagi sozlamalar ro'yxati (joriy qiymatlar bilan)."""
    rows: list[list[InlineKeyboardButton]] = []
    for item in settings.group_items(group):
        mark = "✏️" if settings.is_overridden(item.key) else "•"
        text = _truncate(f"{mark} {item.label}: {settings.display(item.key)}")
        rows.append([InlineKeyboardButton(text=text, callback_data=f"cfg_s|{item.key}")])
    rows.append(
        [
            InlineKeyboardButton(
                text="↩️ Guruhni standartga qaytarish", callback_data=f"cfg_resetg|{group}"
            )
        ]
    )
    rows.append([InlineKeyboardButton(text="⬅️ Orqaga", callback_data="cfg_home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def setting_detail_kb(spec: Setting, group: str) -> InlineKeyboardMarkup:
    """Bitta sozlama uchun amallar klaviaturasi."""
    rows: list[list[InlineKeyboardButton]] = []
    if spec.kind == "bool":
        rows.append(
            [
                InlineKeyboardButton(
                    text="🔄 Almashtirish (yoqish/oʻchirish)",
                    callback_data=f"cfg_toggle|{spec.key}",
                )
            ]
        )
    else:
        rows.append(
            [
                InlineKeyboardButton(
                    text="✏️ Oʻzgartirish", callback_data=f"cfg_edit|{spec.key}"
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text="↩️ Standart qiymat", callback_data=f"cfg_reset|{spec.key}"
            )
        ]
    )
    if spec.key == "AI_API_KEY":
        rows.append(
            [InlineKeyboardButton(text="🔌 Kalitni tekshirish", callback_data="cfg_ai_test")]
        )
        rows.append(
            [
                InlineKeyboardButton(
                    text="📋 Modellarni koʻrish", callback_data="cfg_ai_models"
                ),
                InlineKeyboardButton(text="🔎 Kalitni izlash", callback_data="cfg_ai_find"),
            ]
        )
    rows.append([InlineKeyboardButton(text="⬅️ Orqaga", callback_data=f"cfg_g|{group}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admins_kb() -> InlineKeyboardMarkup:
    """Adminlarni boshqarish klaviaturasi."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Admin qoʻshish", callback_data="adm_add_admin")],
            [InlineKeyboardButton(text="➖ Admin oʻchirish", callback_data="adm_remove_admin")],
            [InlineKeyboardButton(text="⬅️ Orqaga", callback_data="adm_back")],
        ]
    )


def channels_kb(
    post_set: bool = False,
    required_set: bool = False,
) -> InlineKeyboardMarkup:
    """Kanallar boshqaruvi klaviaturasi."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=("✅ " if post_set else "📣 ") + "Eʼlon kanali",
                    callback_data="adm_post_channel",
                )
            ],
            [
                InlineKeyboardButton(
                    text=("✅ " if required_set else "🔒 ") + "Majburiy kanal",
                    callback_data="adm_sub_required",
                )
            ],
            [InlineKeyboardButton(text="⬅️ Orqaga", callback_data="adm_back")],
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


def vip_kb(prefix: str = "vip", credits: int = 0) -> InlineKeyboardMarkup:
    """VIP tanlash klaviaturasi.

    :param credits: foydalanuvchidagi bepul VIP kreditlari soni. 0 dan katta
        bo'lsa, bepul ishlatish tugmasi ham ko'rsatiladi.
    """
    rows: list[list[InlineKeyboardButton]] = []
    if credits > 0:
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"🎁 Bepul VIP ishlatish ({credits} ta)",
                    callback_data=f"{prefix}_free",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(text="💎 Ha, VIP qilib qoʻying", callback_data=f"{prefix}_yes"),
            InlineKeyboardButton(text="🙂 Yoʻq", callback_data=f"{prefix}_no"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


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


def private_chat_kb(payload: str, text: str = "🔒 Shaxsiy chatda ochish") -> InlineKeyboardMarkup:
    """Botning shaxsiy chatini deep-link orqali ochish tugmasi."""
    link = bot_deep_link(payload)
    if not link:
        return InlineKeyboardMarkup(inline_keyboard=[])
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=text, url=link)]]
    )


def garant_kb() -> InlineKeyboardMarkup:
    """Garant xizmati klaviaturasi."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"🛡️ Garant: @{garant_username()}",
                    url=garant_url(),
                )
            ]
        ]
    )


def guide_kb() -> InlineKeyboardMarkup:
    """Qo'llanma klaviaturasi."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"🛡️ Garant bilan bogʻlanish: @{garant_username()}",
                    url=garant_url(),
                )
            ],
            [
                InlineKeyboardButton(
                    text="➕ Kanaldagi eʼlonlarni koʻrish",
                    url=_channel_link(),
                )
            ],
        ]
    )


def _channel_link() -> str:
    """Asosiy kanal havolasi (bot ichidan sozlanadi)."""
    channel = str(settings.get("DEFAULT_CHANNEL_ID") or "").strip()
    if channel.startswith("@"):
        return f"https://t.me/{channel.lstrip('@')}"
    return garant_url()


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


def dm_user_kb(user_id: int, verified: bool = False) -> InlineKeyboardMarkup:
    """Admin panelda foydalanuvchiga xabar yuborish va tasdiqlash."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=("✅ Tasdiqlashni olib tashlash" if verified
                          else "✅ Sotuvchini tasdiqlash"),
                    callback_data=f"vfy_{int(user_id)}",
                )
            ],
            [InlineKeyboardButton(text="✉️ Xabar yuborish", callback_data=f"adm_dm_{user_id}")],
        ]
    )


# ---------------------------------------------------------------------------
# Yangi bo'limlar uchun klaviaturalar
# ---------------------------------------------------------------------------
def offer_response_kb(offer_id: int) -> InlineKeyboardMarkup:
    """Sotuvchi uchun taklifga javob berish tugmalari."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Qabul qilish", callback_data=f"off_ok_{offer_id}"),
                InlineKeyboardButton(text="❌ Rad etish", callback_data=f"off_no_{offer_id}"),
            ],
            [InlineKeyboardButton(text="💬 Javob yozish", callback_data=f"off_msg_{offer_id}")],
        ]
    )


def deal_status_kb(deal_id: int) -> InlineKeyboardMarkup:
    """Admin uchun bitim holatini boshqarish tugmalari."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🛡️ Garantga oʻtdi", callback_data=f"dstat_{deal_id}_garant"
                )
            ],
            [
                InlineKeyboardButton(
                    text="✅ Yakunlandi", callback_data=f"dstat_{deal_id}_done"
                ),
                InlineKeyboardButton(
                    text="❌ Bekor qilindi", callback_data=f"dstat_{deal_id}_cancelled"
                ),
            ],
        ]
    )


def bot_rating_kb() -> InlineKeyboardMarkup:
    """Botga baho berish uchun 1–10 tanlov (balanddan pastga)."""
    half = 5
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=str(score), callback_data=f"botr_{score}")
                for score in range(10, half, -1)
            ],
            [
                InlineKeyboardButton(text=str(score), callback_data=f"botr_{score}")
                for score in range(half, 0, -1)
            ],
        ]
    )


def comment_list_kb(listing_id: int) -> InlineKeyboardMarkup:
    """E'lon kommentlari: ko'rish, yozish, e'lon kartasiga qaytish."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✍️ Komment yozish", callback_data=f"cmt_w_{listing_id}")],
            [InlineKeyboardButton(text="🔙 Eʼlon kartasiga", callback_data=f"view_{listing_id}")],
        ]
    )


#: Shikoyat sabablari: (matn, qisqa kod)
REPORT_REASONS: tuple[tuple[str, str], ...] = (
    ("🚨 Firibgarlik", "scam"),
    ("📢 Yolgʻon eʼlon", "fake"),
    ("💰 Real narx yashirilgan", "price"),
    ("🤬 Qoʻpol munosabat", "abuse"),
    ("🔁 Eʼlonni spam qilish", "spam"),
    ("📝 Boshqa", "other"),
)


def report_reason_kb(listing_id: int, seller_id: int) -> InlineKeyboardMarkup:
    """Shikoyat qilish sabablarini tanlash."""
    rows = [
        [
            InlineKeyboardButton(
                text=label, callback_data=f"rep_r_{code}_{listing_id}_{seller_id}"
            )
        ]
        for label, code in REPORT_REASONS
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


#: Bozor statistikasi uchun taqqoslash davrlari (kun)
MARKET_PERIODS: tuple[int, ...] = (7, 30, 90)


def market_period_kb(current: int = 30) -> InlineKeyboardMarkup:
    """Bozor statistikasining davrini o'zgartirish."""
    rows = [
        [
            InlineKeyboardButton(
                text=f"{days} kun" + (" ✅" if days == current else ""),
                callback_data=f"mkt_{days}",
            )
            for days in MARKET_PERIODS
        ],
        [InlineKeyboardButton(text="⬅️ Orqaga", callback_data="mkt_back")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def report_admin_kb(report_id: int, target_id: int) -> InlineKeyboardMarkup:
    """Admin uchun shikoyatni ko'rish va yopish."""
    rows = [
        [
            InlineKeyboardButton(
                text="✅ Koʻrildi", callback_data=f"rep_ok_{report_id}"
            ),
            InlineKeyboardButton(
                text="🚫 Rad etish", callback_data=f"rep_no_{report_id}"
            ),
        ]
    ]
    if target_id:
        rows.append(
            [InlineKeyboardButton(text="💬 Xabar yuborish", callback_data=f"adm_dm_{target_id}")]
        )
    rows.append([InlineKeyboardButton(text="⬅️ Admin panel", callback_data="adm_back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def verify_seller_kb(user_id: int, verified: bool) -> InlineKeyboardMarkup:
    """Admin uchun sotuvchini tasdiqlash (badge) tugmasi."""
    text = "✅ Olib tashlash" if verified else "✅ Sotuvchini tasdiqlash"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=text, callback_data=f"vfy_{int(user_id)}")],
            [InlineKeyboardButton(text="⬅️ Orqaga", callback_data="adm_back")],
        ]
    )


def review_rating_kb() -> InlineKeyboardMarkup:
    """Sharh uchun 1–5 baho tanlash."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=f"{score}⭐️", callback_data=f"rvwr_{score}")
                for score in range(1, 6)
            ]
        ]
    )


def saved_price_kb() -> InlineKeyboardMarkup:
    """Saqlangan qidiruv uchun narx oralig'ini tanlash."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🟢 100k gacha", callback_data="saved_p_100"),
                InlineKeyboardButton(text="🟡 100k – 400k", callback_data="saved_p_400"),
                InlineKeyboardButton(text="🔴 400k+", callback_data="saved_p_max"),
            ],
            [InlineKeyboardButton(text="❔ Narx muhim emas", callback_data="saved_p_any")],
        ]
    )


def saved_searches_kb(searches: list[dict[str, Any]]) -> InlineKeyboardMarkup:
    """Saqlangan qidiruvlar ro'yxati (o'chirish tugmalari bilan)."""
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text="➕ Yangi obuna", callback_data="saved_new")]
    ]
    for search in searches:
        label = saved_search_label(search)
        rows.append(
            [InlineKeyboardButton(text=f"🗑 {label}", callback_data=f"saved_del_{search['id']}")]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def saved_search_label(search: dict[str, Any]) -> str:
    """Saqlangan qidiruv uchun qisqa yorliq."""
    low, high = search.get("min_price"), search.get("max_price")
    if low is None and high is None:
        price = "har qanday narx"
    elif low is None:
        price = f"{int(high):,}".replace(",", " ") + " gacha"
    elif high is None:
        price = f"{int(low):,}".replace(",", " ") + " dan"
    else:
        price = (
            f"{int(low):,}".replace(",", " ")
            + " – "
            + f"{int(high):,}".replace(",", " ")
        )
    keyword = str(search.get("keyword") or "").strip()
    return f"{price}" + (f" · {keyword}" if keyword else "")


def edit_listing_kb(listing_id: int) -> InlineKeyboardMarkup:
    """E'lonni tahrirlash maydonlarini tanlash."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="💵 Narx", callback_data=f"editf_price_{listing_id}"),
                InlineKeyboardButton(text="📝 Izoh", callback_data=f"editf_desc_{listing_id}"),
            ],
            [InlineKeyboardButton(text="🔗 Aloqa", callback_data=f"editf_contact_{listing_id}")],
        ]
    )


def referral_kb(user_id: int) -> InlineKeyboardMarkup:
    """Referal bo'limi klaviaturasi."""
    return InlineKeyboardMarkup(
        inline_keyboard=[[referral_share_button(user_id)]]
    )
