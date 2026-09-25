"""Botga baho berish bo'limi.

Foydalanuvchi botning o'ziga 1–10 baho qo'yadi va ixtiyoriy izoh yozadi.
Bir foydalanuvchi bir marta baho qo'yadi — keyingisi oldingini yangilaydi.

O'rtacha baho bot statistikasida ko'rinadi, past baho (5 va undan past)
bo'lsa admin darhol xabardor qilinadi.
"""

from __future__ import annotations

import contextlib
import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.filters import StateFilter
from aiogram.types import CallbackQuery, Message

from database import db
from handlers.common import esc, menu_button_guard, notify_admin, user_label
from keyboards import BTN_BOT_RATING, BTN_CANCEL, bot_rating_kb, main_menu_kb, skip_kb
from states import BotRatingFSM

logger = logging.getLogger(__name__)

router = Router(name="bot_rating")

#: Botga quyiladigan eng past baho — admin ogohlantiriladi
LOW_SCORE = 5

ASK = (
    "⭐️ <b>Botga baho bering</b>\n\n"
    "Bot sizga qanchalik yordam berdi? 1 dan 10 gacha baho tanlang 👇\n\n"
    "1 — umuman yoqdi · 10 — juda zoʻr"
)

COMMENT_ASK = (
    "📝 <b>Izoh (ixtiyoriy)</b>\n\n"
    "Nima yaxshi yoki nima yaxshi emas edi? Boʻsh qoldirish ham mumkin."
)

THANKS = (
    "✅ <b>Rahmat!</b> Bahoyiz qabul qilindi.\n\n"
    "💡 Fikringiz bizga botni yaxshilashga yordam beradi."
)


def format_score(score: float, count: int) -> str:
    """Bot reytingini matn ko'rinishida chiqaradi."""
    if not count:
        return "hali baho yoʻq"
    return f"{float(score):.1f}/10 ({count} ta baho)"


@router.message(StateFilter(None), F.text == BTN_BOT_RATING)
async def bot_rating_start(message: Message, state: FSMContext) -> None:
    """Menyudagi «⭐️ Botga baho» tugmasi."""
    existing = await db.get_user_bot_rating(message.from_user.id)
    if existing:
        await message.answer(
            "⭐️ <b>Botga baho</b>\n\n"
            f"Sizning oldingi bahoyiz: <b>{esc(stars_bar(int(existing['rating'])))} "
            f"{int(existing['rating'])}/10</b>\n\n"
            "Boshqacha baho bermoqchimisiz? Quyidagi tugmalardan tanlang 👇",
            reply_markup=bot_rating_kb(),
        )
        await state.clear()
        await state.set_state(BotRatingFSM.rating)
        return

    await state.clear()
    await state.set_state(BotRatingFSM.rating)
    await message.answer(ASK, reply_markup=bot_rating_kb())


@router.callback_query(BotRatingFSM.rating, F.data.startswith("botr_"))
async def bot_rating_pick(callback: CallbackQuery, state: FSMContext) -> None:
    """Baho tanlandi — izoh bosqichiga o'tadi."""
    raw = (callback.data or "").split("_", 1)[-1]
    if not raw.isdigit() or not 1 <= int(raw) <= 10:
        await callback.answer("❌ Notoʻgʻri baho.", show_alert=True)
        return

    await state.update_data(bot_rating=int(raw))
    await state.set_state(BotRatingFSM.comment)
    await callback.answer(f"{raw}/10 qabul qilindi")

    if isinstance(callback.message, Message):
        with contextlib.suppress(TelegramAPIError):
            await callback.message.edit_reply_markup(reply_markup=None)
        await callback.message.answer(
            COMMENT_ASK, reply_markup=skip_kb("botr_skip", "⏭ Izohsiz yuborish")
        )


@router.callback_query(BotRatingFSM.comment, F.data == "botr_skip")
async def bot_rating_skip(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    """Izohni o'tkazib yuboradi."""
    await callback.answer("Yuborilmoqda…")
    if isinstance(callback.message, Message):
        await _save(callback.message, state, bot, comment="")


@router.message(BotRatingFSM.comment, F.text)
async def bot_rating_comment(message: Message, state: FSMContext, bot: Bot) -> None:
    """Izohni qabul qiladi."""
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

    await _save(message, state, bot, comment=text[:300])


@router.message(BotRatingFSM.comment)
async def bot_rating_fallback(message: Message) -> None:
    """Izoh o'rniga boshqa turdagi xabar kelsa."""
    await message.answer(
        "📝 Iltimos, izohni matn ko'rinishida yozing yoki «⏭ Izohsiz yuborish» "
        "tugmasini bosing.",
        reply_markup=skip_kb("botr_skip", "⏭ Izohsiz yuborish"),
    )


async def _save(message: Message, state: FSMContext, bot: Bot, comment: str) -> None:
    """Bahoni saqlaydi, natijani ko'rsatadi va past bahoda adminni ogohlantiradi."""
    user = message.from_user
    if user is None:
        return

    data = await state.get_data()
    await state.clear()
    score = int(data.get("bot_rating") or 0)
    if not score:
        await message.answer(
            "⚠️ Baho tanlanmagan. Qayta urinib koʻring.",
            reply_markup=main_menu_kb(),
        )
        return

    previous = await db.get_user_bot_rating(user.id)
    await db.set_bot_rating(user.id, score, comment)
    avg, count = await db.get_bot_rating()

    await message.answer(
        f"{THANKS}\n\n"
        f"⭐️ Bahoyiz: <b>{stars_bar(score)} {score}/10</b>\n"
        f"📊 Botning o'rtacha bahosi: <b>{esc(format_score(avg, count))}</b>"
        + ("\nℹ️ Bahoyiz yangilandi." if previous else ""),
        reply_markup=main_menu_kb(),
    )

    if score <= LOW_SCORE:
        author = user_label(user.id, user.username, user.full_name)
        await notify_admin(
            bot,
            "⭐️ <b>Botga past baho berildi</b>\n\n"
            f"👤 Foydalanuvchi: {esc(author)} (<code>{user.id}</code>)\n"
            f"💬 Baho: <b>{score}/10</b>\n"
            + (f"📝 Izoh: {esc(comment)}\n" if comment else "")
            + f"📊 O'rtacha: {esc(format_score(avg, count))}\n\n"
            "Bot ishlashida muammo bo'lgan bo'lishi mumkin.",
        )


def stars_bar(score: int, maximum: int = 10) -> str:
    """1–10 bahoni ixcham ko'rinishdagi chiziqchaga aylantiradi."""
    value = max(0, min(int(maximum), int(score)))
    return "▰" * value + "▱" * (int(maximum) - value)


__all__ = ["format_score", "router", "stars_bar"]
