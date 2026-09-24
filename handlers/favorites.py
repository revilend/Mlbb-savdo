"""Sevimlilar bo'limi."""

from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import StateFilter
from aiogram.types import CallbackQuery, Message

from database import db
from handlers.common import send_listing_card, seller_label_of
from keyboards import BTN_FAVORITES, listing_action_kb

logger = logging.getLogger(__name__)

router = Router(name="favorites")

MAX_FAVORITES_SHOWN = 10


@router.callback_query(F.data.startswith("fav_"))
async def toggle_favorite(callback: CallbackQuery) -> None:
    """Sevimlilarga qo'shadi yoki olib tashlaydi."""
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

    if await db.is_favorite(user.id, listing_id):
        await db.remove_favorite(user.id, listing_id)
        await callback.answer("🗑 Sevimlilardan olib tashlandi.")
        return

    await db.add_favorite(user.id, listing_id)
    count = await db.count_favorites(listing_id)
    await callback.answer(
        f"⭐️ Sevimlilarga qoʻshildi! Bu eʼlonni {count} kishi saqlagan.", show_alert=False
    )


@router.message(StateFilter(None), F.text == BTN_FAVORITES)
async def show_favorites(message: Message, bot: Bot) -> None:
    """Foydalanuvchining sevimli e'lonlarini ko'rsatadi."""
    favorites = await db.get_favorites(message.from_user.id)
    if not favorites:
        await message.answer(
            "⭐️ <b>Sevimlilar roʻyxati boʻsh.</b>\n\n"
            "Eʼlonlarni koʻrib chiqib, «⭐️ Saqlab qoʻyish» tugmasi orqali "
            "yoqqan akkauntlarni shu yerga saqlab qoʻyishingiz mumkin."
        )
        return

    await message.answer(
        f"⭐️ <b>Sevimlilar</b> — {len(favorites)} ta eʼlon topildi.\n"
        "Faol boʻlmagan eʼlonlar ham koʻrsatiladi."
    )

    shown = 0
    for listing in favorites[:MAX_FAVORITES_SHOWN]:
        try:
            await send_listing_card(
                bot,
                message.chat.id,
                listing,
                markup=listing_action_kb(listing),
                seller_label=await seller_label_of(listing),
            )
            shown += 1
        except TelegramAPIError as exc:
            logger.warning("Sevimli eʼlon #%s yuborilmadi: %s", listing.get("id"), exc)

    if len(favorites) > MAX_FAVORITES_SHOWN:
        await message.answer(
            f"ℹ️ Yana {len(favorites) - MAX_FAVORITES_SHOWN} ta eʼlon bor. "
            "Koʻrish uchun ularni qisqartirib turing."
        )
