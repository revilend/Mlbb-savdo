"""Firibgarni tekshirish (ScamCheckFSM)."""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from database import db
from handlers.common import esc, menu_button_guard
from keyboards import BTN_SCAM, cancel_kb, garant_kb, main_menu_kb, private_chat_kb
from states import ScamCheckFSM

logger = logging.getLogger(__name__)

router = Router(name="scam_check")

ASK_TEXT = (
    "🛡️ <b>Firibgarni tekshirish</b>\n\n"
    "Tekshirmoqchi boʻlgan foydalanuvchining <b>username</b> ini yoki "
    "<b>Telegram ID</b> sini yuboring.\n\n"
    "Masalan: <code>@username</code> yoki <code>123456789</code>"
)

SAFETY_TIPS = (
    "⚠️ <b>Ehtiyot choralari</b>\n"
    "• Toʻlovni faqat garant orqali amalga oshiring.\n"
    "• Akkauntni toʻlovdan oldin toʻliq tekshiring.\n"
    "• «Arzon narx» va shoshirish — eng koʻp uchraydigan firibgarlik belgisi.\n"
    "• Skrinshot va chat tarixini saqlab qoʻying."
)


@router.message(StateFilter(None), F.text == BTN_SCAM)
async def scam_start(message: Message, state: FSMContext) -> None:
    """Tekshirish jarayonini boshlaydi."""
    if message.chat.type != "private":
        await message.answer(
            "🛡️ Firibgarni tekshirish botning shaxsiy chatida ochiladi 👇",
            reply_markup=private_chat_kb("scam", "🔒 Shaxsiy chatda ochish"),
            disable_web_page_preview=True,
        )
        return
    await state.clear()
    await state.set_state(ScamCheckFSM.waiting_query)
    await message.answer(ASK_TEXT, reply_markup=cancel_kb())


@router.message(ScamCheckFSM.waiting_query, F.text)
async def scam_check(message: Message, state: FSMContext) -> None:
    """Qora ro'yxatdan tekshiradi."""
    if menu_button_guard(message):
        await message.answer("ℹ️ Avval joriy amalni yakunlang yoki «❌ Bekor qilish» tugmasini bosing.")
        return

    query = (message.text or "").strip()
    if len(query) < 3:
        await message.answer(
            "❌ Iltimos, username yoki ID ni toʻliq yozing.\n\nMasalan: <code>@username</code>"
        )
        return

    clean = db.normalize_identifier(query)
    record = await db.is_blacklisted(clean)
    if record is None and clean != query:
        record = await db.is_blacklisted(query)

    # Foydalanuvchi botga ro'yxatdan o'tgan bo'lsa, uning ID sini ham topamiz
    known_user = await db.get_user_by_username(clean)
    known_line = ""
    if known_user:
        known_line = (
            f"\n\n🙋 Bu foydalanuvchi botda roʻyxatdan oʻtgan.\n"
            f"🆔 ID: <code>{known_user['user_id']}</code>"
        )

    await state.clear()

    if record:
        await message.answer(
            "🚨 <b>DIQQAT! Bu foydalanuvchi qora roʻyxatda!</b>\n\n"
            f"👤 Identifikator: <code>{esc(record.get('identifier'))}</code>\n"
            f"📝 Sababi: {esc(record.get('reason') or 'koʻrsatilmagan')}\n"
            f"📅 Qoʻshilgan: {esc(str(record.get('added_at') or '—')[:19])}"
            f"{known_line}\n\n"
            "❗️ <b>Bu foydalanuvchi bilan hech qanday bitim qilmang!</b>\n\n"
            f"{SAFETY_TIPS}",
            reply_markup=garant_kb(),
        )
        return

    await message.answer(
        "✅ <b>Maʼlumot topilmadi</b>\n\n"
        f"🔍 Qidiruv: <code>{esc(clean)}</code>\n\n"
        "Bu foydalanuvchi boʻyicha bizda shikoyat yoʻq. "
        "Ammo bu 100% xavfsiz degani emas — qora roʻyxat faqat "
        "bizga yuborilgan shikoyatlar asosida toʻldiriladi.\n\n"
        f"{SAFETY_TIPS}\n\n"
        "🤝 Bitimni garant orqali yakunlashni tavsiya qilamiz.",
        reply_markup=garant_kb(),
    )


@router.message(ScamCheckFSM.waiting_query)
async def scam_fallback(message: Message) -> None:
    """Matn bo'lmagan xabar."""
    await message.answer(
        "✍️ Iltimos, username yoki Telegram ID ni matn koʻrinishida yuboring.",
        reply_markup=cancel_kb(),
    )
