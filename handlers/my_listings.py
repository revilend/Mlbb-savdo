"""Mening e'lonlarim: holatni ko'rish, sotildi deb belgilash va UP qilish."""

from __future__ import annotations

import contextlib
import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

import config
from database import db
from handlers.common import (
    edit_listing_card,
    esc,
    format_price,
    format_rating,
    get_channel_id,
    is_bump_available,
    is_trade,
    menu_button_guard,
    parse_price,
    safe_delete,
    seller_card_rating,
    seller_label_of,
    send_listing_card,
    status_label,
)
from keyboards import (
    BTN_MY_LISTINGS,
    cancel_kb,
    edit_listing_kb,
    listing_action_kb,
    main_menu_kb,
    my_listing_kb,
)
from settings import settings
from states import EditFSM, PriceDropFSM

logger = logging.getLogger(__name__)

router = Router(name="my_listings")

MAX_SHOWN = 10


@router.message(StateFilter(None), F.text == BTN_MY_LISTINGS)
async def show_my_listings(message: Message, bot: Bot) -> None:
    """Foydalanuvchining barcha e'lonlarini ko'rsatadi."""
    listings = await db.get_user_listings(message.from_user.id)
    if not listings:
        await message.answer(
            "📋 <b>Sizda hali eʼlonlar yoʻq.</b>\n\n"
            "«💰 Akkaunt sotish» boʻlimi orqali birinchi eʼloningizni joylang — "
            "moderatsiyadan soʻng u kanalga chiqadi."
        )
        return

    stats = await db.get_seller_stats(message.from_user.id)
    await message.answer(
        f"📋 <b>Mening eʼlonlarim</b> — jami {len(listings)} ta.\n\n"
        f"⭐️ <b>Sizning reytingiz: {esc(format_rating(stats['rating'], stats['reviews']))}</b>\n"
        f"✅ Sotilgan: <b>{stats['sold']}</b> · 🟢 Faol: <b>{stats['active']}</b>",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="👤 Reytingim va statistikam",
                        callback_data=f"sp_{message.from_user.id}",
                    )
                ]
            ]
        ),
    )

    for listing in listings[:MAX_SHOWN]:
        status = str(listing.get("status") or "pending")
        header = f"{status_label(status)}"
        markup = my_listing_kb(listing) if status in ("active", "expired") else None
        try:
            await send_listing_card(
                bot,
                message.chat.id,
                listing,
                markup=markup,
                header=header,
                seller_rating=await seller_card_rating(listing),
            )
        except TelegramAPIError as exc:
            logger.warning("Mening eʼlonim #%s yuborilmadi: %s", listing.get("id"), exc)

    if len(listings) > MAX_SHOWN:
        await message.answer(
            f"ℹ️ Yana {len(listings) - MAX_SHOWN} ta eʼlon mavjud. "
            "Ularni kichik boʻlib koʻrib chiqing."
        )


@router.callback_query(F.data.startswith("sold_"))
async def mark_as_sold(callback: CallbackQuery, bot: Bot) -> None:
    """E'lonni «sotildi» deb belgilaydi va kanaldagi xabarni yangilaydi."""
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

    if int(listing["user_id"]) != user.id:
        await callback.answer("⛔️ Bu eʼlon sizga tegishli emas.", show_alert=True)
        return

    if listing.get("status") in ("sold", "found"):
        await callback.answer("ℹ️ Bu eʼlon allaqachon yopilgan.", show_alert=True)
        return

    new_status = "found" if listing.get("listing_type") == "buy" else "sold"
    await db.update_listing_status(listing_id, new_status)
    updated = await db.get_listing(listing_id)

    if updated is None:
        await callback.answer("⚠️ Texnik xatolik yuz berdi.", show_alert=True)
        return

    channel_id = await get_channel_id()
    if channel_id and updated.get("channel_msg_id"):
        header = (
            "🔴 <b>SOTILDI</b>"
            if new_status == "sold"
            else "✅ <b>TOPILDI</b>"
        )
        await edit_listing_card(
            bot,
            channel_id,
            int(updated["channel_msg_id"]),
            updated,
            markup=None,
            header=header,
        )

    await callback.answer("✅ Eʼlon yopildi. Tabriklaymiz!")

    if isinstance(callback.message, Message):
        await callback.message.answer(
            f"✅ <b>Eʼlon #{listing_id} yopildi.</b>\n\n"
            f"📌 Yangi holat: {status_label(new_status)}\n"
            "Kanalda eʼlon «SOTILDI» belgisi bilan yangilandi."
        )

    # Savdo yakunlandi — xaridorlarga baho qo'yishni taklif qilamiz
    for buyer_id in await db.get_listing_buyers(listing_id):
        with contextlib.suppress(TelegramAPIError):
            await bot.send_message(
                buyer_id,
                "✅ <b>Savdo yakunlandi!</b>\n\n"
                f"🔗 Eʼlon: <b>#{listing_id}</b>\n\n"
                "Bitim qanday oʻtganini baholang — sizning fikringiz boshqa "
                "xaridorlarga yordam beradi 👇",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="⭐️ Baho qoʻyish",
                                callback_data=f"rvw_{listing_id}",
                            )
                        ]
                    ]
                ),
            )


