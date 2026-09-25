"""Xaridor so'rovi anketasi (SearchFSM).

Foydalanuvchi akkaunt sotib olmoqchi yoki almashtirmoqchi bo'lsa,
so'rov to'ldiriladi va moderatsiyaga yuboriladi.
"""

from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

import config
from database import db
from handlers.common import (
    blacklist_warning,
    menu_button_guard,
    notify_admin,
    parse_price,
    send_listing_card,
    user_label,
)
from keyboards import BTN_SEARCH, cancel_kb, main_menu_kb, moderation_kb, search_type_kb
from states import SearchFSM

logger = logging.getLogger(__name__)

router = Router(name="search")

INTRO_TEXT = (
    "🔍 <b>Akkaunt qidirish soʻrovi</b>\n\n"
    "Agar siz akkaunt sotib olmoqchi yoki almashtirmoqchi boʻlsangiz, "
    "soʻrovingizni qoldiring — u moderatsiyadan soʻng kanalga chiqadi.\n\n"
    "Bekor qilish uchun «❌ Bekor qilish» tugmasini bosing."
)

TYPE_ASK = "1️⃣ <b>Siz akkaunt sotib olasizmi yoki almashtirasizmi?</b>"

REQUIREMENTS_ASK = (
    "2️⃣ <b>Qanday akkaunt kerak?</b>\n\n"
    "Masalan: <i>Mythic Glory, kamida 60 skin, 3 collector, email bogʻlanmagan</i>"
)

BUDGET_ASK = (
    "3️⃣ <b>Budjetingiz qancha?</b>\n\n"
    "Summani raqamda yozing (masalan: <code>2000000</code>) "
    "yoki <code>kelishilgan</code> deb yozing."
)

CONTACT_ASK = (
    "4️⃣ <b>Aloqa uchun maʼlumot qoldiring.</b>\n\n"
    "Masalan: <code>@username</code> yoki <code>+998901234567</code>"
)


@router.message(StateFilter(None), F.text == BTN_SEARCH)
async def start_search(message: Message, state: FSMContext) -> None:
    """So'rov anketasini boshlaydi."""
    await state.clear()
    await state.set_state(SearchFSM.search_type)
    await message.answer(INTRO_TEXT, reply_markup=cancel_kb())
    await message.answer(TYPE_ASK, reply_markup=search_type_kb())


@router.callback_query(SearchFSM.search_type, F.data.startswith("stype_"))
async def search_type_cb(callback: CallbackQuery, state: FSMContext) -> None:
    """So'rov turi tanlandi."""
    search_type = "Almashtirish" if (callback.data or "").endswith("swap") else "Sotib olish"
    await state.update_data(search_type=search_type)
    await callback.answer(f"Tanlandi: {search_type}")

    if isinstance(callback.message, Message):
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except TelegramAPIError:
            pass
        await state.set_state(SearchFSM.requirements)
        await callback.message.answer(REQUIREMENTS_ASK)


@router.message(SearchFSM.search_type)
async def search_type_fallback(message: Message) -> None:
    """Turi tanlanmagan bo'lsa, tugmalarni eslatadi."""
    await message.answer(
        "☝️ Iltimos, yuqoridagi tugmalardan birini tanlang.",
        reply_markup=search_type_kb(),
    )


@router.message(SearchFSM.requirements, F.text)
async def search_requirements(message: Message, state: FSMContext) -> None:
    """Talablarni qabul qiladi."""
    if menu_button_guard(message):
        await message.answer("ℹ️ Avval joriy amalni yakunlang yoki «❌ Bekor qilish» tugmasini bosing.")
        return

    text = (message.text or "").strip()
    if len(text) < 5:
        await message.answer(
            "❌ Iltimos, talablaringizni batafsilroq yozing.\n\n"
            "Masalan: <i>Mythic Glory, 60+ skin, 2 collector</i>"
        )
        return

    await state.update_data(requirements=text[:400])
    await state.set_state(SearchFSM.budget)
    await message.answer(BUDGET_ASK)


