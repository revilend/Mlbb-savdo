"""Bozor narx statistikasi va sotuvchini shikoyat qilish.

Ikki bo'lim bitta routerda:
* **📈 Narx statistikasi** — sotilgan e'lonlar bo'yicha rank ga ko'ra
  o'rtacha / minimal / maksimal narxni ko'rsatadi va e'lon qo'yishda
  bozor narxini tavsiya qiladi.
* **🚨 Shikoyat qilish** — xaridor sotuvchi ustidan shikoyat qoldiradi,
  u saqlanadi va adminlarga darhol yuboriladi.
"""

from __future__ import annotations

import contextlib
import logging
from typing import Optional

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.filters import StateFilter
from aiogram.types import CallbackQuery, Message

from database import db
from handlers.common import esc, format_price, menu_button_guard, notify_admin, user_label
from keyboards import (
    BTN_CANCEL,
    BTN_MARKET,
    REPORT_REASONS,
    cancel_kb,
    main_menu_kb,
    market_period_kb,
    report_reason_kb,
)
from states import ReportFSM

logger = logging.getLogger(__name__)

router = Router(name="market")

#: Bozor statistikasida ko'rsatiladigan maksimal ranklar soni
MAX_ROWS = 15
#: Shikoyat izohining maksimal uzunligi
MAX_DETAILS = 500

EMPTY_MARKET = (
    "📈 <b>Narx statistikasi</b>\n\n"
    "Hozircha bozor uchun yetarli maʼlumot yoʻq.\n\n"
    "Statistika faqat <b>sotilgan</b> eʼlonlar boʻyicha hisoblanadi — "
    "sotilgan eʼlonlar soni oshsa, narxlar ham aniqroq boʻladi."
)

DETAILS_ASK = (
    "📝 <b>Shikoyatni tasdiqlang</b>\n\n"
    "Nima boʻlganini yozing (ixtiyoriy, {limit} belgigacha).\n"
    "Masalan: <i>Pulni oldim, akkauntni bermadi, 2 kun javob bermadi.</i>\n\n"
    "Maʼlumot bermasangiz ham shikoyat yuboriladi."
)

#: Sabab kodi -> koʻrsatiladigan matn (`REPORT_REASONS` teskari tartibda berilgan)
REASON_LABELS: dict[str, str] = {code: label for label, code in REPORT_REASONS}

REPORT_SENT = (
    "✅ <b>Shikoyatingiz qabul qilindi</b>\n\n"
    "📌 Sabab: {reason}\n"
    "🆔 Eʼlon: #{listing}\n"
    "👤 Sotuvchi: {seller}\n\n"
    "Administratorlar tez orada koʻrib chiqadi. "
    "Natija haqida xabar beramiz."
)


# ---------------------------------------------------------------------------
# 📈 Narx statistikasi
# ---------------------------------------------------------------------------
def _format_market(days: int, rows: list[dict]) -> str:
    """Bozor statistikasini matn ko'rinishida chiqaradi."""
    if not rows:
        return EMPTY_MARKET

    lines = [
        "📈 <b>Narx statistikasi (bozor)</b>\n",
        f"🗓 Oxirgi <b>{days}</b> kun · sotilgan eʼlonlar boʻyicha\n",
    ]
    for row in rows[:MAX_ROWS]:
        rank = str(row.get("rank") or "—")
        count = int(row.get("cnt") or 0)
        avg = format_price(row.get("avg_price"))
        low = format_price(row.get("min_price"))
        high = format_price(row.get("max_price"))
        lines.append(
            f"🏆 <b>{esc(rank)}</b> — {count} ta savdo\n"
            f"   📊 Oʻrtacha: <b>{esc(avg)}</b>\n"
            f"   🔻 Eng arzon: {esc(low)} · 🔺 Eng qimmat: {esc(high)}"
        )

    if len(rows) > MAX_ROWS:
        lines.append(f"\n… va yana {len(rows) - MAX_ROWS} ta rank.")

    total = sum(int(row.get("cnt") or 0) for row in rows)
    lines.append(
        f"\n📌 Jami hisobga olingan savdolar: <b>{total}</b>\n\n"
        "💡 Narxni shu raqamlar atrofida qoʻyish bozorga koʻproq mos keladi."
    )
    return "\n".join(lines)


