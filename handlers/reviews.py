"""Sotuvchilar reytingi va sharhlar bo'limi.

Xaridor e'lon kartochkasidagi «⭐️ Sharh qoldirish» tugmasini bosadi,
1–5 baho tanlaydi va izoh yozadi (ixtiyoriy). Bir foydalanuvchi bitta
sotuvchi haqida faqat bitta sharh qoldira oladi (keyingisi yangilanadi).
"""

from __future__ import annotations

import contextlib
import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from database import db
from handlers.common import (
    esc,
    format_rating,
    is_trade,
    menu_button_guard,
    notify_admin,
    stars,
    user_label,
)
from keyboards import (
    BTN_CANCEL,
    main_menu_kb,
    review_rating_kb,
    single_button_kb,
    skip_kb,
)
from states import ReviewFSM

logger = logging.getLogger(__name__)

router = Router(name="reviews")

RATING_ASK = (
    "⭐️ <b>Sotuvchi haqida sharh</b>\n\n"
    "👤 Sotuvchi: <b>{seller}</b>\n"
    "🆔 Eʼlon: <b>#{listing_id}</b>\n\n"
    "Bitim qanday oʻtdi? Bahoni tanlang 👇"
)

COMMENT_ASK = (
    "📝 <b>Izoh yozing (ixtiyoriy)</b>\n\n"
    "Masalan: <i>Tez javob berdi, akkaunt aytilganidek chiqdi.</i>\n\n"
    "Izohni oʻtkazib yuborish uchun quyidagi tugmani bosing."
)


async def _seller_name(seller_id: int) -> str:
    """Sotuvchi uchun o'qishga qulay nom."""
    user = await db.get_user(seller_id)
    return user_label(seller_id, (user or {}).get("username"), (user or {}).get("full_name"))


@router.callback_query(F.data.startswith("rvw_"))
async def review_start(callback: CallbackQuery, state: FSMContext) -> None:
    """«⭐️ Sharh qoldirish» tugmasi bosildi."""
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

    seller_id = int(listing["user_id"])
    if seller_id == user.id:
        await callback.answer("🙂 Oʻz eʼloningizga sharh qoldira olmaysiz.", show_alert=True)
        return

    if is_trade(listing) or listing.get("listing_type") == "buy":
        await callback.answer(
            "ℹ️ Sharh faqat sotuvchi eʼlonlariga qoldiriladi.", show_alert=True
        )
        return

    await state.clear()
    await state.set_state(ReviewFSM.rating)
    await state.update_data(review_listing_id=listing_id, review_seller_id=seller_id)
    await callback.answer("⭐️ Bahoni tanlang.")
    if isinstance(callback.message, Message):
        await callback.message.answer(
            RATING_ASK.format(listing_id=listing_id, seller=esc(await _seller_name(seller_id))),
            reply_markup=review_rating_kb(),
        )


@router.callback_query(ReviewFSM.rating, F.data.startswith("rvwr_"))
async def review_rating(callback: CallbackQuery, state: FSMContext) -> None:
    """Baho tanlandi — izoh bosqichiga o'tadi."""
    raw = (callback.data or "").split("_", 1)[-1]
    if not raw.isdigit() or not 1 <= int(raw) <= 5:
        await callback.answer("❌ Notoʻgʻri baho.", show_alert=True)
        return

    await state.update_data(review_rating=int(raw))
    await state.set_state(ReviewFSM.comment)
    await callback.answer(f"{raw}⭐️ qabul qilindi")

    if isinstance(callback.message, Message):
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except TelegramAPIError:
            pass
        await callback.message.answer(
            COMMENT_ASK, reply_markup=skip_kb("rev_skip", "⏭ Izohsiz yuborish")
        )


