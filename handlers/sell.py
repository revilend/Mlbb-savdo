"""Akkaunt sotish anketasi (SellFSM)."""

from __future__ import annotations

import logging
from typing import Optional

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from database import db
from handlers.common import (
    blacklist_warning,
    default_header,
    esc,
    format_price,
    menu_button_guard,
    notify_admin,
    parse_price,
    send_listing_card,
    user_label,
)
from handlers.moderation import ai_moderate_listing
from keyboards import (
    BTN_DONE,
    BTN_SELL,
    RANKS,
    cancel_kb,
    main_menu_kb,
    moderation_kb,
    photos_kb,
    rank_kb,
    sell_mode_kb,
    skip_kb,
    vip_kb,
)
from settings import settings
from states import SellFSM

logger = logging.getLogger(__name__)

router = Router(name="sell")

INTRO_TEXT = (
    "💰 <b>Akkaunt sotish anketasi</b>\n\n"
    "Bir necha savolga javob bering — eʼloningiz moderator tekshiruvidan soʻng "
    "kanalga chiqadi.\n\n"
    "Bekor qilish uchun «❌ Bekor qilish» tugmasini bosing."
)

MODE_ASK = (
    "🤝 <b>Avval qanday eʼlon joylashni xohlaysiz?</b>\n\n"
    "💰 <b>Sotish</b> — akkauntni pulga sotasiz.\n"
    "🔄 <b>Almashish (Barter)</b> — akkauntingizni boshqa akkauntga almashtirasiz."
)

TRADE_ASK = (
    "3️⃣ <b>Qanday akkauntga alishmoqchisiz?</b>\n\n"
    "Masalan: <i>Ling Collector yoki KOF boʻlsa alishaman</i>\n"
    "Yoki: <i>Mythic Glory + 100kof akkaunt kerak</i>"
)

RANK_ASK = (
    "1️⃣ <b>Akkauntingiz ranki qanday?</b>\n\n"
    "Quyidagilardan birini tanlang yoki rank nomini yozib yuboring."
)

SKINS_ASK = (
    "2️⃣ <b>Skinlar va qahramonlar haqida maʼlumot bering.</b>\n\n"
    "Masalan: <i>45 ta skin, 8 collector, 2 legend, 112 qahramon</i>\n"
    "Yoki: <i>Mythic Glory, 120kof, 3 legend skin</i>"
)

PRICE_ASK = (
    "3️⃣ <b>Qancha narxga sotyapsiz?</b>\n\n"
    "Summani faqat raqamda yozing (masalan: <code>1500000</code>, "
    "<code>1 500 000</code> yoki <code>1.5mln</code>)."
)

VIP_ASK = "4️⃣ <b>Eʼloningizni VIP qilib chiqarishni xohlaysizmi?</b>\n\nVIP eʼlonlar roʻyxatda yuqorida turadi."

CONTACT_ASK = (
    "5️⃣ <b>Aloqa uchun maʼlumot qoldiring.</b>\n\n"
    "Masalan: <code>@username</code>, <code>+998901234567</code> "
    "yoki <code>https://t.me/username</code>"
)

def description_ask() -> str:
    """Izoh so'rovi (chegara bot ichidan sozlanadi)."""
    return (
        "6️⃣ <b>Qoʻshimcha izoh yozing.</b>\n\n"
        "Masalan: <i>Email bogʻlangan, akkaunt 2 yildan beri meniki, "
        "barcha hujjatlar bor.</i>\n\n"
        f"Izoh {settings.get('MAX_DESCRIPTION_LENGTH')} belgidan oshmasin."
    )


def photos_text() -> str:
    """Rasmlar so'rovi (chegara bot ichidan sozlanadi)."""
    return (
        "7️⃣ <b>Akkaunt rasmlarini yuboring.</b>\n\n"
        f"1 tadan {settings.get('MAX_PHOTOS')} tagacha rasm qabul qilinadi.\n"
        "Tayyor boʻlgach «✅ Tayyor» tugmasini bosing."
    )


