"""Akkauntni admin yordamida baholash.

Foydalanuvchi skrinshotlarni yuboradi, bot ularni asosiy admin'ga
baholash uchun yuboradi va admin'ning javobini foydalanuvchiga yetkazadi.
"""

from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InputMediaPhoto, Message

import config
from database import db
from handlers.common import esc
from keyboards import (
    BTN_APPRAISAL,
    BTN_DONE,
    appraisal_answer_kb,
    cancel_kb,
    main_menu_kb,
    photos_kb,
)
from states import AdminFSM, AppraisalFSM

logger = logging.getLogger(__name__)

router = Router(name="calculator")

MAX_APPRAISAL_PHOTOS = 5

APPRAISAL_PROMPT = (
    "📸 <b>Akkauntingizni baholatish</b>\n\n"
    "Akkauntingizning asosiy skrinshotlarini (Profil, Kolleksiya va qimmat "
    "skins) yuboring (1 dan 5 tagacha). Tugagach «✅ Tayyor» tugmasini bosing."
)

APPRAISAL_ADMIN_CAPTION = (
    "📊 <b>YANGI AKKAUNT BAHOLASH SOʻROVI</b>\n"
    "👤 Foydalanuvchi: @{username} (ID: {user_id})"
)

APPRAISAL_SENT = (
    "✅ Skrinshotlar adminga yuborildi. Tez orada sizga akkauntingizning "
    "real bozor narxi aytiladi!"
)

APPRAISAL_FAILED = (
    "⚠️ Skrinshotlarni adminga yuborib boʻlmadi. Iltimos, yana urinib koʻring."
)

ADMIN_PRICE_PROMPT = "Ushbu akkaunt uchun narx va izohni yozing:"


def _admin_caption(user: Message) -> str:
    """Admin uchun xavfsiz, matnli soʻrov sarlavhasi."""
    username = user.from_user.username if user.from_user else None
    display_username = username or "username_yoq"
    return APPRAISAL_ADMIN_CAPTION.format(
        username=esc(display_username), user_id=user.from_user.id
    )


async def _send_to_admin(
    bot: Bot,
    user: Message,
    photos: list[str],
) -> None:
    """Skrinshotlarni primary admin'ga baholash uchun yuboradi."""
    admin_id = int(config.ADMIN_ID or 0)
    if not admin_id:
        admins = db.get_admin_ids()
        admin_id = int(admins[0]) if admins else 0
    if not admin_id:
        raise TelegramAPIError("ADMIN_ID sozlanmagan")

    caption = _admin_caption(user)
    markup = appraisal_answer_kb(user.from_user.id)

    if len(photos) == 1:
        await bot.send_photo(
            admin_id,
            photos[0],
            caption=caption,
            reply_markup=markup,
        )
        return

    media = [
        InputMediaPhoto(media=file_id, caption=caption if index == 0 else None)
        for index, file_id in enumerate(photos)
    ]
    await bot.send_media_group(chat_id=admin_id, media=media)
    # Telegram media guruhiga inline tugma biriktirishga ruxsat bermaydi.
    await bot.send_message(
        admin_id,
        "📸 <b>Skrinshotlar tayyor.</b> Quyidagi tugma orqali bahoni yozing:",
        reply_markup=markup,
    )


@router.message(StateFilter(None), F.text == BTN_APPRAISAL)
async def start_appraisal(message: Message, state: FSMContext) -> None:
    """Baholash uchun skrinshotlarni yig'ishni boshlaydi."""
    await state.clear()
    await state.set_state(AppraisalFSM.photos)
    await message.answer(APPRAISAL_PROMPT, reply_markup=photos_kb())


@router.message(AppraisalFSM.photos, F.photo)
async def collect_appraisal_photo(message: Message, state: FSMContext) -> None:
    """Foydalanuvchining skrinshotlarini 1–5 tagacha jamlaydi."""
    data = await state.get_data()
    photos = list(data.get("photos") or [])
    if len(photos) >= MAX_APPRAISAL_PHOTOS:
        await message.answer(
            "📸 maksimal 5 ta skrinshot qabul qilindi. Endi «✅ Tayyor» "
            "tugmasini bosing."
        )
        return

    photo = message.photo[-1] if message.photo else None
    if photo is None or not photo.file_id:
        await message.answer("❌ Skrinshotni Telegram orqali yubiring.")
        return

    photos.append(photo.file_id)
    await state.update_data(photos=photos)
    remaining = MAX_APPRAISAL_PHOTOS - len(photos)
    suffix = (
        f" Yana {remaining} ta skrinshot yuborishingiz mumkin."
        if remaining
        else " Endi «✅ Tayyor» tugmasini bosing."
    )
    await message.answer(f"📸 Skrinshot qabul qilindi ({len(photos)}/5).{suffix}")


