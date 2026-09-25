"""«⚙️ Sozlamalar» paneli — botni to'liq bot ichidan boshqarish.

Bu bo'lim orqali loyihani sotib olgan kishi `.env` fayliga tegmagan holda
narx chegaralari, vaqtlar, kanal, garant akkaunti, anti-flood, xabarlar
umri, zaxira nusxa va **AI moderatsiyani** (kalit bilan birga) sozlay oladi.

Qiymatlar `settings` jadvalida saqlanadi; `.env` dagi qiymatlar standart
bo'lib qoladi va «↩️ Standart qiymat» tugmasi bilan qaytariladi.
"""

from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

import ai
from database import db
from handlers.common import esc, menu_button_guard, safe_delete
from keyboards import (
    ai_panel_kb,
    main_menu_kb,
    setting_detail_kb,
    settings_groups_kb,
    settings_items_kb,
)
from settings import SettingsError, settings
from states import SettingsFSM

logger = logging.getLogger(__name__)

router = Router(name="settings_panel")

PANEL_TEXT = (
    "⚙️ <b>Bot sozlamalari</b>\n"
    "━━━━━━━━━━━━━━━━━━━━\n"
    "Barcha sozlamalar bot ichidan boshqariladi — `.env` faylini "
    "oʻzgartirish shart emas.\n\n"
    "• ✏️ belgisi — qiymat bot ichidan oʻzgartirilgan\n"
    "• • belgisi — hozircha `.env` dagi standart qiymat ishlatilmoqda\n\n"
    "Oʻzgartirmoqchi boʻlgan boʻlimni tanlang 👇"
)

VALUE_PROMPT = (
    "✏️ <b>{label}</b>\n\n"
    "📌 Hozirgi qiymat: <b>{current}</b>\n"
    "📖 Manba: {source}\n\n"
    "{hint}\n\n"
    "Bekor qilish uchun «❌ Bekor qilish» tugmasini bosing."
)


def _is_admin(user_id: int | None) -> bool:
    return db.is_admin(user_id)


async def _deny(callback: CallbackQuery) -> None:
    await callback.answer("⛔️ Bu amal faqat administrator uchun.", show_alert=True)


async def _render(callback: CallbackQuery, text: str, markup) -> None:
    """Callback xabarini xavfsiz tahrirlaydi (bo'lmasa yangi xabar yuboradi)."""
    if not isinstance(callback.message, Message):
        return
    try:
        await callback.message.edit_text(text, reply_markup=markup, disable_web_page_preview=True)
    except TelegramAPIError:
        try:
            await callback.message.answer(text, reply_markup=markup, disable_web_page_preview=True)
        except TelegramAPIError:
            pass


# ---------------------------------------------------------------------------
# Navigatsiya
# ---------------------------------------------------------------------------
@router.callback_query(F.data == "cfg_home")
async def cfg_home(callback: CallbackQuery, state: FSMContext) -> None:
    """Guruhlar ro'yxatini ko'rsatadi."""
    if not _is_admin(callback.from_user.id):
        await _deny(callback)
        return

    await state.clear()
    await callback.answer()
    text = PANEL_TEXT + (
        f"\n\n✏️ Oʻzgartirilgan sozlamalar: <b>{settings.overridden_count()}</b> ta"
        if settings.overridden_count()
        else ""
    )
    await _render(callback, text, settings_groups_kb())


async def _render_group(callback: CallbackQuery, group: str) -> bool:
    """Guruh sahifasini chizadi. Guruh topilmasa `False`."""
    items = settings.group_items(group)
    if not items:
        return False
    restart_note = (
        "\n\n⏳ Bu boʻlimdagi oʻzgarishlar bot qayta ishga tushgach kuchga kiradi."
        if any(item.restart for item in items)
        else ""
    )
    await _render(
        callback,
        f"{settings.group_label(group)}\n━━━━━━━━━━━━━━━━━━━━\n"
        "Qiymatni oʻzgartirish uchun tegishli tugmani bosing 👇" + restart_note,
        settings_items_kb(group),
    )
    return True


