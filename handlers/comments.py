"""E'lon kommentlari (bo'lishish).

Xaridor e'lon kartasidagi «💬 Kommentlar» tugmasi orqali savol yozishi
yoki boshqa xaridorlarning fikrini o'qishi mumkin. Kommentlar ochiq
ko'rinadi va e'lon egasi javob bermaydi — maqsad faqat fikr almashish.
"""

from __future__ import annotations

import contextlib
import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from database import db
from handlers.common import esc, menu_button_guard, user_label
from keyboards import BTN_CANCEL, cancel_kb, comment_list_kb, main_menu_kb
from states import CommentFSM

logger = logging.getLogger(__name__)

router = Router(name="comments")

#: Bir kommentning maksimal uzunligi
MAX_LENGTH = 400
#: Bir foydalanuvchi bir e'longa nechta komment yozishi mumkin
MAX_PER_USER = 20

ASK = (
    "✍️ <b>Komment yozing</b>\n\n"
    "Eʼlon #{listing_id} haqida savol yoki fikringizni yozing "
    f"({MAX_LENGTH} belgigacha).\n\n"
    "Bekor qilish uchun «❌ Bekor qilish» tugmasini bosing."
)


async def _listing_title(listing: dict) -> str:
    """E'lon nomi (kartochkada chiqadigan matn)."""
    parts = [str(listing.get("rank_info") or "Akkaunt")]
    if listing.get("skins_info"):
        parts.append(str(listing["skins_info"]))
    return " · ".join(parts)


async def _render(message: Message, listing_id: int) -> None:
    """Kommentlar ro'yxatini chizadi."""
    listing = await db.get_listing(listing_id)
    if listing is None:
        await message.answer("⚠️ Eʼlon topilmadi.", reply_markup=main_menu_kb())
        return

    comments = await db.get_listing_comments(listing_id, limit=20)
    total = await db.count_listing_comments(listing_id)

    if not comments:
        text = (
            "💬 <b>Kommentlar</b>\n\n"
            f"🆔 Eʼlon: <b>#{listing_id}</b>\n"
            f"📌 {esc(await _listing_title(listing))}\n\n"
            "Hali komment yoʻq. Birinchi boʻlib fikringizni yozing!"
        )
    else:
        lines = [
            "💬 <b>Kommentlar</b>\n",
            f"🆔 Eʼlon: <b>#{listing_id}</b>",
            f"📌 {esc(await _listing_title(listing))}",
            f"🔢 Jami: <b>{total}</b>\n",
        ]
        for item in comments:
            author = await db.get_user(int(item["user_id"]))
            label = user_label(
                int(item["user_id"]),
                (author or {}).get("username"),
                (author or {}).get("full_name"),
            )
            lines.append(f"👤 {esc(label)} · {esc(str(item.get('created_at') or '')[:10])}")
            lines.append(f"   {esc(str(item['text']))}\n")
        text = "\n".join(lines)

        if total > len(comments):
            text += f"ℹ️ Koʻrsatilgan: {len(comments)} / {total}"

    try:
        await message.answer(
            text, reply_markup=comment_list_kb(listing_id), disable_web_page_preview=True
        )
    except TelegramAPIError as exc:
        logger.debug("Kommentlar yuborilmadi: %s", exc)


@router.callback_query(F.data.startswith("cmt_w_"))
async def comment_write(callback: CallbackQuery, state: FSMContext) -> None:
    """«✍️ Komment yozish» — matn kutish holatiga o'tadi."""
    raw = (callback.data or "").split("_", 2)[-1]
    if not raw.isdigit():
        await callback.answer("❌ Notoʻgʻri soʻrov.", show_alert=True)
        return

    listing_id = int(raw)
    user = callback.from_user
    if int((await db.get_listing(listing_id) or {}).get("user_id") or 0) == user.id:
        await callback.answer("🙂 Oʻz eʼloningizga komment yozmay olasiz.", show_alert=True)
        return

    mine = [
        item
        for item in await db.get_listing_comments(listing_id, limit=MAX_PER_USER * 10)
        if int(item["user_id"]) == user.id
    ]
    if len(mine) >= MAX_PER_USER:
        await callback.answer(
            f"🚫 Bu eʼlonga koʻpi bilan {MAX_PER_USER} ta komment yozishingiz mumkin.",
            show_alert=True,
        )
        return

    await state.clear()
    await state.set_state(CommentFSM.waiting_text)
    await state.update_data(comment_listing_id=listing_id)
    await callback.answer("✍️ Yozing…")
    if isinstance(callback.message, Message):
        await callback.message.answer(ASK.format(listing_id=listing_id), reply_markup=cancel_kb())


@router.callback_query(F.data.startswith("cmt_"))
async def comment_list(callback: CallbackQuery) -> None:
    """«💬 Kommentlar» — ro'yxatni ko'rsatadi."""
    raw = (callback.data or "").split("_", 1)[-1]
    if not raw.isdigit():
        await callback.answer("❌ Notoʻgʻri soʻrov.", show_alert=True)
        return

    await callback.answer()
    if isinstance(callback.message, Message):
        await _render(callback.message, int(raw))


@router.message(CommentFSM.waiting_text, F.text)
async def comment_save(message: Message, state: FSMContext) -> None:
    """Kommentni saqlaydi."""
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

    if len(text) < 2:
        await message.answer("✍️ Komment juda qisqa. Kamida 2 ta belgi yozing.")
        return

    data = await state.get_data()
    await state.clear()
    listing_id = int(data.get("comment_listing_id") or 0)
    if not listing_id:
        await message.answer("⚠️ Eʼlon topilmadi.", reply_markup=main_menu_kb())
        return

    await db.add_listing_comment(listing_id, message.from_user.id, text[:MAX_LENGTH])
    total = await db.count_listing_comments(listing_id)
    await message.answer(
        f"✅ Kommentingiz qoʻshildi. Eʼlon #{listing_id} boʻyicha jami {total} ta komment.",
        reply_markup=comment_list_kb(listing_id),
    )
    with contextlib.suppress(TelegramAPIError):
        await _render(message, listing_id)


@router.message(CommentFSM.waiting_text)
async def comment_fallback(message: Message) -> None:
    """Matn o'rniga boshqa turdagi xabar kelsa."""
    await message.answer(
        "💬 Iltimos, kommentni matn ko'rinishida yozing yoki «❌ Bekor qilish» "
        "tugmasini bosing.",
        reply_markup=cancel_kb(),
    )


__all__ = ["router"]
