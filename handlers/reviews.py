"""Sotuvchilar reytingi va sharhlar bo'limi.

Xaridor e'lonni **sotib olgandan keyin** (e'lon «sotildi» deb belgilangan
va u shu e'lonni xaridor sifatida olgan bo'lsa) «⭐️ Sharh qoldirish»
tugmasini bosadi, 1–5 baho tanlaydi va izoh yozadi (ixtiyoriy). Bir
foydalanuvchi bitta sotuvchi haqida faqat bitta sharh qoldira oladi
(keyingisi yangilanadi).

Barcha sharhlar «📖 Sharhlar» menyu tugmasi orqali ochiq ko'rinadi.
"""

from __future__ import annotations

import contextlib
import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.filters import StateFilter
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

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
    BTN_REVIEWS,
    main_menu_kb,
    review_rating_kb,
    single_button_kb,
    skip_kb,
)
from states import ReviewFSM

logger = logging.getLogger(__name__)

router = Router(name="reviews")

#: Bitta sahifada ko'rsatiladigan sharhlar soni
PAGE_SIZE = 5

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

    if listing.get("status") != "sold":
        await callback.answer(
            "⏳ Sharh faqat savdo tugagandan keyin qoldiriladi.", show_alert=True
        )
        return

    deal = await db.get_buyer_deal(listing_id, user.id)
    if deal is None or deal.get("status") == "cancelled":
        await callback.answer(
            "🙅 Bu eʼlonni siz xaridor sifatida olmagan boʻlishingiz kerak.",
            show_alert=True,
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


async def _review_lines(item: dict) -> list[str]:
    """Bitta sharhni ko'rsatuvchi qatorlar (bitta sharh uchun)."""
    reviewer = await db.get_user(int(item["reviewer_id"]))
    label = user_label(
        int(item["reviewer_id"]),
        (reviewer or {}).get("username"),
        (reviewer or {}).get("full_name"),
    )
    lines = [f"{stars(int(item['rating']))} <b>{item['rating']}/5</b> — {esc(label)}"]
    if item.get("comment"):
        lines.append(f"   <i>{esc(item['comment'])}</i>")
    lines.append(f"   📅 {esc(str(item.get('created_at') or '')[:10])}")
    return lines


@router.callback_query(F.data.startswith("rvws_"))
async def review_list(callback: CallbackQuery) -> None:
    """Sotuvchi haqidagi oxirgi sharhlarni ko'rsatadi."""
    raw_id = (callback.data or "").split("_", 1)[-1]
    if not raw_id.lstrip("-").isdigit():
        await callback.answer("❌ Notoʻgʻri soʻrov.", show_alert=True)
        return

    seller_id = int(raw_id)
    score, count = await db.get_seller_rating(seller_id)
    reviews = await db.get_seller_reviews(seller_id, limit=PAGE_SIZE)

    if not reviews:
        text = f"📖 <b>{esc(await _seller_name(seller_id))}</b> hali sharhga ega emas."
    else:
        lines = [
            "📖 <b>Sharhlar</b>\n",
            f"👤 {esc(await _seller_name(seller_id))}",
            f"📊 Reyting: <b>{esc(format_rating(score, count))}</b>\n",
        ]
        for item in reviews:
            lines.extend(await _review_lines(item))
        text = "\n".join(lines)

    await callback.answer()
    if isinstance(callback.message, Message):
        try:
            await callback.message.answer(text, disable_web_page_preview=True)
        except TelegramAPIError as exc:
            logger.debug("Sharhlar roʻyxati yuborilmadi: %s", exc)


# ---------------------------------------------------------------------------
# Sotuvchi profili
# ---------------------------------------------------------------------------
@router.callback_query(F.data.startswith("sp_"))
async def seller_profile(callback: CallbackQuery) -> None:
    """Sotuvchining reytingi va savdo statistikasi."""
    raw_id = (callback.data or "").split("_", 1)[-1]
    if not raw_id.lstrip("-").isdigit():
        await callback.answer("❌ Notoʻgʻri soʻrov.", show_alert=True)
        return

    seller_id = int(raw_id)
    stats = await db.get_seller_stats(seller_id)
    name = esc(await _seller_name(seller_id))
    verified = await db.is_verified(seller_id)

    if stats["rating"] > 0 and stats["reviews"] >= 3:
        verdict = "🟢 <b>Ishonchli sotuvchi</b>"
    elif stats["reviews"]:
        verdict = "🟡 <b>Yangi sotuvchi</b>"
    else:
        verdict = "⚪️ <b>Hali reyting yoʻq</b>"

    lines = [
        f"👤 <b>{name}</b>",
        f"🆔 Telegram ID: <code>{seller_id}</code>",
        verdict,
    ]
    if verified:
        lines.append("✅ <b>Tasdiqlangan sotuvchi</b> — admin tomonidan tekshirilgan.")
    lines += [
        "",
        f"⭐️ <b>Reyting: {esc(format_rating(stats['rating'], stats['reviews']))}</b>",
        f"✅ Sotilgan eʼlonlar: <b>{stats['sold']}</b>",
        f"🟢 Faol eʼlonlar: <b>{stats['active']}</b>",
    ]
    if stats["free_vip"]:
        lines.append(f"💎 Bepul VIP eʼlonlar: <b>{stats['free_vip']}</b>")
    if stats["joined_at"]:
        lines.append(f"📅 Botga qo'shilgan: {esc(str(stats['joined_at'])[:10])}")

    recent = await db.get_seller_reviews(seller_id, limit=PAGE_SIZE)
    if recent:
        lines.append("\n<b>Oxirgi sharhlar:</b>")
        for item in recent:
            lines.extend(await _review_lines(item))

    await callback.answer()
    if isinstance(callback.message, Message):
        try:
            await callback.message.answer(
                "\n".join(lines),
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="📖 Barcha sharhlar",
                                callback_data=f"rvws_{seller_id}",
                            )
                        ]
                    ]
                ),
                disable_web_page_preview=True,
            )
        except TelegramAPIError as exc:
            logger.debug("Sotuvchi profili yuborilmadi: %s", exc)