@router.callback_query(F.data.startswith("cfg_g|"))
async def cfg_group(callback: CallbackQuery, state: FSMContext) -> None:
    """Guruhdagi sozlamalar ro'yxatini ko'rsatadi."""
    if not _is_admin(callback.from_user.id):
        await _deny(callback)
        return

    group = (callback.data or "").split("|", 1)[-1]
    await state.clear()
    await callback.answer()
    if not await _render_group(callback, group):
        await callback.answer("❌ Boʻlim topilmadi.", show_alert=True)


@router.callback_query(F.data.startswith("cfg_s|"))
async def cfg_detail(callback: CallbackQuery, state: FSMContext) -> None:
    """Bitta sozlama tafsilotlari."""
    if not _is_admin(callback.from_user.id):
        await _deny(callback)
        return

    key = (callback.data or "").split("|", 1)[-1]
    try:
        spec = settings.spec(key)
    except SettingsError:
        await callback.answer("❌ Sozlama topilmadi.", show_alert=True)
        return

    await state.clear()
    await callback.answer()

    source = "🤖 bot ichidan" if settings.is_overridden(key) else "📄 .env (standart)"
    lines = [
        f"⚙️ <b>{spec.label}</b>",
        "━━━━━━━━━━━━━━━━━━━━",
        f"📌 Joriy qiymat: <b>{settings.display(key)}</b>",
        f"📖 Manba: {source}",
        f"🔑 Kalit: <code>{spec.key}</code>",
    ]
    if spec.description:
        lines.append(f"📝 {spec.description}")
    if spec.kind in ("int", "float"):
        lines.append(f"📏 Ruxsat etilgan oraliq: {spec.minimum} – {spec.maximum}")
    if spec.restart:
        lines.append("⏳ Oʻzgarish bot qayta ishga tushgach kuchga kiradi.")
    if spec.key == "AI_API_KEY":
        lines.append("🔒 Kalit bazada saqlanadi va faqat niqoblangan holda koʻrsatiladi.")

    await _render(callback, "\n".join(lines), setting_detail_kb(spec, spec.group))


# ---------------------------------------------------------------------------
# O'zgartirish
# ---------------------------------------------------------------------------
@router.callback_query(F.data.startswith("cfg_edit|"))
async def cfg_edit(callback: CallbackQuery, state: FSMContext) -> None:
    """Matn/son/kalit kiritish jarayonini boshlaydi."""
    if not _is_admin(callback.from_user.id):
        await _deny(callback)
        return

    key = (callback.data or "").split("|", 1)[-1]
    try:
        spec = settings.spec(key)
    except SettingsError:
        await callback.answer("❌ Sozlama topilmadi.", show_alert=True)
        return

    if spec.kind == "bool":
        await callback.answer("ℹ️ Bu sozlama almashtirish tugmasi bilan boshqariladi.")
        return

    await state.clear()
    await state.set_state(SettingsFSM.waiting_value)
    await state.update_data(cfg_key=key)
    await callback.answer()

    if isinstance(callback.message, Message):
        source = "🤖 bot ichidan" if settings.is_overridden(key) else "📄 .env (standart)"
        await callback.message.answer(
            VALUE_PROMPT.format(
                label=esc(spec.label),
                current=esc(settings.display(key)),
                source=source,
                hint=esc(settings.edit_hint(key)),
            )
        )


@router.callback_query(F.data.startswith("cfg_toggle|"))
async def cfg_toggle(callback: CallbackQuery) -> None:
    """Mantiqiy sozlamani yoqadi/o'chiradi."""
    if not _is_admin(callback.from_user.id):
        await _deny(callback)
        return

    key = (callback.data or "").split("|", 1)[-1]
    try:
        spec = settings.spec(key)
    except SettingsError:
        await callback.answer("❌ Sozlama topilmadi.", show_alert=True)
        return

    ok, text = await settings.set(key, "false" if settings.get_bool(key) else "true")
    note = " (⏳ restart kerak)" if spec.restart else ""
    message = f"✅ {spec.label}: {settings.display(key)}{note}" if ok else text
    await callback.answer(message[:190])
    await _render_group(callback, spec.group)