@router.callback_query(F.data.startswith("bump_"))
async def bump_listing(callback: CallbackQuery, bot: Bot) -> None:
    """E'lonni 24 soatda bir marta ko'taradi (UP)."""
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

    if int(listing["user_id"]) != user.id:
        await callback.answer("⛔️ Bu eʼlon sizga tegishli emas.", show_alert=True)
        return

    if listing.get("status") != "active":
        await callback.answer(
            "⚠️ Faqat aktiv eʼlonlarni koʻtarish mumkin.", show_alert=True
        )
        return

    available, remaining = is_bump_available(listing)
    if not available:
        await callback.answer(
            f"⏳ Eʼlonni 24 soatda faqat bir marta koʻtarish mumkin.\n"
            f"Keyingi urinishga {remaining} qoldi.",
            show_alert=True,
        )
        return

    channel_id = await get_channel_id()
    if not channel_id:
        await callback.answer("⚠️ Kanal sozlanmagan. Administratorga murojaat qiling.", show_alert=True)
        return

    try:
        message = await send_listing_card(
            bot,
            channel_id,
            listing,
            markup=None,
            header="🔄 <b>Eʼlon koʻtarildi (UP)</b>",
        )
    except TelegramAPIError as exc:
        logger.error("UP qilishda xatolik (#%s): %s", listing_id, exc)
        await callback.answer("⚠️ Kanalga joylab boʻlmadi. Keyinroq urinib koʻring.", show_alert=True)
        return

    old_message_id = listing.get("channel_msg_id")
    photos = list(listing.get("photos") or [])

    if message is not None:
        await db.set_channel_message_id(listing_id, message.message_id)

    # Bitta rasmdan iborat eski xabarni olib tashlaymiz (media-guruhni buzmaslik uchun)
    if old_message_id and len(photos) <= 1:
        await safe_delete(bot, channel_id, int(old_message_id))

    await db.update_bump_time(listing_id)
    await callback.answer("🔄 Eʼlon koʻtarildi! U kanalda yuqorida turadi.")


# ---------------------------------------------------------------------------
# Narxni tushirish (chegirma)
# ---------------------------------------------------------------------------
DROP_PRICE_PROMPT = (
    "📉 <b>Narxni tushirish</b>\n\n"
    "🆔 Eʼlon: <b>#{listing_id}</b>\n"
    "💵 Hozirgi narx: <b>{current}</b>\n\n"
    "Yangi (pastroq) narxni yozib yuboring — masalan <code>1 200 000</code> "
    "yoki <code>1.2mln</code>.\n\n"
    "Eski narx ustidan chizilib, yangisi kanalda ajratib koʻrsatiladi va "
    "eʼlonni <b>sevimlilarga</b> saqlagan barcha foydalanuvchilarga darhol "
    "xabar boradi.\n\n"
    "Bekor qilish uchun «❌ Bekor qilish» tugmasini bosing."
)


