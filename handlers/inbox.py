"""«📥 Takliflar va bitimlar» bo'limi.

Bu yerda foydalanuvchi:
* sotuvchi sifatida kelgan takliflarni koʻrib, qabul/rad etadi yoki javob yozadi;
* xaridor sifatida yuborgan takliflari holatini koʻradi;
* ishtirok etgan bitimlarining holatini kuzatadi.
"""

from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from database import db
from handlers.common import (
    esc,
    format_price,
    menu_button_guard,
    notify_admin,
    user_label,
)
from keyboards import (
    BTN_CANCEL,
    BTN_INBOX,
    cancel_kb,
    main_menu_kb,
    offer_response_kb,
)
from states import OfferFSM

logger = logging.getLogger(__name__)

router = Router(name="inbox")

#: Taklif holatlari uchun yorliqlar
OFFER_STATUS = {
    "pending": "⏳ Javob kutilmoqda",
    "accepted": "✅ Qabul qilindi",
    "rejected": "❌ Rad etildi",
}

#: Bitim holatlari uchun yorliqlar
DEAL_STATUS = {
    "new": "🆕 Yangi soʻrov",
    "garant": "🛡️ Garant jarayonida",
    "done": "✅ Yakunlandi",
    "cancelled": "❌ Bekor qilindi",
}

REPLY_PROMPT = (
    "💬 <b>Taklifga javob yozing</b>\n\n"
    "Xaridor bu xabarni shaxsiy chatida oladi. Masalan:\n"
    "<i>1500000 boʻlsa kelishamiz.</i>"
)


async def _offer_line(offer: dict, as_seller: bool) -> str:
    """Bitta taklif uchun qisqa matn qatori."""
    listing = await db.get_listing(int(offer["listing_id"]))
    listing_id = int(offer["listing_id"])
    rank = esc((listing or {}).get("rank_info") or "—")

    if offer.get("is_trade"):
        summary = esc(str(offer.get("offer_text") or "—"))
    else:
        summary = esc(format_price(offer.get("amount")))

    other_id = int(offer["buyer_id"] if as_seller else offer["seller_id"])
    other = await db.get_user(other_id)
    who = user_label(other_id, (other or {}).get("username"), (other or {}).get("full_name"))
    role = "🙋 Xaridor" if as_seller else "👤 Sotuvchi"

    return (
        f"🆔 Taklif #{offer['id']} · Eʼlon #{listing_id}\n"
        f"🏆 Rank: {rank}\n"
        f"💰 Taklif: <b>{summary}</b>\n"
        f"{role}: {esc(who)}\n"
        f"📌 Holat: {OFFER_STATUS.get(str(offer.get('status')), '❔')}"
    )


@router.message(StateFilter(None), F.text == BTN_INBOX)
async def show_inbox(message: Message, bot: Bot) -> None:
    """Kelgan takliflar, yuborilgan takliflar va bitimlar ro'yxati."""
    user = message.from_user
    if user is None:
        return

    received = await db.get_user_offers(user.id, side="seller", limit=5)
    sent = await db.get_user_offers(user.id, side="buyer", limit=5)
    deals = await db.get_user_deals(user.id, limit=5)
    pending = await db.count_pending_offers(user.id)

    header = (
        "📥 <b>Takliflar va bitimlar</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"⏳ Javob kutayotgan takliflar: <b>{pending}</b>\n"
        f"🤝 Bitimlar: <b>{len(deals)}</b>"
    )
    await message.answer(header)

    if not received and not sent and not deals:
        await message.answer(
            "ℹ️ Hozircha taklif yoki bitim yoʻq.\n\n"
            "Eʼlon kartochkasidagi <b>«💬 Narx taklif qilish»</b> yoki "
            "<b>«🛡️ Admin orqali sotib olish»</b> tugmalari orqali boshlashingiz mumkin."
        )
        return

    # --- Kelgan takliflar (sotuvchi) --------------------------------------
    for offer in received:
        text = "📨 <b>Kelgan taklif</b>\n\n" + await _offer_line(offer, as_seller=True)
        markup = offer_response_kb(int(offer["id"])) if offer.get("status") == "pending" else None
        try:
            await bot.send_message(
                message.chat.id, text, reply_markup=markup, disable_web_page_preview=True
            )
        except TelegramAPIError as exc:
            logger.warning("Taklif #%s koʻrsatilmadi: %s", offer.get("id"), exc)

    # --- Yuborilgan takliflar (xaridor) -----------------------------------
    for offer in sent:
        text = "📤 <b>Yuborilgan taklif</b>\n\n" + await _offer_line(offer, as_seller=False)
        try:
            await bot.send_message(message.chat.id, text, disable_web_page_preview=True)
        except TelegramAPIError as exc:
            logger.warning("Yuborilgan taklif #%s koʻrsatilmadi: %s", offer.get("id"), exc)

    # --- Bitimlar ---------------------------------------------------------
    if deals:
        lines = ["🤝 <b>Bitimlarim</b>\n"]
        for deal in deals:
            other_id = int(deal["seller_id"]) if int(deal["buyer_id"]) == user.id else int(deal["buyer_id"])
            other = await db.get_user(other_id)
            who = user_label(other_id, (other or {}).get("username"), (other or {}).get("full_name"))
            role = "Sotuvchi" if int(deal["seller_id"]) == user.id else "Xaridor"
            amount = format_price(deal.get("amount")) if deal.get("amount") else "Kelishilgan"
            lines.append(
                f"🆔 Bitim #{deal['id']} · Eʼlon #{deal['listing_id']}\n"
                f"💰 {esc(amount)}\n"
                f"👤 {role}: {esc(who)}\n"
                f"📌 {DEAL_STATUS.get(str(deal.get('status')), '❔')}\n"
            )
        lines.append(
            "ℹ️ Bitimni faqat <b>garant</b> orqali yakunlang. Xavfsizlik qoidalari "
            "«❓ Qoʻllanma» boʻlimida."
        )
        try:
            await message.answer("\n".join(lines), disable_web_page_preview=True)
        except TelegramAPIError as exc:
            logger.warning("Bitimlar roʻyxati yuborilmadi: %s", exc)


