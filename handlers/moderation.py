"""AI moderatsiya orkestratsiyasi.

Yangi e'lon (yoki xaridor so'rovi) yaratilgach shu modul chaqiriladi:

1. AI yoqilgan bo'lsa e'lon matni tahlil qilinadi;
2. natija adminlarga matn ko'rinishida yuboriladi;
3. sozlamalarga qarab e'lon **avtomatik tasdiqlanishi** yoki
   **avtomatik rad etilishi** mumkin.

Bu modul router emas — faqat funksiya eksport qiladi.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from aiogram import Bot

import ai
from database import db
from handlers.admin import approve_listing, reject_listing
from handlers.common import esc
from settings import settings

logger = logging.getLogger(__name__)


@dataclass
class ModerationOutcome:
    """AI tekshiruvi natijasi."""

    #: Adminlarga yuboriladigan qo'shimcha matn (bo'sh bo'lsa hech narsa yuborilmaydi)
    text: str = ""
    #: AI mustaqil qaror qabul qildimi (tasdiqladi yoki rad etdi)
    decided: bool = False
    #: AI javobini qabul qilmadimi (xatolik)
    failed: bool = False


async def _apply_verdict(bot: Bot, listing_id: int, verdict: ai.AIVerdict) -> tuple[str, bool]:
    """AI qarorini sozlamalarga qarab qo'llaydi va xabar matnini qaytaradi."""
    blocks: list[str] = [verdict.as_text()]
    decided = False

    if ai.should_auto_approve(verdict):
        ok, message = await approve_listing(bot, listing_id)
        if ok:
            decided = True
            blocks.append(f"🤖 <b>AI avtomatik tasdiqladi.</b>\n{esc(message)}")
        else:
            blocks.append(
                f"⚠️ Avtomatik tasdiqlash bajarilmadi: {esc(message)}\n"
                "Eʼlon qoʻlda tasdiqlashingiz mumkin."
            )
    elif ai.should_auto_reject(verdict):
        ok, message = await reject_listing(bot, listing_id, verdict.reason)
        if ok:
            decided = True
            blocks.append(f"🤖 <b>AI avtomatik rad etdi.</b>\n{esc(message)}")
        else:
            blocks.append(f"⚠️ {esc(message)}")
    else:
        blocks.append(
            "ℹ️ Mustaqil qaror qabul qilinmadi — eʼlon qoʻlda koʻrib chiqilishini kutmoqda."
        )

    return "\n\n".join(blocks), decided


async def ai_moderate_listing(bot: Bot, listing_id: int) -> ModerationOutcome:
    """E'lonni AI orqali tekshiradi va kerak bo'lsa qaror qabul qiladi."""
    if not ai.is_enabled():
        return ModerationOutcome()

    listing = await db.get_listing(listing_id)
    if listing is None:
        return ModerationOutcome()

    try:
        verdict = await ai.moderate_listing(listing, bot=bot)
    except ai.AIError as exc:
        logger.warning("AI moderatsiya ishlamadi (#%s): %s", listing_id, exc)
        return ModerationOutcome(
            text=(
                "⚠️ <b>AI tekshiruvi bajarilmadi</b>\n\n"
                f"🛠 Xato: {esc(str(exc))}\n\n"
                "Eʼlon qoʻlda tekshirishni kutmoqda."
            ),
            failed=True,
        )

    text, decided = await _apply_verdict(bot, listing_id, verdict)
    return ModerationOutcome(text=text, decided=decided)


async def manual_ai_check(bot: Bot, listing_id: int) -> tuple[str, bool]:
    """Admin qoʻlda ishga tushirgan AI tekshiruvi.

    Avtomatik tekshiruvdan farqli ravishda AI oʻchirilgan boʻlsa ham aniq
    sabab qaytaradi — shu tufayli admin nima uchun ishlamayotganini biladi.
    """
    if not settings.get_bool("AI_ENABLED"):
        return (
            "⛔️ <b>AI moderatsiya oʻchirilgan.</b>\n\n"
            "«🤖 AI» panelidan «✅ AI tekshiruvni yoqish» tugmasini bosing.",
            False,
        )
    if not ai.is_enabled():
        return (
            "⚠️ <b>AI API kaliti kiritilmagan.</b>\n\n"
            "«🔑 AI API kalitini kiritish» tugmasi orqali kalitni qoʻshing.",
            False,
        )

    listing = await db.get_listing(listing_id)
    if listing is None:
        return "⚠️ Eʼlon topilmadi.", False

    try:
        verdict = await ai.moderate_listing(listing, bot=bot)
    except ai.AIError as exc:
        logger.warning("Qoʻlda AI tekshiruvi ishlamadi (#%s): %s", listing_id, exc)
        return f"⚠️ <b>AI tekshiruvi bajarilmadi</b>\n\n🛠 Xato: {esc(str(exc))}", False

    return await _apply_verdict(bot, listing_id, verdict)


__all__ = ["ModerationOutcome", "ai_moderate_listing", "manual_ai_check"]