@router.callback_query(F.data.startswith("drop_price_"))
async def drop_price_start(callback: CallbackQuery, state: FSMContext) -> None:
    """«📉 Narxni tushirish» tugmasi bosildi."""
    user = callback.from_user
    raw_id = (callback.data or "").split("_", 2)[-1]
    if not raw_id.isdigit():
        await callback.answer("❌ Notoʻgʻri soʻrov.", show_alert=True)
        return

    listing_id = int(raw_id)
    listing = await db.get_listing(listing_id)
    if listing is None:
        await callback.answer("❌ Eʼlon topilmadi.", show_alert=True)
        return

    if int(listing["user_id"]) != user.id:
        await callback.answer("⛔️ Bu eʼlon sizga tegishli emas.", show_alert=True)
        return

    if listing.get("status") != "active":
        await callback.answer(
            "⚠️ Narxni faqat aktiv eʼlonlarda tushirish mumkin.", show_alert=True
        )
        return

    if is_trade(listing) or not listing.get("price_numeric"):
        await callback.answer(
            "ℹ️ Almashish (barter) eʼlonlarida narx boʻlmaydi.", show_alert=True
        )
        return

    await state.clear()
    await state.set_state(PriceDropFSM.waiting_new_price)
    await state.update_data(drop_listing_id=listing_id)
    await callback.answer("📉 Yangi narxni kiriting.")

    if isinstance(callback.message, Message):
        await callback.message.answer(
            DROP_PRICE_PROMPT.format(
                listing_id=listing_id,
                current=format_price(listing.get("price_numeric")),
            ),
            reply_markup=cancel_kb(),
        )


@router.message(PriceDropFSM.waiting_new_price, F.text)
async def drop_price_apply(message: Message, state: FSMContext, bot: Bot) -> None:
    """Yangi narxni qabul qiladi va kanal hamda sevimlilarga xabar yuboradi."""
    user = message.from_user
    if user is None:
        return

    if menu_button_guard(message):
        await message.answer(
            "ℹ️ Avval joriy amalni yakunlang yoki «❌ Bekor qilish» tugmasini bosing."
        )
        return

    data = await state.get_data()
    listing_id = int(data.get("drop_listing_id") or 0)
    listing = await db.get_listing(listing_id) if listing_id else None
    if listing is None:
        await state.clear()
        await message.answer(
            "⚠️ Eʼlon topilmadi. «📋 Mening eʼlonlarim» boʻlimidan qaytadan urinib koʻring.",
            reply_markup=main_menu_kb(),
        )
        return

    if int(listing["user_id"]) != user.id:
        await state.clear()
        await message.answer("⛔️ Bu eʼlon sizga tegishli emas.", reply_markup=main_menu_kb())
        return

    current = int(listing.get("price_numeric") or 0)
    new_price = parse_price(message.text)

    if new_price is None:
        await message.answer(
            "❌ Narxni tushunmadim. Iltimos, faqat raqam bilan yozing.\n\n"
            "Masalan: <code>1200000</code> yoki <code>1.2mln</code>"
        )
        return

    if new_price < int(settings.get("MIN_PRICE")):
        await message.answer(
            f"⚠️ Narx juda past (kamida {format_price(int(settings.get('MIN_PRICE')))}). "
            "Boshqa summa kiriting."
        )
        return

    if current and new_price >= current:
        await message.answer(
            "⚠️ <b>Yangi narx eskisidan past boʻlishi kerak.</b>\n\n"
            f"💵 Hozirgi narx: <b>{format_price(current)}</b>\n"
            "Chegirma uchun undan kichik summa kiriting."
        )
        return

    new_display = format_price(new_price)
    updated = await db.update_listing_price(listing_id, new_price, new_display)
    if updated is None:
        await state.clear()
        await message.answer("⚠️ Texnik xatolik. Keyinroq urinib koʻring.", reply_markup=main_menu_kb())
        return

    await state.clear()

    # --- Kanaldagi e'lonni yangilash -------------------------------------
    channel_id = await get_channel_id()
    channel_updated = False
    if channel_id and updated.get("channel_msg_id"):
        channel_updated = await edit_listing_card(
            bot,
            channel_id,
            int(updated["channel_msg_id"]),
            updated,
            markup=listing_action_kb(updated),
        )

    # --- Sevimlilarga saqlagan foydalanuvchilarga xabar -------------------
    notified = await notify_favoriters(bot, updated)

    await message.answer(
        "✅ <b>Narx yangilandi!</b>\n\n"
        f"🆔 Eʼlon: <b>#{listing_id}</b>\n"
        f"📉 Eski narx: ~{esc(updated.get('old_price') or format_price(current))}~\n"
        f"🔥 Yangi narx: <b>{esc(new_display)}</b>\n\n"
        f"📣 Kanal yangilandi: {'ha' if channel_updated else 'yoʻq'}\n"
        f"🔔 Xabar yuborilgan obunachilar: <b>{notified}</b>",
        reply_markup=main_menu_kb(),
    )