@router.callback_query(F.data.startswith("cfg_reset|"))
async def cfg_reset(callback: CallbackQuery) -> None:
    """Sozlamani standart qiymatga qaytaradi."""
    if not _is_admin(callback.from_user.id):
        await _deny(callback)
        return

    key = (callback.data or "").split("|", 1)[-1]
    try:
        spec = settings.spec(key)
    except SettingsError:
        await callback.answer("❌ Sozlama topilmadi.", show_alert=True)
        return

    was_overridden = await settings.reset(key)
    await callback.answer(
        "↩️ Standartga qaytarildi." if was_overridden else "ℹ️ Allaqachon standart qiymat."
    )
    await _render(
        callback,
        f"↩️ <b>{esc(spec.label)}</b> standart qiymatga qaytarildi.\n"
        f"📌 Joriy qiymat: <b>{settings.display(key)}</b>\n"
        f"📖 Manba: 📄 .env (standart)",
        setting_detail_kb(spec, spec.group),
    )


@router.callback_query(F.data.startswith("cfg_resetg|"))
async def cfg_reset_group(callback: CallbackQuery) -> None:
    """Guruhdagi barcha sozlamalarni standartga qaytaradi."""
    if not _is_admin(callback.from_user.id):
        await _deny(callback)
        return

    group = (callback.data or "").split("|", 1)[-1]
    count = await settings.reset_group(group)
    await callback.answer(f"↩️ {count} ta sozlama standartga qaytarildi.")
    await _render(
        callback,
        f"{settings.group_label(group)}\n━━━━━━━━━━━━━━━━━━━━\n"
        f"↩️ {count} ta sozlama standart qiymatga qaytarildi.",
        settings_items_kb(group),
    )


@router.message(SettingsFSM.waiting_value, F.text)
async def cfg_value(message: Message, state: FSMContext, bot: Bot) -> None:
    """Kiritilgan qiymatni tekshirib saqlaydi."""
    if not _is_admin(message.from_user.id if message.from_user else None):
        return

    if menu_button_guard(message):
        await message.answer(
            "ℹ️ Avval joriy amalni yakunlang yoki «❌ Bekor qilish» tugmasini bosing."
        )
        return

    data = await state.get_data()
    key = str(data.get("cfg_key") or "")
    text = (message.text or "").strip()

    try:
        spec = settings.spec(key)
    except SettingsError:
        await state.clear()
        await message.answer(
            "⚠️ Sozlama yoʻqolib qoldi. «⚙️ Sozlamalar» boʻlimidan qaytadan kiriting.",
            reply_markup=main_menu_kb(),
        )
        return

    # Maxfiy qiymatlarni chatda qoldirmaymiz
    if spec.kind == "secret":
        await safe_delete(bot, message.chat.id, message.message_id)

    ok, answer = await settings.set(key, text)
    if not ok:
        await message.answer(f"{answer}\n\nQaytadan urinib koʻring.")
        return

    await state.clear()
    note = "\n\n⏳ Oʻzgarish bot qayta ishga tushgach kuchga kiradi." if spec.restart else ""
    await message.answer(
        f"{answer}{note}\n\n"
        f"📌 Joriy qiymat: <b>{settings.display(key)}</b>\n"
        f"📖 Manba: 🤖 bot ichidan",
        reply_markup=main_menu_kb(),
    )


@router.message(SettingsFSM.waiting_value)
async def cfg_value_fallback(message: Message) -> None:
    """Qiymat o'rniga boshqa turdagi xabar kelsa."""
    await message.answer("✍️ Iltimos, qiymatni matn koʻrinishida yuboring.")