@router.callback_query(F.data.startswith("off_ok_"))
async def offer_accept(callback: CallbackQuery, bot: Bot) -> None:
    """Sotuvchi taklifni qabul qiladi."""
    offer_id = _offer_id(callback)
    if offer_id is None:
        return

    offer = await db.get_offer(offer_id)
    if offer is None:
        await callback.answer("❌ Taklif topilmadi.", show_alert=True)
        return
    if int(offer["seller_id"]) != callback.from_user.id:
        await callback.answer("⛔️ Bu taklif sizga tegishli emas.", show_alert=True)
        return
    if offer.get("status") != "pending":
        await callback.answer("ℹ️ Bu taklifga allaqachon javob berilgan.", show_alert=True)
        return

    await db.update_offer_status(offer_id, "accepted")
    await callback.answer("✅ Taklif qabul qilindi.")

    summary = _offer_summary(offer)
    if isinstance(callback.message, Message):
        await callback.message.answer(
            f"✅ <b>Taklif #{offer_id} qabul qilindi.</b>\n\n"
            f"💰 {esc(summary)}\n\n"
            "Endi xaridor bilan bogʻlaning va bitimni <b>garant</b> orqali yakunlang."
        )
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except TelegramAPIError:
            pass

    await _notify_buyer(
        bot,
        offer,
        "✅ <b>Taklifingiz qabul qilindi!</b>",
        summary=summary,
    )


@router.callback_query(F.data.startswith("off_no_"))
async def offer_reject(callback: CallbackQuery, bot: Bot) -> None:
    """Sotuvchi taklifni rad etadi."""
    offer_id = _offer_id(callback)
    if offer_id is None:
        return

    offer = await db.get_offer(offer_id)
    if offer is None:
        await callback.answer("❌ Taklif topilmadi.", show_alert=True)
        return
    if int(offer["seller_id"]) != callback.from_user.id:
        await callback.answer("⛔️ Bu taklif sizga tegishli emas.", show_alert=True)
        return
    if offer.get("status") != "pending":
        await callback.answer("ℹ️ Bu taklifga allaqachon javob berilgan.", show_alert=True)
        return

    await db.update_offer_status(offer_id, "rejected")
    await callback.answer("❌ Taklif rad etildi.")

    if isinstance(callback.message, Message):
        await callback.message.answer(f"❌ <b>Taklif #{offer_id} rad etildi.</b>")
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except TelegramAPIError:
            pass

    await _notify_buyer(
        bot,
        offer,
        "❌ <b>Afsuski, taklifingiz rad etildi.</b>",
        summary=_offer_summary(offer),
    )