async def notify_favoriters(bot: Bot, listing: dict) -> int:
    """E'lonni sevimlilarga saqlagan foydalanuvchilarga xabar yuboradi."""
    listing_id = int(listing["id"])
    user_ids = await db.get_favorited_user_ids(listing_id)
    if not user_ids:
        return 0

    text = (
        "🔔 <b>Aksiyadorlik xabari!</b>\n\n"
        f"Siz «⭐️ Sevimlilar»ga saqlagan <b>#{listing_id}</b>-raqamli akkaunt "
        "narxi tushdi!\n\n"
        f"🔥 Yangi narx: <b>{esc(listing.get('price_display'))}</b>"
    )

    sent = 0
    for user_id in user_ids:
        try:
            await bot.send_message(user_id, text, disable_web_page_preview=True)
            sent += 1
        except TelegramAPIError as exc:
            logger.warning("Chegirma xabari yuborilmadi (user=%s): %s", user_id, exc)
    return sent


# ---------------------------------------------------------------------------
# E'lon muddati tugagach yangilash
# ---------------------------------------------------------------------------
@router.callback_query(F.data.startswith("renew_"))
async def renew_listing(callback: CallbackQuery, bot: Bot) -> None:
    """Muddati tugagan e'lonni yangilab, kanalga qayta joylaydi."""
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

    if int(listing["user_id"]) != user.id:
        await callback.answer("⛔️ Bu eʼlon sizga tegishli emas.", show_alert=True)
        return

    if listing.get("status") != "expired":
        await callback.answer("ℹ️ Bu eʼlon muddati tugamagan.", show_alert=True)
        return

    channel_id = await get_channel_id()
    if not channel_id:
        await callback.answer(
            "⚠️ Kanal sozlanmagan. Administratorga murojaat qiling.", show_alert=True
        )
        return

    await db.update_listing_status(listing_id, "active")
    await db.touch_listing_expiry(listing_id)
    updated = await db.get_listing(listing_id)
    if updated is None:
        await callback.answer("⚠️ Texnik xatolik.", show_alert=True)
        return

    try:
        message = await send_listing_card(
            bot,
            channel_id,
            updated,
            markup=listing_action_kb(updated),
            header="🔄 <b>Eʼlon yangilandi</b>",
            seller_label=await seller_label_of(updated),
            seller_rating=await seller_card_rating(updated),
        )
    except TelegramAPIError as exc:
        logger.error("Eʼlonni yangilashda xatolik (#%s): %s", listing_id, exc)
        await callback.answer("⚠️ Kanalga joylab boʻlmadi. Keyinroq urinib koʻring.", show_alert=True)
        return

    old_message_id = listing.get("channel_msg_id")
    photos = list(updated.get("photos") or [])
    if message is not None:
        await db.set_channel_message_id(listing_id, message.message_id)
    if old_message_id and len(photos) <= 1:
        await safe_delete(bot, channel_id, int(old_message_id))

    await db.update_bump_time(listing_id)
    await callback.answer("🔄 Eʼlon yangilandi!")

    if isinstance(callback.message, Message):
        await callback.message.answer(
            f"✅ <b>Eʼlon #{listing_id} yana {settings.get('LISTING_TTL_DAYS')} kunga"
            " yangilandi.</b>\n\n"
            "U kanalda qayta joylandi va roʻyxatda koʻrinadi."
        )


# ---------------------------------------------------------------------------
# E'lonni tahrirlash
# ---------------------------------------------------------------------------
EDIT_FIELDS = {"price", "desc", "contact"}