async def _ask(message: Message, text: str, markup=None) -> None:
    """Yordamchi: savolni yuborish."""
    await message.answer(text, reply_markup=markup, disable_web_page_preview=True)


async def ask_skins(message: Message, state: FSMContext) -> None:
    """Skinlar bosqichiga o'tadi."""
    await state.set_state(SellFSM.skins)
    await _ask(message, SKINS_ASK)


async def ask_photos(message: Message, state: FSMContext) -> None:
    """Rasmlar bosqichiga o'tadi."""
    await state.set_state(SellFSM.photos)
    await _ask(message, photos_text(), markup=photos_kb())


# ---------------------------------------------------------------------------
# 1. Rank
# ---------------------------------------------------------------------------
@router.message(StateFilter(None), F.text == BTN_SELL)
async def start_sell(message: Message, state: FSMContext) -> None:
    """Sotish anketasini boshlaydi: avval rejim (sotish/almashish) tanlanadi."""
    await state.clear()
    await state.set_state(SellFSM.mode)
    await state.update_data(photos=[], listing_mode="sell", trade_wanted=None)
    await _ask(message, INTRO_TEXT, markup=cancel_kb())
    await _ask(message, MODE_ASK, markup=sell_mode_kb())


@router.callback_query(SellFSM.mode, F.data.in_(["mode_sell", "mode_trade"]))
async def sell_mode_cb(callback: CallbackQuery, state: FSMContext) -> None:
    """Rejim tanlandi: «💰 Sotish» yoki «🔄 Almashish (Barter)»."""
    mode = "trade" if (callback.data or "") == "mode_trade" else "sell"
    await state.update_data(listing_mode=mode)
    await callback.answer(
        "🔄 Almashish rejimi" if mode == "trade" else "💰 Sotish rejimi"
    )

    if isinstance(callback.message, Message):
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except TelegramAPIError:
            pass
        await state.set_state(SellFSM.rank)
        await _ask(callback.message, RANK_ASK, markup=rank_kb("srank"))


@router.callback_query(SellFSM.rank, F.data.startswith("srank_"))
async def sell_rank_cb(callback: CallbackQuery, state: FSMContext) -> None:
    """Rank inline tugma orqali tanlandi."""
    value = (callback.data or "").split("_", 1)[-1]

    if value == "custom":
        await callback.answer()
        if isinstance(callback.message, Message):
            try:
                await callback.message.edit_reply_markup(reply_markup=None)
                await callback.message.edit_text(
                    "✍️ Rank nomini yozib yuboring.\n\nMasalan: <i>Mythic Glory</i>"
                )
            except TelegramAPIError:
                pass
        return

    if not value.isdigit() or int(value) >= len(RANKS):
        await callback.answer("❌ Notoʻgʻri tanlov. Iltimos, qaytadan urinib koʻring.", show_alert=True)
        return

    rank = RANKS[int(value)]
    await state.update_data(rank_info=rank)
    await callback.answer(f"Tanlandi: {rank}")

    if isinstance(callback.message, Message):
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except TelegramAPIError:
            pass
        await ask_skins(callback.message, state)


@router.message(SellFSM.rank, F.text)
async def sell_rank_text(message: Message, state: FSMContext) -> None:
    """Rank matn orqali kiritildi."""
    if menu_button_guard(message):
        await message.answer("ℹ️ Avval joriy amalni yakunlang yoki «❌ Bekor qilish» tugmasini bosing.")
        return

    rank = (message.text or "").strip()
    if len(rank) < 2:
        await message.answer("❌ Rank juda qisqa. Iltimos, toʻliqroq yozing.")
        return

    await state.update_data(rank_info=rank[:80])
    await ask_skins(message, state)