@router.message(AppraisalFSM.photos, F.text == BTN_DONE)
async def finish_appraisal(message: Message, state: FSMContext, bot: Bot) -> None:
    """Skrinshotlarni adminga yuboradi va foydalanuvchini kutishga o'tkazadi."""
    data = await state.get_data()
    photos = list(data.get("photos") or [])[:MAX_APPRAISAL_PHOTOS]
    if not photos:
        await message.answer(
            "📸 Avval kamida bitta skrinshot yuboring, keyin «✅ Tayyor» bosing.",
            reply_markup=photos_kb(),
        )
        return

    try:
        await _send_to_admin(bot, message, photos)
    except TelegramAPIError as exc:
        logger.warning("Baholash soʻrovini adminga yuborib boʻlmadi: %s", exc)
        await message.answer(APPRAISAL_FAILED, reply_markup=photos_kb())
        return

    await state.clear()
    await message.answer(APPRAISAL_SENT, reply_markup=main_menu_kb())


@router.message(AppraisalFSM.photos, F.text)
async def appraisal_waiting_photo(message: Message) -> None:
    """Skrinshot bosqichidagi noto'g'ri matnni qayta ishlaydi."""
    await message.answer(
        "📸 Iltimos, skrinshot yuboring. Tugagach «✅ Tayyor» tugmasini bosing.",
        reply_markup=photos_kb(),
    )


@router.callback_query(F.data.startswith("eval_ans_"))
async def admin_valuation_request(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    """Admin baholash javobini kiritish rejimiga o'tadi."""
    if not db.is_admin(callback.from_user.id):
        await callback.answer("⛔️ Bu amal faqat administrator uchun.", show_alert=True)
        return

    raw_target = (callback.data or "").split("_", 2)[-1]
    if not raw_target.isdigit() or int(raw_target) <= 0:
        await callback.answer("❌ Notoʻgʻri foydalanuvchi ID.", show_alert=True)
        return

    target_user_id = int(raw_target)
    await state.clear()
    await state.set_state(AdminFSM.waiting_eval_price)
    await state.update_data(target_user_id=target_user_id)
    await callback.answer("✍️ Bahoni yozing.")

    if isinstance(callback.message, Message):
        await callback.message.answer(
            f"{ADMIN_PRICE_PROMPT}\n\n"
            f"👤 Foydalanuvchi ID: <code>{target_user_id}</code>",
            reply_markup=cancel_kb(),
        )


@router.message(AdminFSM.waiting_eval_price, F.text)
async def send_admin_valuation(
    message: Message,
    state: FSMContext,
    bot: Bot,
) -> None:
    """Admin bahosini foydalanuvchiga yuboradi."""
    if not db.is_admin(message.from_user.id if message.from_user else None):
        return

    admin_text = (message.text or "").strip()
    if not admin_text:
        await message.answer("❌ Narx va izohni yozing.", reply_markup=cancel_kb())
        return

    data = await state.get_data()
    raw_target = data.get("target_user_id")
    try:
        target_user_id = int(raw_target or 0)
    except (TypeError, ValueError):
        target_user_id = 0
    if target_user_id <= 0:
        await state.clear()
        await message.answer("⚠️ Foydalanuvchi topilmadi.", reply_markup=main_menu_kb())
        return

    try:
        await bot.send_message(
            target_user_id,
            "🎯 <b>Akkauntingiz admin tomonidan baholandi!</b>\n\n"
            f"💰 <b>Tavsiya etilgan narx:</b>\n{esc(admin_text)}\n\n"
            "Akkauntni sotish uchun menyudan <b>«💰 Akkaunt sotish»</b> "
            "boʻlimiga kiring!",
        )
    except TelegramAPIError as exc:
        logger.warning("Admin bahosi yuborilmadi (user=%s): %s", target_user_id, exc)
        await state.clear()
        await message.answer("❌ Foydalanuvchiga javob yuborib boʻlmadi.")
        return

    await state.clear()
    await message.answer("✅ Javobingiz foydalanuvchiga yuborildi.")
