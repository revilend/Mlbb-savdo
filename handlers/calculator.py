"""Akkaunt narxini hisoblash (CalcFSM).

Rank va skin toifalari asosida Oʻzbekiston bozori uchun real narx oraligʻi
hisoblab beriladi.
"""

from __future__ import annotations

import logging
import re

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from handlers.common import esc, format_price, menu_button_guard
from keyboards import BTN_CALC, RANKS, cancel_kb, main_menu_kb, rank_kb
from states import CalcFSM

logger = logging.getLogger(__name__)

router = Router(name="calculator")

# Rank bo'yicha bazaviy narx (soʻm)
RANK_BASE_PRICE: dict[str, int] = {
    "Mythic Glory": 4_500_000,
    "Mythic": 2_200_000,
    "Legend": 1_100_000,
    "Epic": 550_000,
    "Grandmaster": 300_000,
    "Master va undan past": 120_000,
}
DEFAULT_RANK_PRICE = 250_000

# Skin toifalari bo'yicha qoʻshimcha qiymat (soʻm)
COLLECTOR_VALUE = 220_000
LEGEND_VALUE = 320_000
EPIC_VALUE = 65_000

# Hisoblangan narxga qoʻllaniladigan koeffitsiyentlar
LOW_FACTOR = 0.82
HIGH_FACTOR = 1.22

INTRO_TEXT = (
    "🧮 <b>Akkaunt narx kalkulyatori</b>\n\n"
    "Bir necha savolga javob bering — akkauntingizning real bozor narxini "
    "hisoblab beraman.\n\n"
    "Bekor qilish uchun «❌ Bekor qilish» tugmasini bosing."
)

RANK_ASK = "1️⃣ <b>Akkauntning ranki qanday?</b>"
COLLECTOR_ASK = (
    "2️⃣ <b>Nechta Collector skin bor?</b>\n\n"
    "Faqat raqam yozing. Agar yoʻq boʻlsa <code>0</code> yuboring."
)
LEGEND_ASK = (
    "3️⃣ <b>Nechta Legend skin bor?</b>\n\n"
    "Faqat raqam yozing. Agar yoʻq boʻlsa <code>0</code> yuboring."
)
EPIC_ASK = (
    "4️⃣ <b>Nechta Epic skin bor?</b>\n\n"
    "Faqat raqam yozing. Agar yoʻq boʻlsa <code>0</code> yuboring."
)


def _parse_count(text: str, limit: int = 2000) -> int | None:
    """Matndan sonni ajratadi (0 ham to'g'ri javob)."""
    if text is None:
        return None
    digits = re.sub(r"\D", "", text)
    if not digits:
        return None
    value = int(digits)
    if value > limit:
        return None
    return value


