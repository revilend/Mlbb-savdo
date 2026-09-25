"""«🔔 Qidiruv obunasi» bo'limi.

Foydalanuvchi narx oralig'i va ixtiyoriy kalit so'z bo'yicha obuna bo'ladi.
Moderatsiyadan o'tgan yangi e'lon obuna shartlariga mos kelsa, bot
foydalanuvchiga avtomatik xabar yuboradi.
"""

from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from database import db
from handlers.common import esc, menu_button_guard, send_listing_card, seller_label_of
from keyboards import (
    BTN_SAVED_SEARCH,
    listing_action_kb,
    main_menu_kb,
    saved_price_kb,
    saved_search_label,
    saved_searches_kb,
    skip_kb,
)
from states import SavedSearchFSM

logger = logging.getLogger(__name__)

router = Router(name="subscriptions")

#: Narx oraliqi: callback -> (min, max, yorliq)
PRICE_RANGES: dict[str, tuple[int | None, int | None, str]] = {
    "saved_p_100": (None, 100_000, "🟢 100 000 soʻmgacha"),
    "saved_p_400": (100_000, 400_000, "🟡 100 000 – 400 000 soʻm"),
    "saved_p_max": (400_000, None, "🔴 400 000 soʻmdan yuqori"),
    "saved_p_any": (None, None, "❔ Narx muhim emas"),
}

INTRO_TEXT = (
    "🔔 <b>Qidiruv obunasi</b>\n\n"
    "Kerakli shartlarni belgilang — shu shartlarga mos <b>yangi eʼlon</b> "
    "kanalga chiqsa, bot sizga darhol xabar beradi.\n\n"
    "Avval narx oraligʻini tanlang 👇"
)

KEYWORD_ASK = (
    "🏆 <b>Kalit soʻz kiriting (ixtiyoriy)</b>\n\n"
    "Masalan: <i>Mythic Glory</i>, <i>collector</i>, <i>KOF</i>\n\n"
    "Eʼlon tavsifida shu soʻz uchrasa, xabar yuboriladi. "
    "Kalit soʻzsiz ham obuna boʻlishingiz mumkin."
)


async def _show_section(message: Message, user_id: int) -> None:
    """Obunalar ro'yxatini ko'rsatadi."""
    searches = await db.get_saved_searches(user_id)
    if not searches:
        text = (
            "🔔 <b>Qidiruv obunasi</b>\n\n"
            "Sizda hali obuna yoʻq.\n"
            "Kerakli narx va rankni belgilang — mos eʼlon chiqsa, bot xabar beradi."
        )
    else:
        lines = ["🔔 <b>Saqlangan qidiruvlar</b>\n"]
        for index, search in enumerate(searches, start=1):
            lines.append(f"{index}. {esc(saved_search_label(search))}")
        lines.append("\n🗑 Oʻchirish uchun tegishli tugmani bosing.")
        text = "\n".join(lines)

    await message.answer(text, reply_markup=saved_searches_kb(searches))


@router.message(StateFilter(None), F.text == BTN_SAVED_SEARCH)
async def show_saved_searches(message: Message, state: FSMContext) -> None:
    """«🔔 Qidiruv obunasi» bo'limini ochadi."""
    user = message.from_user
    if user is None:
        return
    await state.clear()
    await _show_section(message, user.id)


@router.callback_query(F.data == "saved_new")
async def saved_new(callback: CallbackQuery, state: FSMContext) -> None:
    """Yangi obuna yaratishni boshlaydi."""
    await state.clear()
    await callback.answer()
    if isinstance(callback.message, Message):
        await callback.message.answer(INTRO_TEXT, reply_markup=saved_price_kb())


@router.callback_query(F.data.in_(set(PRICE_RANGES.keys())))
async def saved_price(callback: CallbackQuery, state: FSMContext) -> None:
    """Narx oralig'i tanlandi — kalit so'z bosqichiga o'tadi."""
    low, high, label = PRICE_RANGES[callback.data or "saved_p_any"]
    await state.clear()
    await state.set_state(SavedSearchFSM.waiting_keyword)
    await state.update_data(saved_min=low, saved_max=high, saved_label=label)
    await callback.answer(f"{label}")

    if isinstance(callback.message, Message):
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except TelegramAPIError:
            pass
        await callback.message.answer(
            KEYWORD_ASK, reply_markup=skip_kb("saved_skip", "⏭ Kalit soʻzsiz")
        )