# ---------------------------------------------------------------------------
# Barcha sharhlar (menyu tugmasi)
# ---------------------------------------------------------------------------
async def _send_reviews_page(message: Message, page: int = 0) -> None:
    """Sharhlar ro'yxatining `page`-sahifasini yuboradi."""
    items = await db.get_recent_reviews(limit=PAGE_SIZE + 1, offset=page * PAGE_SIZE)
    has_next = len(items) > PAGE_SIZE
    items = items[:PAGE_SIZE]

    if not items and page == 0:
        await message.answer(
            "📖 <b>Sharhlar</b>\n\n"
            "Hali hech kim sharh qoldirmagan. Savdo tugagandan keyin xaridorlar "
            "sotuvchiga baho qoʻyadi — siz ham birinchilardan boʻling.",
            reply_markup=main_menu_kb(),
        )
        return

    lines = ["📖 <b>Oxirgi sharhlar</b>\n"]
    for item in items:
        lines.extend(await _review_lines(item))
        lines.append("")

    markup = main_menu_kb()
    if has_next:
        lines.append("➡️ Yana sharhlar uchun quyidagi tugmani bosing.")
        markup = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="➡️ Yana", callback_data=f"rwall_{page + 1}")]
            ]
        )

    try:
        await message.answer(
            "\n".join(lines).strip(),
            reply_markup=markup,
            disable_web_page_preview=True,
        )
    except TelegramAPIError as exc:
        logger.debug("Sharhlar sahifasi yuborilmadi: %s", exc)


@router.message(StateFilter(None), F.text == BTN_REVIEWS)
async def reviews_menu(message: Message) -> None:
    """Menyudagi «📖 Sharhlar» tugmasi — oxirgi sharhlar ro'yxatini ochadi."""
    await _send_reviews_page(message, page=0)


@router.callback_query(F.data.startswith("rwall_"))
async def reviews_page(callback: CallbackQuery) -> None:
    """«➡️ Yana» tugmasi — keyingi sahifani ko'rsatadi."""
    raw_page = (callback.data or "").split("_", 1)[-1]
    page = int(raw_page) if raw_page.isdigit() else 0
    await callback.answer()
    if isinstance(callback.message, Message):
        await _send_reviews_page(callback.message, page=page)


__all__ = ["router"]