# ---------------------------------------------------------------------------
# AI
# ---------------------------------------------------------------------------
@router.callback_query(F.data == "cfg_ai_test")
async def cfg_ai_test(callback: CallbackQuery, bot: Bot) -> None:
    """AI kaliti va ulanishni tekshiradi."""
    if not _is_admin(callback.from_user.id):
        await _deny(callback)
        return

    await callback.answer("🔌 Tekshirilmoqda…")
    if not isinstance(callback.message, Message):
        return

    status = ai.config_summary()
    try:
        reply = await ai.test_connection()
    except ai.AIError as exc:
        await callback.message.answer(
            "❌ <b>AI ulanishi ishlamadi</b>\n\n"
            f"📌 Holat: {status}\n"
            f"🛠 Xato: {esc(str(exc))}\n\n"
            "Kalitni, manzilni (`AI_BASE_URL`) va modelni tekshiring."
        )
        return

    await callback.message.answer(
        "✅ <b>AI ulanishi ishlaydi!</b>\n\n"
        f"📌 Holat: {status}\n"
        f"🤖 Javob: <code>{esc(reply)}</code>"
    )


@router.callback_query(F.data == "cfg_ai_models")
async def cfg_ai_models(callback: CallbackQuery) -> None:
    """Kalit ishlatadigan provayderda mavjud modellarni ro'yxatlaydi."""
    if not _is_admin(callback.from_user.id):
        await _deny(callback)
        return

    await callback.answer("📋 Modellar yuklanmoqda…")
    if not isinstance(callback.message, Message):
        return

    try:
        models = await ai.list_models()
    except ai.AIError as exc:
        await callback.message.answer(
            "❌ <b>Modellarni olib boʻlmadi</b>\n\n"
            f"🛠 Xato: {esc(str(exc))}\n\n"
            "Avval kalitni kiriting, keyin «🔌 Ulanishni tekshirish» bilan "
            "tekshirib koʻring."
        )
        return

    current = str(settings.get("AI_MODEL") or "")
    text = (
        "📋 <b>Mavjud modellar</b>\n\n"
        f"🔌 Provayder: {esc(ai.PROVIDER_LABELS[ai.provider()])}\n"
        f"⚙️ Joriy model: <code>{esc(current or ai.active_model())}</code>\n"
        f"📊 Jami: <b>{len(models)}</b>\n\n"
    )
    shown = models[:25]
    text += "\n".join(f"• <code>{esc(name)}</code>" for name in shown)
    if len(models) > len(shown):
        text += f"\n\n… va yana {len(models) - len(shown)} ta."

    text += (
        "\n\nℹ️ Kerakli modelni «🤖 AI moderatsiya» → «AI modeli» orqali "
        "kiriting."
    )
    await callback.message.answer(
        text, disable_web_page_preview=True, reply_markup=ai_panel_kb()
    )


@router.callback_query(F.data == "cfg_ai_find")
async def cfg_ai_find(callback: CallbackQuery) -> None:
    """Kalit qaysi provayderda ishlashini aniqlaydi."""
    if not _is_admin(callback.from_user.id):
        await _deny(callback)
        return

    await callback.answer("🔎 Texhirilmoqda…")
    if not isinstance(callback.message, Message):
        return

    try:
        results = await ai.probe_endpoints()
    except ai.AIError as exc:
        await callback.message.answer(f"❌ <b>Tekshira olmadi</b>\n\n🛠 Xato: {esc(str(exc))}")
        return

    working = [item for item in results if item[2].startswith("✅")]
    lines = ["🔎 <b>Kalit qayerda ishlaydi?</b>\n"]
    for base, name, outcome in results:
        lines.append(f"{outcome} <b>{esc(name)}</b> — <code>{esc(base)}</code>")

    if working:
        base, name, _ = working[0]
        lines.append(
            f"\n\n✅ Topildi: <b>{esc(name)}</b>\n"
            f"«AI manzili (base URL)» sozlamasiga quyidagini yozing:\n"
            f"<code>{esc(base)}</code>\n\n"
            "Kalitni aynan shu provayderdan olgan bo'lishingiz kerak."
        )
    else:
        lines.append(
            "\n\n❌ Hech qanday odiiy provayderda ishlamadi. Ehtimol kalit "
            "notoʻgʻri yoki bu maxsus xizmat kaliti (masalan Google).\n"
            "Google kaliti boʻlsa «AI provayderi» sozlamasini <code>gemini</code> "
            "qiling."
        )

    await callback.message.answer(
        "\n".join(lines), disable_web_page_preview=True, reply_markup=ai_panel_kb()
    )


__all__ = ["router"]