@router.callback_query(F.data.startswith("off_msg_"))
async def offer_reply_start(callback: CallbackQuery, state: FSMContext) -> None:
    """Sotuvchi xaridorga javob yozishni boshlaydi."""
    offer_id = _offer_id(callback)
    if offer_id is None:
        return

    offer = await db.get_offer(offer_id)
    if offer is None:
        await callback.answer("❌ Taklif topilmadi.", show_alert=True)
        return
    if int(offer["seller_id"]) != callback.from_user.id:
        await callback.answer("⛔️ Bu taklif sizga tegishli emas.", show_alert=True)
        return

    await state.clear()
    await state.set_state(OfferFSM.waiting_reply)
    await state.update_data(reply_offer_id=offer_id)
    await callback.answer("💬 Javobingizni yozing.")
    if isinstance(callback.message, Message):
        await callback.message.answer(
            f"{REPLY_PROMPT}\n\n🆔 Taklif: <b>#{offer_id}</b>", reply_markup=cancel_kb()
        )


@router.message(OfferFSM.waiting_reply, F.text)
async def offer_reply_send(message: Message, state: FSMContext, bot: Bot) -> None:
    """Javob matnini xaridorga yetkazadi."""
    user = message.from_user
    if user is None:
        return

    text = (message.text or "").strip()
    if text == BTN_CANCEL:
        await state.clear()
        await message.answer("✅ Amal bekor qilindi.", reply_markup=main_menu_kb())
        return

    if menu_button_guard(message):
        await message.answer(
            "ℹ️ Avval joriy amalni yakunlang yoki «❌ Bekor qilish» tugmasini bosing."
        )
        return

    if len(text) < 2:
        await message.answer("❌ Javob juda qisqa. Iltimos, toʻliqroq yozing.")
        return

    data = await state.get_data()
    await state.clear()

    offer_id = int(data.get("reply_offer_id") or 0)
    offer = await db.get_offer(offer_id) if offer_id else None
    if offer is None:
        await message.answer(
            "⚠️ Taklif topilmadi. «📥 Takliflar va bitimlar» boʻlimidan qaytadan urinib koʻring.",
            reply_markup=main_menu_kb(),
        )
        return

    if int(offer["seller_id"]) != user.id:
        await message.answer("⛔️ Bu taklif sizga tegishli emas.", reply_markup=main_menu_kb())
        return

    delivered = await _notify_buyer(
        bot,
        offer,
        "💬 <b>Sotuvchidan javob keldi!</b>",
        summary=_offer_summary(offer),
        extra=esc(text[:300]),
    )

    await message.answer(
        "✅ <b>Javobingiz yuborildi.</b>" if delivered else "⚠️ Javobni yuborib boʻlmadi.",
        reply_markup=main_menu_kb(),
    )

    await notify_admin(
        bot,
        "💬 <b>Taklifga javob</b>\n\n"
        f"🆔 Taklif: #{offer_id}\n"
        f"👤 Sotuvchi: <code>{user.id}</code>\n"
        f"📝 {esc(text[:200])}",
    )


@router.message(OfferFSM.waiting_reply)
async def offer_reply_fallback(message: Message) -> None:
    """Javob o'rniga boshqa xabar kelsa."""
    await message.answer(
        "💬 Iltimos, javobni matn koʻrinishida yozing yoki «❌ Bekor qilish» "
        "tugmasini bosing.",
        reply_markup=cancel_kb(),
    )


# ---------------------------------------------------------------------------
# Yordamchilar
# ---------------------------------------------------------------------------
def _offer_id(callback: CallbackQuery) -> int | None:
    """Callback ma'lumotidan taklif ID sini ajratadi."""
    raw = (callback.data or "").split("_", 2)[-1]
    return int(raw) if raw.isdigit() else None


def _offer_summary(offer: dict) -> str:
    """Taklif mazmuni (summa yoki barter matni)."""
    if offer.get("is_trade"):
        return str(offer.get("offer_text") or "—")
    return format_price(offer.get("amount"))


async def _notify_buyer(
    bot: Bot,
    offer: dict,
    title: str,
    summary: str,
    extra: str = "",
) -> bool:
    """Xaridorga taklif holati haqida xabar yuboradi."""
    buyer_id = int(offer["buyer_id"])
    listing_id = int(offer["listing_id"])

    text = (
        f"{title}\n\n"
        f"🆔 Eʼlon: <b>#{listing_id}</b>\n"
        f"💰 Taklif: <b>{esc(summary)}</b>\n"
    )
    if extra:
        text += f"\n{extra}\n"
    text += "\n🛡️ Bitimni faqat garant orqali yakunlang."

    try:
        await bot.send_message(buyer_id, text, disable_web_page_preview=True)
        return True
    except TelegramAPIError as exc:
        logger.warning("Taklif xabari xaridorga yuborilmadi (user=%s): %s", buyer_id, exc)
        return False


__all__ = ["router"]
