"""Katalog: tasodifiy akkaunt, narx bo'yicha saralash va xarid so'rovi."""

from __future__ import annotations

import logging
from typing import Optional

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from database import db
from handlers.common import (
    default_header,
    esc,
    format_price,
    is_trade,
    notify_admin,
    send_listing_card,
    seller_label_of,
    user_label,
    user_link,
)
from keyboards import (
    BTN_PRICE_FILTER,
    BTN_RANDOM,
    deal_admin_kb,
    listing_action_kb,
    price_filter_kb,
)

logger = logging.getLogger(__name__)

router = Router(name="catalog")

FILTER_ASK = (
    "💵 <b>Narx boʻyicha saralash</b>\n\n"
    "Qaysi narx oraligʻidagi akkauntlar qiziqtiradi?"
)

PRICE_RANGES: dict[str, tuple[Optional[int], Optional[int], str]] = {
    "f_100": (None, 100_000, "🟢 100 000 soʻmgacha"),
    "f_400": (100_000, 400_000, "🟡 100 000 — 400 000 soʻm"),
    "f_max": (400_000, None, "🔴 400 000 soʻmdan yuqori"),
}

MAX_RESULTS = 10


async def _send_listings(
    bot: Bot,
    chat_id: int,
    listings: list[dict],
    header: Optional[str] = None,
) -> int:
    """E'lonlar ro'yxatini kartochkalar ko'rinishida yuboradi."""
    sent = 0
    for listing in listings[:MAX_RESULTS]:
        try:
            await send_listing_card(
                bot,
                chat_id,
                listing,
                markup=listing_action_kb(listing),
                header=header if sent == 0 else None,
                seller_label=await seller_label_of(listing),
            )
            sent += 1
        except TelegramAPIError as exc:
            logger.warning("Eʼlon #%s yuborilmadi: %s", listing.get("id"), exc)
    return sent


@router.message(StateFilter(None), F.text == BTN_RANDOM)
async def random_listing(message: Message, bot: Bot) -> None:
    """Tasodifiy aktiv e'lonni ko'rsatadi."""
    listing = await db.get_random_active_listing()
    if listing is None:
        await message.answer(
            "😔 Hozircha kanalda aktiv eʼlonlar yoʻq.\n\n"
            "Birozdan soʻng qaytadan urinib koʻring yoki oʻzingiz eʼlon joylang."
        )
        return

    await send_listing_card(
        bot,
        message.chat.id,
        listing,
        markup=listing_action_kb(listing),
        header=f"🎲 <b>Tasodifiy akkaunt</b>\n{default_header(listing)}",
        seller_label=await seller_label_of(listing),
    )


@router.message(StateFilter(None), F.text == BTN_PRICE_FILTER)
async def price_filter_menu(message: Message) -> None:
    """Narx oralig'ini tanlash menyusi."""
    await message.answer(FILTER_ASK, reply_markup=price_filter_kb())


@router.callback_query(F.data.in_(set(PRICE_RANGES.keys())))
async def price_filter_cb(callback: CallbackQuery, bot: Bot) -> None:
    """Tanlangan narx oralig'i bo'yicha e'lonlarni chiqaradi."""
    min_price, max_price, label = PRICE_RANGES[callback.data or "f_100"]
    await callback.answer(f"{label} — qidirilmoqda…")

    listings = await db.get_filtered_listings(min_price, max_price, limit=MAX_RESULTS)
    if not listings:
        if isinstance(callback.message, Message):
            await callback.message.answer(
                f"😔 <b>{esc(label)}</b> oraligʻida aktiv eʼlon topilmadi.\n\n"
                "Boshqa oraliqni tanlab koʻring yoki keyinroq qaytadan urinib koʻring.",
                reply_markup=price_filter_kb(),
            )
        return

    if isinstance(callback.message, Message):
        await callback.message.answer(
            f"🔎 <b>{esc(label)}</b> — {len(listings)} ta eʼlon topildi.\n"
            "Quyidagi eʼlonlarni koʻrib chiqing 👇"
        )
        await _send_listings(bot, callback.message.chat.id, listings)


@router.callback_query(F.data.startswith("deal_"))
async def deal_cb(callback: CallbackQuery, bot: Bot) -> None:
    """Admin orqali sotib olish so'rovi."""
    user = callback.from_user
    raw_id = (callback.data or "").split("_", 1)[-1]
    if not raw_id.isdigit():
        await callback.answer("❌ Notoʻgʻri soʻrov.", show_alert=True)
        return

    listing_id = int(raw_id)
    listing = await db.get_listing(listing_id)
    if listing is None:
        await callback.answer("❌ Eʼlon topilmadi.", show_alert=True)
        return

    if listing.get("status") not in ("active", "pending"):
        await callback.answer("⚠️ Bu eʼlon endi aktiv emas.", show_alert=True)
        return

    if int(listing["user_id"]) == user.id:
        await callback.answer("🙂 Bu sizning eʼloningiz.", show_alert=True)
        return

    seller = await db.get_user(int(listing["user_id"]))
    is_buy = listing.get("listing_type") == "buy"
    trade = is_trade(listing)

    if is_buy:
        kind_line = "🛒 Xaridor soʻrovi"
    elif trade:
        kind_line = "🔄 Almashish (barter) eʼloni"
    else:
        kind_line = "💰 Sotuvchi eʼloni"

    if trade:
        demand_line = f"🎯 Talab: {esc(listing.get('trade_wanted') or 'Kelishiladi')}"
    else:
        demand_line = (
            "💵 Narx: "
            + esc(listing.get("price_display") or format_price(listing.get("price_numeric")))
        )

    admin_text = (
        "🛡️ <b>Admin orqali bitim soʻrovi!</b>\n\n"
        f"🆔 Eʼlon: <b>#{listing_id}</b>\n"
        f"📌 Turi: {kind_line}\n"
        f"🏆 Rank: {esc(listing.get('rank_info') or '—')}\n"
        f"{demand_line}\n\n"
        f"🙋 Kim murojaat qildi: {user_link(user.id, user.full_name)}"
        + (f" ({esc(user.username)})" if user.username else "")
        + f"\n🆔 Buyurtmachi ID: <code>{user.id}</code>\n"
        f"👤 Eʼlon egasi: {esc(user_label(int(listing['user_id']), (seller or {}).get('username'), (seller or {}).get('full_name')))}\n"
        f"🔗 Aloqa: {esc(listing.get('contact') or '—')}"
    )

    markup = deal_admin_kb(
        buyer_id=user.id,
        seller_id=int(listing["user_id"]),
        username_buyer=user.username,
        username_seller=(seller or {}).get("username"),
    )

    await notify_admin(bot, admin_text, markup=markup)
    await callback.answer(
        "✅ Administratsiya xabardor qilindi. Tez orada siz bilan bogʻlanadi.",
        show_alert=True,
    )

    if isinstance(callback.message, Message):
        try:
            await callback.message.reply(
                "🛡️ <b>Bitim soʻrovingiz qabul qilindi!</b>\n\n"
                "Administrator tez orada siz bilan bogʻlanadi. "
                "Iltimos, toʻlovni faqat garant orqali amalga oshiring — "
                "bu sizni firibgarlikdan himoya qiladi."
            )
        except TelegramAPIError:
            pass


__all__ = ["router"]
