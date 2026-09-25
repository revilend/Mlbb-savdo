"""Narx taklif qilish (OfferFSM).

Foydalanuvchi e'londagi «💬 Narx taklif qilish» tugmasini bosgach,
summani kiritadi va bot taklifni e'lon egasiga yetkazadi.
"""

from __future__ import annotations

import logging
from typing import Optional

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

import config
from database import db
from handlers.common import (
    esc,
    format_price,
    is_trade,
    menu_button_guard,
    notify_admin,
    parse_price,
    user_label,
)
from keyboards import BTN_CANCEL, cancel_kb, main_menu_kb, offer_response_kb
from settings import settings
from states import OfferFSM

logger = logging.getLogger(__name__)

router = Router(name="offers")


@router.callback_query(F.data.startswith("offer_"))
async def offer_start(callback: CallbackQuery, state: FSMContext) -> None:
    """Taklif jarayonini boshlaydi."""
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

    if listing.get("status") != "active":
        await callback.answer("⚠️ Bu eʼlon aktiv emas, taklif yuborib boʻlmaydi.", show_alert=True)
        return

    if int(listing["user_id"]) == user.id:
        await callback.answer("🙂 Bu sizning eʼloningiz.", show_alert=True)
        return

    await state.set_state(OfferFSM.waiting_amount)
    await state.update_data(offer_listing_id=listing_id)

    if isinstance(callback.message, Message):
        if is_trade(listing):
            await callback.message.answer(
                "🔄 <b>Almashish taklifi</b>\n\n"
                f"🆔 Eʼlon: <b>#{listing_id}</b>\n"
                f"🎯 Egasi talabi: <b>{esc(listing.get('trade_wanted') or 'Kelishiladi')}</b>\n\n"
                "Qanday akkauntni almashtirishga taklif qilasiz? "
                "Qisqacha yozib yuboring.\n\n"
                "Masalan: <i>Mythic Glory, 90kof, 3 legend</i>",
                reply_markup=cancel_kb(),
            )
        else:
            await callback.message.answer(
                "💬 <b>Narx taklif qilish</b>\n\n"
                f"🆔 Eʼlon: <b>#{listing_id}</b>\n"
                f"💵 Eʼlon narxi: <b>{esc(listing.get('price_display') or format_price(listing.get('price_numeric')))}</b>\n\n"
                "Qancha narx taklif qilasiz? Summani raqamda yozing "
                "(masalan: <code>1200000</code>).",
                reply_markup=cancel_kb(),
            )

    await callback.answer("✍️ Taklifingizni kiriting.")