EDIT_PROMPTS = {
    "desc": (
        "📝 <b>Izohni tahrirlash</b>\n\n"
        "🆔 Eʼlon: <b>#{listing_id}</b>\n"
        "📄 Hozirgi izoh: <i>{current}</i>\n\n"
        f"Yangi izohni yozib yuboring (maks. {settings.get('MAX_DESCRIPTION_LENGTH')} belgi)."
    ),
    "contact": (
        "🔗 <b>Aloqani tahrirlash</b>\n\n"
        "🆔 Eʼlon: <b>#{listing_id}</b>\n"
        "📄 Hozirgi aloqa: <i>{current}</i>\n\n"
        "Yangi aloqa maʼlumotini yozib yuboring — masalan <code>@username</code>."
    ),
}


@router.callback_query(F.data.startswith("edit_"))
async def edit_listing_start(callback: CallbackQuery, state: FSMContext) -> None:
    """«✏️ Tahrirlash» — maydon tanlash menyusi."""
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

    if int(listing["user_id"]) != user.id:
        await callback.answer("⛔️ Bu eʼlon sizga tegishli emas.", show_alert=True)
        return

    if listing.get("status") not in ("active", "pending"):
        await callback.answer(
            "⚠️ Faqat aktiv yoki moderatsiyadagi eʼlonni tahrirlash mumkin.",
            show_alert=True,
        )
        return

    await state.clear()
    await callback.answer()
    if isinstance(callback.message, Message):
        await callback.message.answer(
            f"✏️ <b>Eʼlon #{listing_id} ni tahrirlash</b>\n\n"
            f"🏆 Rank: {esc(listing.get('rank_info') or '—')}\n"
            f"💵 Narx: {esc(listing.get('price_display') or format_price(listing.get('price_numeric')))}\n\n"
            "Qaysi maydonni oʻzgartirasiz?",
            reply_markup=edit_listing_kb(listing_id),
        )


@router.callback_query(F.data.startswith("editf_"))
async def edit_field_start(callback: CallbackQuery, state: FSMContext) -> None:
    """Tahrirlanadigan maydon tanlandi."""
    user = callback.from_user
    parts = (callback.data or "").split("_", 2)
    if len(parts) < 3 or parts[1] not in EDIT_FIELDS or not parts[2].isdigit():
        await callback.answer("❌ Notoʻgʻri soʻrov.", show_alert=True)
        return

    field, listing_id = parts[1], int(parts[2])
    listing = await db.get_listing(listing_id)
    if listing is None:
        await callback.answer("❌ Eʼlon topilmadi.", show_alert=True)
        return

    if int(listing["user_id"]) != user.id:
        await callback.answer("⛔️ Bu eʼlon sizga tegishli emas.", show_alert=True)
        return

    await state.clear()
    await state.update_data(edit_listing_id=listing_id, edit_field=field)

    if isinstance(callback.message, Message):
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except TelegramAPIError:
            pass

    if field == "price":
        if is_trade(listing) or not listing.get("price_numeric"):
            await callback.answer(
                "ℹ️ Bu eʼlonda narx yoʻq (barter/soʻrov).", show_alert=True
            )
            return
        await state.set_state(EditFSM.waiting_price)
        await callback.answer("💵 Yangi narxni kiriting.")
        if isinstance(callback.message, Message):
            await callback.message.answer(
                "💵 <b>Narxni tahrirlash</b>\n\n"
                f"🆔 Eʼlon: <b>#{listing_id}</b>\n"
                f"💵 Hozirgi narx: <b>{esc(format_price(listing.get('price_numeric')))}</b>\n\n"
                "Yangi narxni yozib yuboring — masalan <code>1 500 000</code> "
                "yoki <code>1.5mln</code>.",
                reply_markup=cancel_kb(),
            )
        return

    state_map = {"desc": EditFSM.waiting_description, "contact": EditFSM.waiting_contact}
    await state.set_state(state_map[field])
    await callback.answer("✍️ Yangi qiymatni kiriting.")
    if isinstance(callback.message, Message):
        current = listing.get("description") if field == "desc" else listing.get("contact")
        await callback.message.answer(
            EDIT_PROMPTS[field].format(
                listing_id=listing_id, current=esc(current or "—")
            ),
            reply_markup=cancel_kb(),
        )