@router.callback_query(SavedSearchFSM.waiting_keyword, F.data == "saved_skip")
async def saved_skip(callback: CallbackQuery, state: FSMContext) -> None:
    """Kalit so'zsiz obuna yaratadi."""
    await callback.answer("Saqlanmoqda…")
    if isinstance(callback.message, Message):
        await _save_search(callback.message, state, keyword="")


@router.message(SavedSearchFSM.waiting_keyword, F.text)
async def saved_keyword(message: Message, state: FSMContext) -> None:
    """Kalit so'zni qabul qilib obunani saqlaydi."""
    if menu_button_guard(message):
        await message.answer(
            "ℹ️ Avval joriy amalni yakunlang yoki «❌ Bekor qilish» tugmasini bosing."
        )
        return

    keyword = (message.text or "").strip()
    await _save_search(message, state, keyword=keyword[:120])


@router.message(SavedSearchFSM.waiting_keyword)
async def saved_fallback(message: Message) -> None:
    """Kalit so'z o'rniga boshqa xabar kelsa."""
    await message.answer(
        "🏆 Iltimos, kalit soʻzni matn koʻrinishida yozing yoki "
        "«⏭ Kalit soʻzsiz» tugmasini bosing.",
        reply_markup=skip_kb("saved_skip", "⏭ Kalit soʻzsiz"),
    )


@router.callback_query(F.data.startswith("saved_del_"))
async def saved_delete(callback: CallbackQuery) -> None:
    """Obunani o'chiradi."""
    raw_id = (callback.data or "").split("_", 2)[-1]
    if not raw_id.isdigit():
        await callback.answer("❌ Notoʻgʻri soʻrov.", show_alert=True)
        return

    removed = await db.remove_saved_search(int(raw_id), callback.from_user.id)
    await callback.answer(
        "🗑 Obuna oʻchirildi." if removed else "ℹ️ Obuna topilmadi."
    )
    if isinstance(callback.message, Message):
        await _show_section(callback.message, callback.from_user.id)


async def _save_search(message: Message, state: FSMContext, keyword: str = "") -> None:
    """Obunani bazaga yozadi va foydalanuvchiga tasdiq ko'rsatadi."""
    user = message.from_user
    if user is None:
        return

    data = await state.get_data()
    await state.clear()

    low = data.get("saved_min")
    high = data.get("saved_max")
    label = str(data.get("saved_label") or "")

    search_id = await db.add_saved_search(user.id, low, high, keyword)
    if not search_id:
        await message.answer(
            "⚠️ Obunani saqlab boʻlmadi. Keyinroq urinib koʻring.",
            reply_markup=main_menu_kb(),
        )
        return

    search = {
        "min_price": low,
        "max_price": high,
        "keyword": keyword,
    }
    await message.answer(
        "✅ <b>Qidiruv obunasi saqlandi!</b>\n\n"
        f"📌 Shartlar: <b>{esc(saved_search_label(search))}</b>\n"
        f"💰 Narx: {esc(label or 'har qanday')}\n"
        f"🏆 Kalit soʻz: {esc(keyword or 'yoʻq')}\n\n"
        "Mos eʼlon kanalga chiqishi bilan sizga xabar beramiz.\n"
        "«🔔 Qidiruv obunasi» boʻlimida obunalarni boshqarishingiz mumkin.",
        reply_markup=main_menu_kb(),
    )


async def notify_subscribers(bot: Bot, listing: dict) -> int:
    """Yangi e'lon obunalarga mos kelsa egalariga xabar yuboradi.

    Qaytaradi: xabar yuborilgan foydalanuvchilar soni.
    """
    matches = await db.match_saved_searches(listing)
    if not matches:
        return 0

    sent = 0
    notified: set[int] = set()
    for search in matches:
        user_id = int(search["user_id"])
        if user_id in notified:
            continue
        notified.add(user_id)
        try:
            await bot.send_message(
                user_id,
                "🔔 <b>Sizga mos yangi eʼlon chiqdi!</b>\n\n"
                f"📌 Obuna: <b>{esc(saved_search_label(search))}</b>",
                disable_web_page_preview=True,
            )
            await send_listing_card(
                bot,
                user_id,
                listing,
                markup=listing_action_kb(listing),
                seller_label=await seller_label_of(listing),
            )
            sent += 1
        except TelegramAPIError as exc:
            logger.warning("Obuna xabari yuborilmadi (user=%s): %s", user_id, exc)
    return sent


__all__ = ["router", "notify_subscribers"]
