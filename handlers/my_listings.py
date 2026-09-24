"""Mening e'lonlarim: holatni ko'rish, sotildi deb belgilash va UP qilish."""

from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import StateFilter
from aiogram.types import CallbackQuery, Message

from database import db
from handlers.common import (
    edit_listing_card,
    get_channel_id,
    is_bump_available,
    safe_delete,
    send_listing_card,
    status_label,
)
from keyboards import BTN_MY_LISTINGS, my_listing_kb

logger = logging.getLogger(__name__)

router = Router(name="my_listings")

MAX_SHOWN = 10


@router.message(StateFilter(None), F.text == BTN_MY_LISTINGS)
async def show_my_listings(message: Message, bot: Bot) -> None:
    """Foydalanuvchining barcha e'lonlarini ko'rsatadi."""
    listings = await db.get_user_listings(message.from_user.id)
    if not listings:
        await message.answer(
            "📋 <b>Sizda hali eʼlonlar yoʻq.</b>\n\n"
            "«💰 Akkaunt sotish» boʻlimi orqali birinchi eʼloningizni joylang — "
            "moderatsiyadan soʻng u kanalga chiqadi."
        )
        return

    await message.answer(f"📋 <b>Mening eʼlonlarim</b> — jami {len(listings)} ta.")

    for listing in listings[:MAX_SHOWN]:
        status = str(listing.get("status") or "pending")
        header = f"{status_label(status)}"
        markup = my_listing_kb(int(listing["id"])) if status == "active" else None
        try:
            await send_listing_card(bot, message.chat.id, listing, markup=markup, header=header)
        except TelegramAPIError as exc:
            logger.warning("Mening eʼlonim #%s yuborilmadi: %s", listing.get("id"), exc)

    if len(listings) > MAX_SHOWN:
        await message.answer(
            f"ℹ️ Yana {len(listings) - MAX_SHOWN} ta eʼlon mavjud. "
            "Ularni kichik boʻlib koʻrib chiqing."
        )


@router.callback_query(F.data.startswith("sold_"))
async def mark_as_sold(callback: CallbackQuery, bot: Bot) -> None:
    """E'lonni «sotildi» deb belgilaydi va kanaldagi xabarni yangilaydi."""
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

    if int(listing["user_id"]) != user.id:
        await callback.answer("⛔️ Bu eʼlon sizga tegishli emas.", show_alert=True)
        return

    if listing.get("status") in ("sold", "found"):
        await callback.answer("ℹ️ Bu eʼlon allaqachon yopilgan.", show_alert=True)
        return

    new_status = "found" if listing.get("listing_type") == "buy" else "sold"
    await db.update_listing_status(listing_id, new_status)
    updated = await db.get_listing(listing_id)

    if updated is None:
        await callback.answer("⚠️ Texnik xatolik yuz berdi.", show_alert=True)
        return

    channel_id = await get_channel_id()
    if channel_id and updated.get("channel_msg_id"):
        header = (
            "🔴 <b>SOTILDI</b>"
            if new_status == "sold"
            else "✅ <b>TOPILDI</b>"
        )
        await edit_listing_card(
            bot,
            channel_id,
            int(updated["channel_msg_id"]),
            updated,
            markup=None,
            header=header,
        )

    await callback.answer("✅ Eʼlon yopildi. Tabriklaymiz!")

    if isinstance(callback.message, Message):
        await callback.message.answer(
            f"✅ <b>Eʼlon #{listing_id} yopildi.</b>\n\n"
            f"📌 Yangi holat: {status_label(new_status)}\n"
            "Kanalda eʼlon «SOTILDI» belgisi bilan yangilandi."
        )


@router.callback_query(F.data.startswith("bump_"))
async def bump_listing(callback: CallbackQuery, bot: Bot) -> None:
    """E'lonni 24 soatda bir marta ko'taradi (UP)."""
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

    if int(listing["user_id"]) != user.id:
        await callback.answer("⛔️ Bu eʼlon sizga tegishli emas.", show_alert=True)
        return

    if listing.get("status") != "active":
        await callback.answer(
            "⚠️ Faqat aktiv eʼlonlarni koʻtarish mumkin.", show_alert=True
        )
        return

    available, remaining = is_bump_available(listing)
    if not available:
        await callback.answer(
            f"⏳ Eʼlonni 24 soatda faqat bir marta koʻtarish mumkin.\n"
            f"Keyingi urinishga {remaining} qoldi.",
            show_alert=True,
        )
        return

    channel_id = await get_channel_id()
    if not channel_id:
        await callback.answer("⚠️ Kanal sozlanmagan. Administratorga murojaat qiling.", show_alert=True)
        return

    try:
        message = await send_listing_card(
            bot,
            channel_id,
            listing,
            markup=None,
            header="🔄 <b>Eʼlon koʻtarildi (UP)</b>",
        )
    except TelegramAPIError as exc:
        logger.error("UP qilishda xatolik (#%s): %s", listing_id, exc)
        await callback.answer("⚠️ Kanalga joylab boʻlmadi. Keyinroq urinib koʻring.", show_alert=True)
        return

    old_message_id = listing.get("channel_msg_id")
    photos = list(listing.get("photos") or [])

    if message is not None:
        await db.set_channel_message_id(listing_id, message.message_id)

    # Bitta rasmdan iborat eski xabarni olib tashlaymiz (media-guruhni buzmaslik uchun)
    if old_message_id and len(photos) <= 1:
        await safe_delete(bot, channel_id, int(old_message_id))

    await db.update_bump_time(listing_id)
    await callback.answer("🔄 Eʼlon koʻtarildi! U kanalda yuqorida turadi.")


__all__ = ["router"]
