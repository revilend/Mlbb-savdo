"""Garant (xavfsiz bitim) xizmati bo'limi."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.types import Message

from keyboards import BTN_GARANT, garant_kb, private_chat_kb
from middlewares import permanent

router = Router(name="garant")

GARANT_TEXT = (
    "🛡️ <b>Garant xizmati — xavfsiz bitim</b>\n\n"
    "Garant — bu ikki tomon oʻrtasidagi ishonchli vositachi. "
    "Pul va akkaunt bir vaqtning oʻzida almashinadi, shu sababli "
    "firibgarlik ehtimoli deyarli nolga tushadi.\n\n"
    "<b>1️⃣ Bitim qanday oʻtadi?</b>\n"
    "• Xaridor va sotuvchi shartlarni kelishib oladi.\n"
    "• Xaridor pulni garantshga yuboradi (garant pulni ushlab turadi).\n"
    "• Sotuvchi akkaunt maʼlumotlarini beradi.\n"
    "• Xaridor akkauntni tekshiradi va Moonton hisobini toʻliq oʻziga oʻtkazadi.\n"
    "• Tasdiqlangach, garant pulni sotuvchiga beradi.\n\n"
    "<b>2️⃣ Moonton akkauntini xavfsiz oʻtkazish roʻyxati</b>\n"
    "✅ Email manzilni xaridorning emailiga oʻzgartirish\n"
    "✅ Telefon raqamni olib tashlash yoki xaridor raqamiga oʻzgartirish\n"
    "✅ Ijtimoiy tarmoq (Facebook/Google) bogʻlanishlarini uzish\n"
    "✅ Barcha qurilmalardan chiqish (Device Management)\n"
    "✅ Parolni oʻzgartirish va ikki bosqichli himoyani yoqish\n"
    "✅ Asl chek / toʻlov tarixini xaridorga topshirish\n"
    "✅ 7 kun davomida akkauntga kirish imkoniyatini tekshirish\n\n"
    "<b>3️⃣ Nimalarga eʼtibor berish kerak?</b>\n"
    "⚠️ Faqat rasmiy garant bilan ishlang.\n"
    "⚠️ Shaxsiy maʼlumotlaringizni uchinchi shaxslarga bermang.\n"
    "⚠️ «Avval pul, keyin akkaunt» yoki aksincha — garantsiz qilmang.\n"
    "⚠️ Screenshot, chat tarixi va toʻlov chekini saqlab qoʻying.\n\n"
    f"🤝 Garant bilan bogʻlanish uchun quyidagi tugmani bosing 👇"
)


@router.message(StateFilter(None), F.text == BTN_GARANT)
async def show_garant(message: Message) -> None:
    """Garant haqida ma'lumot beradi (xabar doimiy saqlanadi)."""
    with permanent():
        if message.chat.type != "private":
            await message.answer(
                "🛡️ Garant xizmatini botning shaxsiy chatida oching 👇",
                reply_markup=private_chat_kb("garant", "🔒 Shaxsiy chatda ochish"),
                disable_web_page_preview=True,
            )
            return
        await message.answer(
            GARANT_TEXT, reply_markup=garant_kb(), disable_web_page_preview=True
        )