async def _send_market(message: Message, days: int) -> None:
    """Bozor statistikasini yuboradi."""
    rows = await db.get_market_stats(days=days)
    try:
        await message.answer(
            _format_market(days, rows),
            reply_markup=market_period_kb(days),
            disable_web_page_preview=True,
        )
    except TelegramAPIError as exc:
        logger.debug("Bozor statistikasi yuborilmadi: %s", exc)


@router.message(StateFilter(None), F.text == BTN_MARKET)
async def market_menu(message: Message) -> None:
    """Menyudagi «📈 Narx statistikasi» tugmasi."""
    await _send_market(message, days=30)


@router.callback_query(F.data.startswith("mkt_"))
async def market_period(callback: CallbackQuery, state: FSMContext) -> None:
    """Davrni o'zgartiradi yoki menyuga qaytaradi."""
    raw = (callback.data or "").split("_", 1)[-1]

    if raw == "back":
        await callback.answer()
        if isinstance(callback.message, Message):
            await callback.message.answer(
                "📈 Bozor statistikasi uchun menyudan «📈 Narx statistikasi» "
                "tugmasini bosing.",
                reply_markup=main_menu_kb(),
            )
        return

    if not raw.isdigit():
        await callback.answer("❌ Notoʻgʻri soʻrov.", show_alert=True)
        return

    await callback.answer("🔄 Yangilanmoqda…")
    if isinstance(callback.message, Message):
        await _send_market(callback.message, days=int(raw))


# ---------------------------------------------------------------------------
# 🚨 Shikoyat qilish
# ---------------------------------------------------------------------------
async def _seller_label(user_id: int) -> str:
    user = await db.get_user(user_id)
    return user_label(user_id, (user or {}).get("username"), (user or {}).get("full_name"))


@router.callback_query(F.data.startswith("rep_l_"), StateFilter(None))
async def report_start(callback: CallbackQuery, state: FSMContext) -> None:
    """«🚨 Shikoyat qilish» — sababni tanlash bosqichi."""
    raw = (callback.data or "").split("_", 2)[-1]
    if not raw.isdigit():
        await callback.answer("❌ Notoʻgʻri soʻrov.", show_alert=True)
        return

    listing_id = int(raw)
    listing = await db.get_listing(listing_id)
    if listing is None:
        await callback.answer("❌ Eʼlon topilmadi.", show_alert=True)
        return

    seller_id = int(listing["user_id"])
    if seller_id == callback.from_user.id:
        await callback.answer(
            "🙂 Oʻz eʼloningizga shikoyat qila olmaysiz.", show_alert=True
        )
        return

    await callback.answer("🚨 Sababni tanlang")
    if isinstance(callback.message, Message):
        await callback.message.answer(
            "🚨 <b>Shikoyat qilish</b>\n\n"
            "Sotuvchi ustidan shikoyat qoldirasiz.\n"
            f"🆔 Eʼlon: <b>#{listing_id}</b>\n"
            f"👤 Sotuvchi: {esc(await _seller_label(seller_id))}\n\n"
            "Qaysi holat yuz berdi?",
            reply_markup=report_reason_kb(listing_id, seller_id),
            disable_web_page_preview=True,
        )
    await state.clear()


@router.callback_query(F.data.startswith("rep_r_"), StateFilter(None))
async def report_reason(callback: CallbackQuery, state: FSMContext) -> None:
    """Sabab tanlandi — izoh kutish holatiga o'tadi."""
    parts = (callback.data or "").split("_")
    # rep_r_<code>_<listing_id>_<seller_id>
    if len(parts) != 5 or not parts[3].isdigit() or not parts[4].isdigit():
        await callback.answer("❌ Notoʻgʻri soʻrov.", show_alert=True)
        return

    code = parts[2]
    if code not in REASON_LABELS:
        await callback.answer("❌ Nomaʼlum sabab.", show_alert=True)
        return

    listing_id = int(parts[3])
    seller_id = int(parts[4])

    listing = await db.get_listing(listing_id)
    if listing is None or int(listing["user_id"]) != seller_id:
        await callback.answer("❌ Eʼlon topilmadi.", show_alert=True)
        return

    await state.clear()
    await state.set_state(ReportFSM.waiting_details)
    await state.update_data(
        report_listing_id=listing_id,
        report_seller_id=seller_id,
        report_reason=code,
    )
    await callback.answer("📝 Izochni yozing")
    if isinstance(callback.message, Message):
        await callback.message.answer(
            DETAILS_ASK.format(limit=MAX_DETAILS), reply_markup=cancel_kb()
        )