def _estimate(rank: str, collector: int, legend: int, epic: int) -> tuple[int, int, int]:
    """(pastki, oʻrta, yuqori) narx oraligʻini hisoblaydi."""
    base = RANK_BASE_PRICE.get(rank, DEFAULT_RANK_PRICE)
    total = base + collector * COLLECTOR_VALUE + legend * LEGEND_VALUE + epic * EPIC_VALUE
    low = int(total * LOW_FACTOR // 10_000 * 10_000)
    middle = int(total // 10_000 * 10_000)
    high = int(total * HIGH_FACTOR // 10_000 * 10_000)
    return max(low, 10_000), middle, high


@router.message(StateFilter(None), F.text == BTN_CALC)
async def start_calc(message: Message, state: FSMContext) -> None:
    """Kalkulyatorni boshlaydi."""
    await state.clear()
    await state.set_state(CalcFSM.rank)
    await message.answer(INTRO_TEXT, reply_markup=cancel_kb())
    await message.answer(RANK_ASK, reply_markup=rank_kb("crank"))


@router.callback_query(CalcFSM.rank, F.data.startswith("crank_"))
async def calc_rank_cb(callback: CallbackQuery, state: FSMContext) -> None:
    """Rank tugma orqali tanlandi."""
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
        await callback.answer("❌ Notoʻgʻri tanlov.", show_alert=True)
        return

    rank = RANKS[int(value)]
    await state.update_data(rank=rank)
    await callback.answer(f"Tanlandi: {rank}")

    if isinstance(callback.message, Message):
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except TelegramAPIError:
            pass
        await state.set_state(CalcFSM.collector_count)
        await callback.message.answer(COLLECTOR_ASK)


@router.message(CalcFSM.rank, F.text)
async def calc_rank_text(message: Message, state: FSMContext) -> None:
    """Rank matn orqali kiritildi."""
    if menu_button_guard(message):
        await message.answer("ℹ️ Avval joriy amalni yakunlang yoki «❌ Bekor qilish» tugmasini bosing.")
        return

    rank = (message.text or "").strip()
    if len(rank) < 2:
        await message.answer("❌ Rank juda qisqa. Masalan: <i>Mythic Glory</i>")
        return

    await state.update_data(rank=rank[:60])
    await state.set_state(CalcFSM.collector_count)
    await message.answer(COLLECTOR_ASK)


@router.message(CalcFSM.collector_count, F.text)
async def calc_collector(message: Message, state: FSMContext) -> None:
    """Collector skinlar soni."""
    if menu_button_guard(message):
        await message.answer("ℹ️ Avval joriy amalni yakunlang yoki «❌ Bekor qilish» tugmasini bosing.")
        return

    count = _parse_count(message.text or "")
    if count is None:
        await message.answer("❌ Iltimos, faqat raqam yozing (masalan: <code>8</code> yoki <code>0</code>).")
        return

    await state.update_data(collector_count=count)
    await state.set_state(CalcFSM.legend_count)
    await message.answer(LEGEND_ASK)


@router.message(CalcFSM.legend_count, F.text)
async def calc_legend(message: Message, state: FSMContext) -> None:
    """Legend skinlar soni."""
    if menu_button_guard(message):
        await message.answer("ℹ️ Avval joriy amalni yakunlang yoki «❌ Bekor qilish» tugmasini bosing.")
        return

    count = _parse_count(message.text or "")
    if count is None:
        await message.answer("❌ Iltimos, faqat raqam yozing (masalan: <code>2</code> yoki <code>0</code>).")
        return

    await state.update_data(legend_count=count)
    await state.set_state(CalcFSM.epic_count)
    await message.answer(EPIC_ASK)


@router.message(CalcFSM.epic_count, F.text)
async def calc_epic(message: Message, state: FSMContext) -> None:
    """Epic skinlar soni va yakuniy hisob-kitob."""
    if menu_button_guard(message):
        await message.answer("ℹ️ Avval joriy amalni yakunlang yoki «❌ Bekor qilish» tugmasini bosing.")
        return

    count = _parse_count(message.text or "")
    if count is None:
        await message.answer("❌ Iltimos, faqat raqam yozing (masalan: <code>15</code> yoki <code>0</code>).")
        return

    data = await state.get_data()
    rank = str(data.get("rank") or "Nomaʼlum")
    collector = int(data.get("collector_count") or 0)
    legend = int(data.get("legend_count") or 0)
    epic = count

    await state.clear()

    low, middle, high = _estimate(rank, collector, legend, epic)

    tips: list[str] = []
    if collector == 0 and legend == 0:
        tips.append("Collector va Legend skinlar narxni sezilarli oshiradi — ularni alohida koʻrsating.")
    if collector >= 5:
        tips.append("Kollektsiyangiz kuchli — eʼlonda collector skinlar roʻyxatini alohida yozing.")
    if "glory" in rank.lower():
        tips.append("Mythic Glory akkauntlar talabgir — narxni pastga tushirmaslikka harakat qiling.")
    tips.append("Akkauntni faqat garant xizmati orqali soting — bu sizni firibgarlikdan himoya qiladi.")
    tips.append("Eʼlonda email va telefon bogʻlanishi holatini aniq koʻrsating.")

    text = (
        "🧮 <b>Narx hisob-kitobi tayyor!</b>\n\n"
        f"🏆 Rank: <b>{esc(rank)}</b>\n"
        f"💎 Collector skin: <b>{collector}</b>\n"
        f"👑 Legend skin: <b>{legend}</b>\n"
        f"✨ Epic skin: <b>{epic}</b>\n\n"
        "💰 <b>Bozor narxi oraligʻi:</b>\n"
        f"🟢 Pastki chegara: <b>{esc(format_price(low))}</b>\n"
        f"🟡 Oʻrtacha narx: <b>{esc(format_price(middle))}</b>\n"
        f"🔴 Yuqori chegara: <b>{esc(format_price(high))}</b>\n\n"
        "💡 <b>Tavsiyalar</b>\n"
        + "\n".join(f"• {esc(tip)}" for tip in tips)
    )

    await message.answer(text, reply_markup=main_menu_kb())