async def _apply_edit(
    message: Message,
    state: FSMContext,
    bot: Bot,
    fields: dict,
    summary: str,
) -> None:
    """O'zgarishni bazaga yozadi va kanal kartochkasini yangilaydi."""
    data = await state.get_data()
    await state.clear()

    listing_id = int(data.get("edit_listing_id") or 0)
    listing = await db.get_listing(listing_id) if listing_id else None
    if listing is None:
        await message.answer(
            "⚠️ Eʼlon topilmadi. «📋 Mening eʼlonlarim» boʻlimidan qaytadan urinib koʻring.",
            reply_markup=main_menu_kb(),
        )
        return

    updated = await db.update_listing_fields(listing_id, **fields)
    if updated is None:
        await message.answer("⚠️ Texnik xatolik.", reply_markup=main_menu_kb())
        return

    channel_id = await get_channel_id()
    channel_updated = False
    if updated.get("status") == "active" and channel_id and updated.get("channel_msg_id"):
        channel_updated = await edit_listing_card(
            bot,
            channel_id,
            int(updated["channel_msg_id"]),
            updated,
            markup=listing_action_kb(updated),
        )

    await message.answer(
        f"✅ <b>Eʼlon #{listing_id} tahrirlandi.</b>\n\n"
        f"{summary}\n\n"
        f"📣 Kanal yangilandi: {'ha' if channel_updated else 'yoʻq'}",
        reply_markup=main_menu_kb(),
    )


@router.message(EditFSM.waiting_price, F.text)
async def edit_price_apply(message: Message, state: FSMContext, bot: Bot) -> None:
    """Yangi narxni saqlaydi."""
    if menu_button_guard(message):
        await message.answer(
            "ℹ️ Avval joriy amalni yakunlang yoki «❌ Bekor qilish» tugmasini bosing."
        )
        return

    price = parse_price(message.text)
    if price is None:
        await message.answer(
            "❌ Narxni tushunmadim. Iltimos, faqat raqam bilan yozing.\n\n"
            "Masalan: <code>1500000</code>"
        )
        return

    if price < int(settings.get("MIN_PRICE")) or price > int(settings.get("MAX_PRICE")):
        await message.answer(
            f"⚠️ Narx {format_price(int(settings.get('MIN_PRICE')))} dan kam boʻlmasligi va "
            "juda katta boʻlmasligi kerak. Qaytadan kiriting."
        )
        return

    display = format_price(price)
    await _apply_edit(
        message,
        state,
        bot,
        {"price_numeric": price, "price_display": display, "old_price": None},
        f"💵 Yangi narx: <b>{esc(display)}</b>",
    )


@router.message(EditFSM.waiting_description, F.text)
async def edit_description_apply(message: Message, state: FSMContext, bot: Bot) -> None:
    """Yangi izohni saqlaydi."""
    if menu_button_guard(message):
        await message.answer(
            "ℹ️ Avval joriy amalni yakunlang yoki «❌ Bekor qilish» tugmasini bosing."
        )
        return

    text = (message.text or "").strip()
    if len(text) < 3:
        await message.answer("❌ Izoh juda qisqa. Iltimos, batafsilroq yozing.")
        return

    text = text[: int(settings.get("MAX_DESCRIPTION_LENGTH"))]
    await _apply_edit(
        message, state, bot, {"description": text}, f"📝 Yangi izoh: {esc(text)}"
    )


@router.message(EditFSM.waiting_contact, F.text)
async def edit_contact_apply(message: Message, state: FSMContext, bot: Bot) -> None:
    """Yangi aloqa ma'lumotini saqlaydi."""
    if menu_button_guard(message):
        await message.answer(
            "ℹ️ Avval joriy amalni yakunlang yoki «❌ Bekor qilish» tugmasini bosing."
        )
        return

    contact = (message.text or "").strip()
    if len(contact) < 4:
        await message.answer("❌ Aloqa maʼlumoti juda qisqa. Masalan: <code>@username</code>")
        return

    contact = contact[:120]
    await _apply_edit(
        message, state, bot, {"contact": contact}, f"🔗 Yangi aloqa: {esc(contact)}"
    )


@router.message(StateFilter(EditFSM))
async def edit_fallback(message: Message) -> None:
    """Tahrirlash bosqichida noto'g'ri xabar."""
    await message.answer(
        "✍️ Iltimos, yangi qiymatni matn koʻrinishida yozing yoki "
        "«❌ Bekor qilish» tugmasini bosing.",
        reply_markup=cancel_kb(),
    )


__all__ = ["router"]