# ---------------------------------------------------------------------------
# 2. Skinlar
# ---------------------------------------------------------------------------
@router.message(SellFSM.skins, F.text)
async def sell_skins(message: Message, state: FSMContext) -> None:
    """Skinlar ma'lumoti."""
    if menu_button_guard(message):
        await message.answer("ℹ️ Avval joriy amalni yakunlang yoki «❌ Bekor qilish» tugmasini bosing.")
        return

    text = (message.text or "").strip()
    if len(text) < 3:
        await message.answer(
            "❌ Iltimos, skinlar haqida batafsilroq yozing.\n\n"
            "Masalan: <i>45 ta skin, 8 collector, 2 legend</i>"
        )
        return

    await state.update_data(skins_info=text[:200])

    data = await state.get_data()
    if data.get("listing_mode") == "trade":
        await state.set_state(SellFSM.trade_wanted)
        await message.answer(TRADE_ASK)
        return

    await state.set_state(SellFSM.price)
    await message.answer(PRICE_ASK)


# ---------------------------------------------------------------------------
# 3b. Almashish talabi (barter)
# ---------------------------------------------------------------------------
@router.message(SellFSM.trade_wanted, F.text)
async def sell_trade_wanted(message: Message, state: FSMContext) -> None:
    """Barter rejimida qanday akkaunt kerakligini qabul qiladi."""
    if menu_button_guard(message):
        await message.answer("ℹ️ Avval joriy amalni yakunlang yoki «❌ Bekor qilish» tugmasini bosing.")
        return

    wanted = (message.text or "").strip()
    if len(wanted) < 3:
        await message.answer(
            "❌ Iltimos, talabni batafsilroq yozing.\n\n"
            "Masalan: <i>Ling Collector yoki KOF boʻlsa alishaman</i>"
        )
        return

    await state.update_data(trade_wanted=wanted[:200], price_numeric=None, price_display="")
    await state.set_state(SellFSM.is_vip)
    credits = await db.get_free_vip(message.from_user.id) if message.from_user else 0
    await message.answer(VIP_ASK, reply_markup=vip_kb("vip", credits))


# ---------------------------------------------------------------------------
# 3. Narx
# ---------------------------------------------------------------------------
@router.message(SellFSM.price, F.text)
async def sell_price(message: Message, state: FSMContext) -> None:
    """Narxni qabul qiladi va tekshiradi."""
    if menu_button_guard(message):
        await message.answer("ℹ️ Avval joriy amalni yakunlang yoki «❌ Bekor qilish» tugmasini bosing.")
        return

    price = parse_price(message.text)
    if price is None:
        await message.answer(
            "❌ Narxni tushunmadim. Iltimos, faqat raqam bilan yozing.\n\n"
            "Masalan: <code>1500000</code> yoki <code>1 500 000</code>"
        )
        return

    if price < int(settings.get("MIN_PRICE")):
        await message.answer(
            f"⚠️ Narx juda past koʻrinadi (kamida {format_price(int(settings.get('MIN_PRICE')))}).\n"
            "Iltimos, narxni qaytadan kiriting."
        )
        return

    if price > int(settings.get("MAX_PRICE")):
        await message.answer(
            "⚠️ Narx juda katta koʻrinadi. Iltimos, summani qaytadan tekshirib kiriting."
        )
        return

    await state.update_data(price_numeric=price, price_display=format_price(price))
    await state.set_state(SellFSM.is_vip)
    credits = await db.get_free_vip(message.from_user.id) if message.from_user else 0
    await message.answer(VIP_ASK, reply_markup=vip_kb("vip", credits))


# ---------------------------------------------------------------------------
# 4. VIP
# ---------------------------------------------------------------------------
@router.callback_query(SellFSM.is_vip, F.data.startswith("vip_"))
async def sell_vip(callback: CallbackQuery, state: FSMContext) -> None:
    """VIP tanlovi (bepul kredit bilan ham)."""
    suffix = (callback.data or "").split("_", 1)[-1]

    if suffix == "free":
        consumed = await db.consume_free_vip(callback.from_user.id)
        is_vip = 1 if consumed else 0
        remaining = await db.get_free_vip(callback.from_user.id)
        await callback.answer(
            f"🎁 Bepul VIP ishlatildi (qoldi: {remaining})"
            if consumed
            else "⚠️ Bepul VIP topilmadi",
            show_alert=not consumed,
        )
    else:
        is_vip = 1 if suffix == "yes" else 0
        await callback.answer("💎 VIP yoqildi" if is_vip else "🙂 Yaxshi")

    await state.update_data(is_vip=is_vip)

    if isinstance(callback.message, Message):
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except TelegramAPIError:
            pass
        await state.set_state(SellFSM.contact)
        await callback.message.answer(CONTACT_ASK)