@router.message(OfferFSM.waiting_amount, F.text)
async def offer_amount(message: Message, state: FSMContext, bot: Bot) -> None:
    """Taklif summasini qabul qiladi va sotuvchiga yuboradi."""
    user = message.from_user
    if user is None:
        return

    if message.text == BTN_CANCEL:
        # Umumiy bekor qilish handleri odatda buni ushlaydi;
        # bu yerdagi tekshiruv faqat zaxira uchun.
        await state.clear()
        await message.answer("✅ Amal bekor qilindi.", reply_markup=main_menu_kb())
        return

    if menu_button_guard(message):
        await message.answer("ℹ️ Avval joriy amalni yakunlang yoki «❌ Bekor qilish» tugmasini bosing.")
        return

    data = await state.get_data()
    listing_id = int(data.get("offer_listing_id") or 0)
    listing = await db.get_listing(listing_id) if listing_id else None

    if listing is None:
        await state.clear()
        await message.answer(
            "⚠️ Eʼlon topilmadi. Taklif yuborilmadi.",
            reply_markup=main_menu_kb(),
        )
        return

    trade = is_trade(listing)
    offer_line = ""
    offer_text = ""
    summary = ""
    amount_value: Optional[int] = None
    trade_text = ""

    if trade:
        offered = (message.text or "").strip()
        if len(offered) < 3:
            await message.answer(
                "❌ Taklifni batafsilroq yozing.\n\n"
                "Masalan: <i>Mythic Glory, 90kof, 3 legend</i>"
            )
            return
        offered = offered[:300]
        trade_text = offered
        offer_line = f"🔄 Taklif: {esc(offered)}"
        summary = offered
    else:
        amount = parse_price(message.text)
        if amount is None or amount < int(settings.get("MIN_PRICE")):
            await message.answer(
                "❌ Summani tushunmadim. Iltimos, faqat raqam bilan yozing.\n\n"
                "Masalan: <code>1200000</code>"
            )
            return
        amount_value = int(amount)
        offer_line = f"💵 Taklif summasi: {esc(format_price(amount))}"
        summary = format_price(amount)

    await state.clear()

    if listing.get("status") != "active":
        await message.answer(
            "⚠️ Bu eʼlon endi aktiv emas. Taklif yuborilmadi.",
            reply_markup=main_menu_kb(),
        )
        return

    seller_id = int(listing["user_id"])
    seller = await db.get_user(seller_id)
    seller_name = user_label(seller_id, (seller or {}).get("username"), (seller or {}).get("full_name"))

    buyer_ref = f"@{user.username}" if user.username else f"ID: {user.id}"

    # Taklifni bazaga saqlaymiz — shunda sotuvchi «📥 Takliflar va bitimlar»
    # boʻlimidan uni qabul yoki rad etishi mumkin boʻladi.
    offer_id = await db.create_offer(
        listing_id=listing_id,
        buyer_id=user.id,
        seller_id=seller_id,
        amount=amount_value,
        offer_text=trade_text,
        is_trade=trade,
    )

    if trade:
        offer_text = (
            "🔄 <b>Yangi almashish taklifi!</b>\n\n"
            f"🆔 Sizning <b>#{listing_id}</b> eʼloningizga xaridor quyidagi "
            "akkauntni almashtirishni taklif qilmoqda:\n\n"
            f"🎯 <b>{esc(summary)}</b>\n\n"
            f"Qabul qilsangiz bogʻlaning: {esc(buyer_ref)}\n"
            f"\n🆔 Taklif raqami: <b>#{offer_id}</b>"
        )
    else:
        offer_text = (
            "🔔 <b>Yangi narx taklifi!</b>\n\n"
            f"🆔 Sizning <b>#{listing_id}</b> eʼloningizga xaridor "
            f"<b>{esc(summary)}</b> taklif qilmoqda!\n\n"
            f"Qabul qilsangiz bogʻlaning: {esc(buyer_ref)}\n"
            f"\n🆔 Taklif raqami: <b>#{offer_id}</b>"
        )

    delivered = False
    try:
        await bot.send_message(
            seller_id,
            offer_text,
            reply_markup=offer_response_kb(offer_id),
            disable_web_page_preview=True,
        )
        delivered = True
    except TelegramAPIError as exc:
        logger.warning("Taklifni sotuvchiga yuborib boʻlmadi (user=%s): %s", seller_id, exc)

    if delivered:
        await message.answer(
            "✅ <b>Taklifingiz eʼlon egasiga yuborildi!</b>\n\n"
            f"🆔 Taklif raqami: <b>#{offer_id}</b>\n"
            f"📨 Taklif: <b>{esc(summary)}</b>\n\n"
            "⏳ Javobini kuting. Holatni «📥 Takliflar va bitimlar» boʻlimida "
            "kuzatishingiz mumkin. Xavfsizlik uchun bitimni faqat garant orqali "
            "yakunlang.",
            reply_markup=main_menu_kb(),
        )
    else:
        await message.answer(
            "⚠️ <b>Taklifni yuborib boʻlmadi.</b>\n\n"
            "Ehtimol eʼlon egasi botni bloklagan. Administratorga murojaat qiling — "
            "u sizga yordam beradi.",
            reply_markup=main_menu_kb(),
        )

    await notify_admin(
        bot,
        ("🔄 <b>Almashish taklifi</b>" if trade else "💬 <b>Narx taklifi</b>")
        + "\n\n"
        f"🆔 Eʼlon: #{listing_id} · Taklif: #{offer_id}\n"
        f"👤 Egasi: {esc(seller_name)}\n"
        f"🙋 Xaridor: {esc(buyer_ref)}\n"
        f"{offer_line}\n"
        f"{'✅ Yuborildi' if delivered else '⚠️ Yuborilmadi'}"
    )


@router.message(OfferFSM.waiting_amount)
async def offer_fallback(message: Message) -> None:
    """Summa o'rniga boshqa xabar kelsa."""
    await message.answer(
        "✍️ Iltimos, taklif summasini raqamda yozing (masalan: <code>1200000</code>) "
        "yoki «❌ Bekor qilish» tugmasini bosing.",
        reply_markup=cancel_kb(),
    )