@router.callback_query(ReviewFSM.comment, F.data == "rev_skip")
async def review_skip(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    """Izohni o'tkazib yuborib sharhni saqlaydi."""
    await callback.answer("Yuborilmoqda…")
    if isinstance(callback.message, Message):
        await _save_review(callback.message, state, bot, comment="")


@router.message(ReviewFSM.comment, F.text)
async def review_comment(message: Message, state: FSMContext, bot: Bot) -> None:
    """Izohni qabul qilib sharhni saqlaydi."""
    if menu_button_guard(message):
        await message.answer(
            "ℹ️ Avval joriy amalni yakunlang yoki «❌ Bekor qilish» tugmasini bosing."
        )
        return

    text = (message.text or "").strip()
    if text == BTN_CANCEL:
        await state.clear()
        await message.answer("✅ Amal bekor qilindi.", reply_markup=main_menu_kb())
        return

    await _save_review(message, state, bot, comment=text[:300])


@router.message(ReviewFSM.comment)
async def review_fallback(message: Message) -> None:
    """Izoh o'rniga boshqa turdagi xabar kelsa."""
    await message.answer(
        "📝 Iltimos, izohni matn koʻrinishida yozing yoki «⏭ Izohsiz yuborish» "
        "tugmasini bosing.",
        reply_markup=skip_kb("rev_skip", "⏭ Izohsiz yuborish"),
    )


async def _save_review(
    message: Message,
    state: FSMContext,
    bot: Bot,
    comment: str = "",
) -> None:
    """Sharhni saqlaydi, sotuvchini xabardor qiladi va reytingni ko'rsatadi."""
    user = message.from_user
    if user is None:
        return

    data = await state.get_data()
    await state.clear()

    listing_id = int(data.get("review_listing_id") or 0)
    seller_id = int(data.get("review_seller_id") or 0)
    rating = int(data.get("review_rating") or 0)

    if not seller_id or not rating:
        await message.answer(
            "⚠️ Sharh maʼlumotlari yoʻqolib qoldi. Qaytadan urinib koʻring.",
            reply_markup=main_menu_kb(),
        )
        return

    previous = await db.has_reviewed(user.id, seller_id)
    await db.add_review(
        listing_id or None,
        seller_id,
        user.id,
        rating,
        comment if comment and comment != "—" else "",
    )

    score, count = await db.get_seller_rating(seller_id)
    verb = "yangilandi" if previous else "saqlandi"
    await message.answer(
        "✅ <b>Sharhingiz uchun rahmat!</b>\n\n"
        f"👤 Sotuvchi: <b>{esc(await _seller_name(seller_id))}</b>\n"
        f"⭐️ Sizning bahoyiz: {stars(rating)} ({rating}/5)\n"
        f"📊 Umumiy reyting: <b>{esc(format_rating(score, count))}</b>\n\n"
        f"ℹ️ Sharh {verb}.",
        reply_markup=main_menu_kb(),
    )
    with contextlib.suppress(TelegramAPIError):
        await message.answer(
            "📖 Sotuvchi haqidagi barcha sharhlarni koʻrish:",
            reply_markup=single_button_kb("📖 Sharhlarni koʻrish", f"rvws_{seller_id}"),
        )

    reviewer = user_label(user.id, user.username, user.full_name)
    try:
        await bot.send_message(
            seller_id,
            "⭐️ <b>Siz haqingizda yangi sharh qoldirildi!</b>\n\n"
            f"👤 {esc(reviewer)}: {stars(rating)} ({rating}/5)\n"
            + (f"📝 {esc(comment)}\n" if comment else "")
            + f"📊 Joriy reytingingiz: <b>{esc(format_rating(score, count))}</b>",
            disable_web_page_preview=True,
        )
    except TelegramAPIError as exc:
        logger.warning("Sharh xabari sotuvchiga yuborilmadi (user=%s): %s", seller_id, exc)

    if rating <= 2:
        await notify_admin(
            bot,
            "⚠️ <b>Past baho olindi!</b>\n\n"
            f"👤 Sotuvchi: {esc(await _seller_name(seller_id))} "
            f"(<code>{seller_id}</code>)\n"
            f"🙋 Baholagan: {esc(reviewer)}\n"
            f"⭐️ Baho: {stars(rating)} ({rating}/5)\n"
            + (f"📝 {esc(comment)}" if comment else ""),
        )


@router.callback_query(F.data.startswith("rvws_"))
async def review_list(callback: CallbackQuery) -> None:
    """Sotuvchi haqidagi oxirgi sharhlarni ko'rsatadi."""
    raw_id = (callback.data or "").split("_", 1)[-1]
    if not raw_id.lstrip("-").isdigit():
        await callback.answer("❌ Notoʻgʻri soʻrov.", show_alert=True)
        return

    seller_id = int(raw_id)
    score, count = await db.get_seller_rating(seller_id)
    reviews = await db.get_seller_reviews(seller_id, limit=5)

    if not reviews:
        text = f"📖 <b>{esc(await _seller_name(seller_id))}</b> hali sharhga ega emas."
    else:
        lines = [
            "📖 <b>Sharhlar</b>\n",
            f"👤 {esc(await _seller_name(seller_id))}",
            f"📊 Reyting: <b>{esc(format_rating(score, count))}</b>\n",
        ]
        for item in reviews:
            reviewer = await db.get_user(int(item["reviewer_id"]))
            label = user_label(
                int(item["reviewer_id"]),
                (reviewer or {}).get("username"),
                (reviewer or {}).get("full_name"),
            )
            lines.append(
                f"{stars(int(item['rating']))} <b>{item['rating']}/5</b> — {esc(label)}"
            )
            if item.get("comment"):
                lines.append(f"   <i>{esc(item['comment'])}</i>")
            lines.append(f"   📅 {esc(str(item.get('created_at') or '')[:10])}")
        text = "\n".join(lines)

    await callback.answer()
    if isinstance(callback.message, Message):
        try:
            await callback.message.answer(text, disable_web_page_preview=True)
        except TelegramAPIError as exc:
            logger.debug("Sharhlar roʻyxati yuborilmadi: %s", exc)


__all__ = ["router"]