# ---------------------------------------------------------------------------
# 5. Aloqa
# ---------------------------------------------------------------------------
@router.message(SellFSM.contact, F.text)
async def sell_contact(message: Message, state: FSMContext) -> None:
    """Aloqa ma'lumotlari."""
    if menu_button_guard(message):
        await message.answer("ℹ️ Avval joriy amalni yakunlang yoki «❌ Bekor qilish» tugmasini bosing.")
        return

    contact = (message.text or "").strip()
    if len(contact) < 4:
        await message.answer("❌ Aloqa maʼlumoti juda qisqa. Masalan: <code>@username</code>")
        return

    await state.update_data(contact=contact[:120])
    await state.set_state(SellFSM.description)
    await message.answer(description_ask(), reply_markup=skip_kb("desc_skip"))


# ---------------------------------------------------------------------------
# 6. Izoh
# ---------------------------------------------------------------------------
@router.callback_query(SellFSM.description, F.data == "desc_skip")
async def sell_description_skip(callback: CallbackQuery, state: FSMContext) -> None:
    """Izohni o'tkazib yuborish."""
    await state.update_data(description="—")
    await callback.answer("Oʻtkazib yuborildi")

    if isinstance(callback.message, Message):
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except TelegramAPIError:
            pass
        await ask_photos(callback.message, state)


@router.message(SellFSM.description, F.text)
async def sell_description(message: Message, state: FSMContext) -> None:
    """Qo'shimcha izoh."""
    if menu_button_guard(message):
        await message.answer("ℹ️ Avval joriy amalni yakunlang yoki «❌ Bekor qilish» tugmasini bosing.")
        return

    limit = int(settings.get("MAX_DESCRIPTION_LENGTH"))
    text = (message.text or "").strip()
    if len(text) > limit:
        text = text[:limit]
        await message.answer(f"ℹ️ Izoh {limit} belgigacha qisqartirildi.")

    await state.update_data(description=text or "—")
    await ask_photos(message, state)


# ---------------------------------------------------------------------------
# 7. Rasmlar
# ---------------------------------------------------------------------------
@router.message(SellFSM.photos, F.photo)
async def sell_photo(message: Message, state: FSMContext) -> None:
    """Rasm qabul qiladi."""
    data = await state.get_data()
    photos: list[str] = list(data.get("photos") or [])

    limit = int(settings.get("MAX_PHOTOS"))
    if len(photos) >= limit:
        await message.answer(
            f"⚠️ Maksimal {limit} ta rasm qabul qilinadi.\n"
            "«✅ Tayyor» tugmasini bosing."
        )
        return

    if message.photo:
        photos.append(message.photo[-1].file_id)
    await state.update_data(photos=photos)

    await message.answer(
        f"✅ Rasm qabul qilindi ({len(photos)}/{limit}).\n"
        "Yana rasm yuboring yoki «✅ Tayyor» tugmasini bosing."
    )