@router.message(ReportFSM.waiting_details, F.text)
async def report_details(message: Message, state: FSMContext, bot: Bot) -> None:
    """Izohni qabul qilib shikoyatni saqlaydi."""
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

    data = await state.get_data()
    await state.clear()
    listing_id = int(data.get("report_listing_id") or 0)
    seller_id = int(data.get("report_seller_id") or 0)
    code = str(data.get("report_reason") or "")

    if not listing_id or not seller_id or code not in REASON_LABELS:
        await message.answer(
            "⚠️ Shikoyat maʼlumotlari yoʻqolib qoldi. Qayta urinib koʻring.",
            reply_markup=main_menu_kb(),
        )
        return

    user = message.from_user
    if user is None:
        return

    if await db.has_open_report(user.id, seller_id):
        await message.answer(
            "ℹ️ Siz bu sotuvchi ustidan allaqachon shikoyat yuborgansiz. "
            "Administratorlar uni koʻrib chiqmoqda.",
            reply_markup=main_menu_kb(),
        )
        return

    reason_label = REASON_LABELS[code]
    report_id = await db.create_report(
        reporter_id=user.id,
        target_id=seller_id,
        listing_id=listing_id,
        reason=reason_label,
        details=text[:MAX_DETAILS],
    )
    open_reports = await db.get_report_stats(seller_id)

    await message.answer(
        REPORT_SENT.format(
            reason=esc(reason_label),
            listing=listing_id,
            seller=esc(await _seller_label(seller_id)),
        ),
        reply_markup=main_menu_kb(),
    )

    reporter = user_label(user.id, user.username, user.full_name)
    with contextlib.suppress(TelegramAPIError):
        await notify_admin(
            bot,
            "🚨 <b>Yangi shikoyat</b>\n\n"
            f"🆔 Shikoyat raqami: <b>#{report_id}</b>\n"
            f"📌 Sabab: <b>{esc(reason_label)}</b>\n"
            f"🆔 Eʼlon: #{listing_id}\n"
            f"👤 Sotuvchi: {esc(await _seller_label(seller_id))} "
            f"(<code>{seller_id}</code>)\n"
            f"🙋 Shikoyat qilgan: {esc(reporter)} (<code>{user.id}</code>)\n"
            + (f"📝 Izoh: {esc(text[:MAX_DETAILS])}\n" if text else "")
            + f"📊 Bu sotuvchi ustidan umumiy shikoyatlar: <b>{open_reports}</b>",
        )


@router.message(ReportFSM.waiting_details)
async def report_fallback(message: Message) -> None:
    """Matn o'rniga boshqa turdagi xabar kelsa."""
    await message.answer(
        "📝 Iltimos, shikoyatni matn ko'rinishida yozing yoki "
        "«❌ Bekor qilish» tugmasini bosing.",
        reply_markup=cancel_kb(),
    )


# ---------------------------------------------------------------------------
# Narx bo'yicha bozor tavsiyasi (e'lon qo'yishda)
# ---------------------------------------------------------------------------
async def price_suggestion_text(rank_info: str, days: int = 30) -> Optional[str]:
    """Rank uchun bozor o'rtacha narxini matn ko'rinishida beradi.

    Maʼlumot yetarli bo'lmasa `None` qaytaradi — foydalanuvchi hech qanday
    bozor qarori majburlashini xohlamaymiz.
    """
    average = await db.get_price_suggestion(rank_info, days=days)
    if not average:
        return None
    return (
        f"📈 <b>Bozor maʼlumoti:</b> «{esc(rank_info)}» ranki uchun oxirgi "
        f"{days} kunda sotilgan eʼlonlarning oʻrtacha narxi — "
        f"<b>{esc(format_price(average))}</b>.\n"
        "Narxni shu atrofda qoʻyish xaridor topishiga yordam beradi."
    )


__all__ = ["market_menu", "price_suggestion_text", "router"]