@router.message(SearchFSM.budget, F.text)
async def search_budget(message: Message, state: FSMContext) -> None:
    """Budjetni qabul qiladi."""
    if menu_button_guard(message):
        await message.answer("ℹ️ Avval joriy amalni yakunlang yoki «❌ Bekor qilish» tugmasini bosing.")
        return

    raw = (message.text or "").strip()
    lowered = raw.lower()

    if any(word in lowered for word in ("kelish", "yoʻq", "yoq", "—", "-", "0")):
        await state.update_data(price_numeric=None, price_display="Kelishilgan")
    else:
        price = parse_price(raw)
        if price is None or price < config.MIN_PRICE:
            await message.answer(
                "❌ Budjetni tushunmadim. Iltimos, raqamda yozing.\n\n"
                "Masalan: <code>2000000</code> yoki <code>kelishilgan</code>"
            )
            return
        await state.update_data(price_numeric=price, price_display=f"{price:,} soʻm".replace(",", " "))

    await state.set_state(SearchFSM.contact)
    await message.answer(CONTACT_ASK)


@router.message(SearchFSM.contact, F.text)
async def search_contact(message: Message, state: FSMContext, bot: Bot) -> None:
    """Aloqa ma'lumotini qabul qilib, so'rovni moderatsiyaga yuboradi."""
    user = message.from_user
    if user is None:
        return

    if menu_button_guard(message):
        await message.answer("ℹ️ Avval joriy amalni yakunlang yoki «❌ Bekor qilish» tugmasini bosing.")
        return

    contact = (message.text or "").strip()
    if len(contact) < 4:
        await message.answer("❌ Aloqa maʼlumoti juda qisqa. Masalan: <code>@username</code>")
        return

    data = await state.get_data()
    search_type = str(data.get("search_type") or "Sotib olish")

    listing_id = await db.create_listing(
        user_id=user.id,
        listing_type="buy",
        rank_info=f"{search_type}: {data.get('requirements') or '—'}",
        skins_info="—",
        price_numeric=data.get("price_numeric"),
        price_display=str(data.get("price_display") or "Kelishilgan"),
        contact=contact[:120],
        description=f"Soʻrov turi: {search_type}",
        is_vip=0,
        photos=[],
        status="pending",
    )

    await state.clear()

    listing = await db.get_listing(listing_id)
    if listing is None:
        await message.answer(
            "⚠️ Texnik xatolik yuz berdi. Iltimos, keyinroq qaytadan urinib koʻring.",
            reply_markup=main_menu_kb(),
        )
        return

    await message.answer(
        "🎉 <b>Soʻrovingiz qabul qilindi!</b>\n\n"
        f"🆔 Raqami: <b>#{listing_id}</b>\n"
        "⏳ Moderatsiyadan soʻng kanalga chiqadi.\n\n"
        "«📋 Mening eʼlonlarim» boʻlimida holatini kuzatishingiz mumkin.",
        reply_markup=main_menu_kb(),
    )

    failed = False
    for admin_id in db.get_admin_ids():
        try:
            await send_listing_card(
                bot,
                admin_id,
                listing,
                markup=moderation_kb(listing_id),
                header="🆕 <b>Yangi xaridor soʻrovi (moderatsiya)</b>",
                seller_label=user_label(user.id, user.username, user.full_name),
            )
        except TelegramAPIError as exc:
            failed = True
            logger.error("Xaridor so'rovini adminga (%s) yuborishda xatolik: %s", admin_id, exc)

    if failed:
        await notify_admin(
            bot,
            f"⚠️ #{listing_id} soʻrovini yuborishda xatolik yuz berdi.",
            markup=moderation_kb(listing_id),
        )

    # Avtomatik firibgarlik tekshiruvi (aloqa/username qora ro'yxatda bo'lsa)
    warning = await blacklist_warning(user.id, user.username, contact)
    if warning:
        await notify_admin(
            bot,
            f"🚨 <b>Soʻrov #{listing_id} — shubhali foydalanuvchi!</b>\n\n"
            f"{warning}\n\n"
            "Iltimos, soʻrovni chiqarishdan oldin tekshirib koʻring.",
            markup=moderation_kb(listing_id),
        )