@router.message(SellFSM.photos, F.text == BTN_DONE)
async def sell_finish(message: Message, state: FSMContext, bot: Bot) -> None:
    """Anketani yakunlaydi va adminga moderatsiyaga yuboradi."""
    user = message.from_user
    if user is None:
        return

    data = await state.get_data()
    photos: list[str] = list(data.get("photos") or [])

    if not photos:
        await message.answer(
            "⚠️ Kamida 1 ta rasm yuklashingiz kerak.\n\n"
            "Rasm yuboring yoki «❌ Bekor qilish» tugmasini bosing."
        )
        return

    mode = "trade" if data.get("listing_mode") == "trade" else "sell"

    listing_id = await db.create_listing(
        user_id=user.id,
        listing_type="sell",
        listing_mode=mode,
        trade_wanted=str(data.get("trade_wanted") or "") or None,
        rank_info=str(data.get("rank_info") or "—"),
        skins_info=str(data.get("skins_info") or "—"),
        price_numeric=None if mode == "trade" else data.get("price_numeric"),
        price_display="" if mode == "trade" else str(data.get("price_display") or "Kelishilgan"),
        contact=str(data.get("contact") or "—"),
        description=str(data.get("description") or "—"),
        is_vip=int(data.get("is_vip") or 0),
        photos=photos,
        status="pending",
    )

    await state.clear()

    listing = await db.get_listing(listing_id)
    if listing is None:
        await message.answer(
            "⚠️ Texnik xatolik yuz berdi. Iltimos, birozdan soʻng qaytadan urinib koʻring.",
            reply_markup=main_menu_kb(),
        )
        return

    await message.answer(
        "🎉 <b>Rahmat! Eʼloningiz qabul qilindi.</b>\n\n"
        f"🆔 Eʼlon raqami: <b>#{listing_id}</b>\n"
        + (
            "🔄 Rejim: almashish (barter)\n"
            if mode == "trade"
            else "💰 Rejim: sotish\n"
        )
        + "⏳ Holat: moderator tekshiruvi kutilmoqda.\n\n"
        "Tekshiruvdan soʻng eʼloningiz kanalga chiqadi va sizga xabar beramiz.\n"
        "«📋 Mening eʼlonlarim» boʻlimida holatini kuzatib borishingiz mumkin.",
        reply_markup=main_menu_kb(),
    )

    seller = user_label(user.id, user.username, user.full_name)
    header = f"🆕 <b>Yangi eʼlon (moderatsiya)</b>\n{default_header(listing)}"
    last_error: Optional[str] = None
    for admin_id in db.get_admin_ids():
        try:
            await send_listing_card(
                bot,
                admin_id,
                listing,
                markup=moderation_kb(listing_id),
                header=header,
                seller_label=seller,
            )
        except TelegramAPIError as exc:
            last_error = str(exc)
            logger.error("Yangi eʼlon adminga (%s) yuborilmadi: %s", admin_id, exc)

    if last_error:
        await notify_admin(
            bot,
            f"⚠️ #{listing_id} eʼlonini yuborishda xatolik: {esc(last_error)}",
            markup=moderation_kb(listing_id),
        )

    # Avtomatik firibgarlik tekshiruvi: aloqa/username qora ro'yxatda bo'lsa
    warning = await blacklist_warning(
        user.id, user.username, str(data.get("contact") or "")
    )
    if warning:
        await notify_admin(
            bot,
            f"🚨 <b>Eʼlon #{listing_id} — shubhali sotuvchi!</b>\n\n"
            f"{warning}\n\n"
            "Iltimos, eʼlonni chiqarishdan oldin tekshirib koʻring.",
            markup=moderation_kb(listing_id),
        )

    # AI moderatsiyasi (yoqilgan bo'lsa). Natija adminlarga alohida xabar bo'lib boradi;
    # AI mustaqil qaror qabul qilgan bo'lsa, tugmalar ko'rsatilmaydi.
    outcome = await ai_moderate_listing(bot, listing_id)
    if outcome.text:
        await notify_admin(
            bot,
            outcome.text,
            markup=None if outcome.decided else moderation_kb(listing_id),
        )


@router.message(SellFSM.photos)
async def sell_photos_fallback(message: Message, state: FSMContext) -> None:
    """Rasmlar bosqichida noto'g'ri xabar."""
    await message.answer(
        "📷 Iltimos, akkaunt rasmini yuboring yoki «✅ Tayyor» tugmasini bosing.",
        reply_markup=photos_kb(),
    )
