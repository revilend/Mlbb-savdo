"""Administrator paneli.

Moderatsiya (tasdiqlash/rad etish), xabar tarqatish, majburiy kanal,
foydalanuvchini qidirish, shaxsiy xabar yuborish va qora ro'yxat.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Optional

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, FSInputFile, Message

import ai
import config
from database import db
from handlers.common import (
    ADMIN_PANEL_TEXT,
    default_header,
    esc,
    get_channel_id,
    get_channel_link,
    get_required_channel,
    get_required_channel_link,
    send_listing_card,
    seller_label_of,
    status_label,
    user_label,
)
from keyboards import (
    admin_panel_kb,
    ai_panel_kb,
    admins_kb,
    cancel_kb,
    channels_kb,
    deal_status_kb,
    dm_user_kb,
    listing_action_kb,
    main_menu_kb,
    moderation_kb,
    single_button_kb,
)
from handlers.subscriptions import notify_subscribers
from settings import settings
from states import AdminFSM

logger = logging.getLogger(__name__)

router = Router(name="admin")

CHANNEL_PROMPT = (
    "⚙️ <b>Majburiy kanalni sozlash</b>\n\n"
    "Kanal username ini (@belgisi bilan yoki belgisiz) yoki "
    "<code>-100...</code> koʻrinishidagi ID sini yuboring.\n\n"
    "⚠️ Bot kanalda administrator boʻlishi shart, aks holda aʼzolikni "
    "tekshirib boʻlmaydi.\n\n"
    "Bekor qilish uchun «❌ Bekor qilish» tugmasini bosing."
)

POST_CHANNEL_PROMPT = (
    "📣 <b>Eʼlon kanalini sozlash</b>\n\n"
    "Tasdiqlangan eʼlonlar shu kanalga joylanadi.\n\n"
    "Kanal username ini (@belgisi bilan yoki belgisiz), <code>-100...</code> "
    "ID sini yuboring yoki kanaldan istalgan xabarni <b>forward</b> qilib "
    "yuboring.\n\n"
    "⚠️ Bot kanalda administrator boʻlishi shart.\n\n"
    "Bekor qilish uchun «❌ Bekor qilish» tugmasini bosing."
)

ADMIN_ADD_PROMPT = (
    "➕ <b>Yangi admin qoʻshish</b>\n\n"
    "Yangi administratorning <b>Telegram ID</b> sini yoki botdagi "
    "<b>username</b> ini yuboring.\n\n"
    "Masalan: <code>123456789</code> yoki <code>@username</code>\n\n"
    "⚠️ U botga kamida bir marta /start bosgan boʻlishi kerak."
)

ADMIN_REMOVE_PROMPT = (
    "➖ <b>Adminni oʻchirish</b>\n\n"
    "Oʻchiriladigan administratorning <b>ID</b> sini yuboring.\n\n"
    "Masalan: <code>123456789</code>\n\n"
    "⚠️ Asosiy administratorni (.env dagi ADMIN_ID) oʻchirib boʻlmaydi."
)

LOOKUP_PROMPT = (
    "👤 <b>Foydalanuvchi qidirish</b>\n\n"
    "Foydalanuvchining Telegram ID sini yuboring (masalan: <code>123456789</code>)."
)

BAN_PROMPT = (
    "🚫 <b>Qora roʻyxatga kiritish</b>\n\n"
    "Firibgar deb topilgan foydalanuvchining username ini yoki ID sini yuboring.\n\n"
    "Masalan: <code>@scammer_uz</code> yoki <code>123456789</code>"
)

BAN_REASON_PROMPT = (
    "📝 <b>Sababni yozing.</b>\n\n"
    "Masalan: <i>Pulni olib akkauntni bermadi, 2 ta shikoyat bor.</i>"
)

BROADCAST_PROMPT = (
    "📢 <b>Xabar tarqatish</b>\n\n"
    "Barcha foydalanuvchilarga yuboriladigan xabarni joʻnating.\n"
    "Matn, rasm, video yoki hujjat boʻlishi mumkin.\n\n"
    "⚠️ Yuborgandan keyin uni qaytarib boʻlmaydi."
)

DM_PROMPT = "✉️ Foydalanuvchiga yuboriladigan xabarni joʻnating."


def is_admin(user_id: Optional[int]) -> bool:
    """Foydalanuvchi administrator ekanmi (bot ichida qoʻshilganlar ham)."""
    return db.is_admin(user_id)


async def _deny(callback: CallbackQuery) -> None:
    """Ruxsat yo'qligini bildiradi."""
    await callback.answer("⛔️ Bu amal faqat administrator uchun.", show_alert=True)


async def approve_listing(bot: Bot, listing_id: int) -> tuple[bool, str]:
    """E'lonni tasdiqlab kanalga joylaydi."""
    listing = await db.get_listing(listing_id)
    if listing is None:
        return False, "Eʼlon topilmadi."

    if listing.get("status") == "active":
        return False, "Bu eʼlon allaqachon aktiv."

    channel_id = await get_channel_id()
    if not channel_id:
        return False, "Kanal sozlanmagan. «⚙️ Majburiy kanal» boʻlimidan sozlang."

    header = f"🆕 <b>Yangi eʼlon</b>\n{default_header(listing)}"

    try:
        message = await send_listing_card(
            bot,
            channel_id,
            listing,
            markup=listing_action_kb(listing),
            header=header,
            seller_label=await seller_label_of(listing),
        )
    except TelegramAPIError as exc:
        logger.error("Eʼlonni kanalga joylab boʻlmadi (#%s): %s", listing_id, exc)
        return False, f"Kanalga joylashda xatolik: {esc(str(exc))}"

    await db.update_listing_status(listing_id, "active")
    await db.touch_listing_expiry(listing_id)
    if message is not None:
        await db.set_channel_message_id(listing_id, message.message_id)
    await db.update_bump_time(listing_id)

    # Obuna bo'lganlarga mos e'lon haqida xabar beramiz
    active = await db.get_listing(listing_id) or listing
    try:
        await notify_subscribers(bot, active)
    except Exception as exc:  # obuna xatosi e'lonni tasdiqlashga xalaqit bermasin
        logger.warning("Obunachilarga xabar yuborilmadi (#%s): %s", listing_id, exc)

    owner = await db.get_user(int(listing["user_id"]))
    owner_name = user_label(
        int(listing["user_id"]), (owner or {}).get("username"), (owner or {}).get("full_name")
    )

    try:
        await bot.send_message(
            int(listing["user_id"]),
            "🎉 <b>Tabriklaymiz! Eʼloningiz tasdiqlandi va kanalga chiqarildi.</b>\n\n"
            f"🆔 Eʼlon raqami: <b>#{listing_id}</b>\n"
            f"📌 Holat: {status_label('active')}\n\n"
            "Eʼloningizni «📋 Mening eʼlonlarim» boʻlimida boshqarishingiz mumkin: "
            "24 soatda bir marta koʻtarish (UP) yoki sotildi deb belgilash.",
        )
    except TelegramAPIError as exc:
        logger.warning("Eʼlon egasiga xabar yuborilmadi (#%s): %s", listing_id, exc)

    return True, f"#{listing_id} eʼloni kanalga chiqarildi ({esc(owner_name)})."


async def reject_listing(bot: Bot, listing_id: int, reason: str = "") -> tuple[bool, str]:
    """E'lonni rad etadi va egasiga xabar beradi."""
    listing = await db.get_listing(listing_id)
    if listing is None:
        return False, "Eʼlon topilmadi."

    await db.update_listing_status(listing_id, "rejected")

    text = (
        "😔 <b>Afsuski, eʼloningiz rad etildi.</b>\n\n"
        f"🆔 Eʼlon raqami: <b>#{listing_id}</b>\n"
    )
    if reason:
        text += f"📝 Sababi: {esc(reason)}\n"
    text += "\nQoidalarga mos ravishda qaytadan eʼlon joylashingiz mumkin."

    try:
        await bot.send_message(int(listing["user_id"]), text)
    except TelegramAPIError as exc:
        logger.warning("Rad etish xabari yuborilmadi (#%s): %s", listing_id, exc)

    return True, f"#{listing_id} eʼloni rad etildi."


# ---------------------------------------------------------------------------
# Moderatsiya
# ---------------------------------------------------------------------------
@router.callback_query(F.data.startswith("app_"))
async def approve_cb(callback: CallbackQuery, bot: Bot) -> None:
    """«✅ Kanalga chiqarish» tugmasi."""
    if not is_admin(callback.from_user.id):
        await _deny(callback)
        return

    raw_id = (callback.data or "").split("_", 1)[-1]
    if not raw_id.isdigit():
        await callback.answer("❌ Notoʻgʻri soʻrov.", show_alert=True)
        return

    await callback.answer("⏳ Joylanmoqda…")
    ok, message = await approve_listing(bot, int(raw_id))

    if isinstance(callback.message, Message):
        prefix = "✅ " if ok else "⚠️ "
        try:
            await callback.message.edit_text(prefix + message, disable_web_page_preview=True)
        except TelegramAPIError:
            await callback.message.answer(prefix + message)


@router.callback_query(F.data.startswith("rej_"))
async def reject_cb(callback: CallbackQuery, bot: Bot) -> None:
    """«❌ Rad etish» tugmasi."""
    if not is_admin(callback.from_user.id):
        await _deny(callback)
        return

    raw_id = (callback.data or "").split("_", 1)[-1]
    if not raw_id.isdigit():
        await callback.answer("❌ Notoʻgʻri soʻrov.", show_alert=True)
        return

    await callback.answer("⏳ Bajarilmoqda…")
    ok, message = await reject_listing(bot, int(raw_id))

    if isinstance(callback.message, Message):
        prefix = "✅ " if ok else "⚠️ "
        try:
            await callback.message.edit_text(prefix + message, disable_web_page_preview=True)
        except TelegramAPIError:
            await callback.message.answer(prefix + message)


# ---------------------------------------------------------------------------
# Admin panel
# ---------------------------------------------------------------------------
@router.callback_query(F.data == "adm_back")
async def adm_back(callback: CallbackQuery, state: FSMContext) -> None:
    """Asosiy admin panelga qaytish."""
    if not is_admin(callback.from_user.id):
        await _deny(callback)
        return

    await state.clear()
    await callback.answer()
    if isinstance(callback.message, Message):
        try:
            await callback.message.edit_text(ADMIN_PANEL_TEXT, reply_markup=admin_panel_kb())
        except TelegramAPIError:
            await callback.message.answer(ADMIN_PANEL_TEXT, reply_markup=admin_panel_kb())


# ---------------------------------------------------------------------------
# AI moderatsiya boshqaruvi
# ---------------------------------------------------------------------------
async def _render_ai_panel(callback: CallbackQuery, note: str = "") -> None:
    """AI boshqaruv panelini chizadi."""
    text = (
        "🤖 <b>AI moderatsiya</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"Holat: <b>{'✅ yoqilgan' if settings.get_bool('AI_ENABLED') else '⛔️ oʻchirilgan'}</b>\n"
        f"Kalit: <code>{esc(settings.display('AI_API_KEY'))}</code>\n"
        f"Model: <code>{esc(str(settings.get('AI_MODEL') or '—'))}</code>\n"
        f"Manzil: <code>{esc(str(settings.get('AI_BASE_URL') or '—'))}</code>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"Avto-tasdiqlash: {settings.display('AI_AUTO_APPROVE')}\n"
        f"Avto-rad (firibgarlik): {settings.display('AI_REJECT_SCAMS')}\n"
        f"Minimal ishonch: <b>{settings.display('AI_MIN_CONFIDENCE')}</b>"
    )
    if note:
        text += f"\n\n{note}"
    text += (
        "\n\nHar bir yangi e'lon AI orqali tekshiriladi va natija shu yerda "
        "koʻrinadi. E'lon kartochkasidagi «🤖 AI tekshiruvi (qoʻlda)» tugmasi "
        "bilan istalgan vaqtda qayta tekshirish mumkin."
    )

    if not isinstance(callback.message, Message):
        return
    try:
        await callback.message.edit_text(
            text, reply_markup=ai_panel_kb(), disable_web_page_preview=True
        )
    except TelegramAPIError:
        try:
            await callback.message.answer(
                text, reply_markup=ai_panel_kb(), disable_web_page_preview=True
            )
        except TelegramAPIError:
            pass


@router.callback_query(F.data == "adm_ai")
async def adm_ai(callback: CallbackQuery, state: FSMContext) -> None:
    """«🤖 AI moderatsiya» boshqaruv paneli."""
    if not is_admin(callback.from_user.id):
        await _deny(callback)
        return

    await state.clear()
    await callback.answer()
    await _render_ai_panel(callback)


@router.callback_query(F.data == "adm_ai_toggle")
async def adm_ai_toggle(callback: CallbackQuery) -> None:
    """AI tekshiruvni bir tugma bilan yoqadi yoki oʻchiradi."""
    if not is_admin(callback.from_user.id):
        await _deny(callback)
        return

    turning_on = not settings.get_bool("AI_ENABLED")
    ok, message = await settings.set("AI_ENABLED", "true" if turning_on else "false")
    if not ok:
        await callback.answer(message[:190], show_alert=True)
        return

    if not turning_on:
        note = "⛔️ AI tekshiruv oʻchirildi. E'lonlar faqat qoʻlda tekshiriladi."
        await callback.answer("⛔️ AI oʻchirildi")
    elif not str(settings.get("AI_API_KEY") or "").strip():
        note = (
            "✅ AI yoqildi, lekin <b>API kaliti kiritilmagan</b> — tekshiruv "
            "ishlashi uchun «🔑 AI API kalitini kiritish» tugmasini bosing."
        )
        await callback.answer("✅ Yoqildi — kalit kerak", show_alert=True)
    else:
        note = f"✅ AI tekshiruv yoqildi. Holat: {ai.config_summary()}"
        await callback.answer("✅ AI yoqildi")

    await _render_ai_panel(callback, note=note)


@router.callback_query(F.data.startswith("ai_chk_"))
async def ai_check_cb(callback: CallbackQuery, bot: Bot) -> None:
    """«🤖 AI tekshiruvi (qoʻlda)» tugmasi — bitta e'lonni qayta tekshiradi."""
    if not is_admin(callback.from_user.id):
        await _deny(callback)
        return

    raw_id = (callback.data or "").split("_", 2)[-1]
    if not raw_id.isdigit():
        await callback.answer("❌ Notoʻgʻri soʻrov.", show_alert=True)
        return

    await callback.answer("🤖 AI tekshirilmoqda…")

    # Aylanma importdan qochish uchun funksiya ichida chaqiriladi
    from handlers.moderation import manual_ai_check

    text, decided = await manual_ai_check(bot, int(raw_id))
    if not isinstance(callback.message, Message):
        return
    try:
        await callback.message.edit_text(
            text,
            reply_markup=None if decided else moderation_kb(int(raw_id)),
            disable_web_page_preview=True,
        )
    except TelegramAPIError:
        await callback.message.answer(text, disable_web_page_preview=True)


@router.callback_query(F.data == "adm_stats")
async def adm_stats(callback: CallbackQuery) -> None:
    """To'liq statistika."""
    if not is_admin(callback.from_user.id):
        await _deny(callback)
        return

    stats = await db.get_detailed_stats()
    text = (
        "📊 <b>Toʻliq statistika</b>\n\n"
        f"👥 Foydalanuvchilar: <b>{stats['users']}</b> "
        f"(bloklangan: {stats['banned']})\n"
        f"📋 Jami eʼlonlar: <b>{stats['listings']}</b>\n"
        f"⏳ Moderatsiya kutayotgan: <b>{stats['pending']}</b>\n"
        f"🟢 Aktiv: <b>{stats['active']}</b>\n"
        f"⌛️ Muddati tugagan: <b>{stats.get('expired', 0)}</b>\n"
        f"🔴 Sotilgan: <b>{stats['sold']}</b>\n"
        f"🚫 Rad etilgan: <b>{stats['rejected']}</b>\n"
        f"🛒 Xaridor soʻrovlari: <b>{stats['buy_requests']}</b>\n"
        f"⭐️ Sevimlilarga qoʻshilganlar: <b>{stats['favorites']}</b>\n"
        f"📝 Sharhlar: <b>{stats.get('reviews', 0)}</b>\n"
        f"💬 Takliflar: <b>{stats.get('offers', 0)}</b> "
        f"(kutilmoqda: {stats.get('pending_offers', 0)})\n"
        f"🤝 Bitimlar: <b>{stats.get('deals', 0)}</b> "
        f"(faol: {stats.get('open_deals', 0)})\n"
        f"🚫 Qora roʻyxat: <b>{stats['blacklist']}</b>"
    )

    await callback.answer()
    if isinstance(callback.message, Message):
        try:
            await callback.message.edit_text(
                text, reply_markup=single_button_kb("⬅️ Orqaga", "adm_back")
            )
        except TelegramAPIError:
            await callback.message.answer(
                text, reply_markup=single_button_kb("⬅️ Orqaga", "adm_back")
            )


@router.callback_query(F.data == "adm_today")
async def adm_today(callback: CallbackQuery) -> None:
    """Bugungi qisqa hisobot (kunlik digest bilan bir xil maʼlumot)."""
    if not is_admin(callback.from_user.id):
        await _deny(callback)
        return

    new_users, new_listings, sold_listings = await db.get_today_stats()
    text = (
        "📊 <b>KUNLIK HISOBOT</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 Bugungi yangi a'zolar: <b>+{new_users}</b>\n"
        f"📝 Yangi eʼlonlar: <b>{new_listings}</b>\n"
        f"✅ Sotilgan akkauntlar: <b>{sold_listings}</b>\n"
        "━━━━━━━━━━━━━━━━━━━━"
    )

    await callback.answer()
    if isinstance(callback.message, Message):
        try:
            await callback.message.edit_text(
                text, reply_markup=single_button_kb("⬅️ Orqaga", "adm_back")
            )
        except TelegramAPIError:
            await callback.message.answer(
                text, reply_markup=single_button_kb("⬅️ Orqaga", "adm_back")
            )


@router.callback_query(F.data == "adm_analytics")
async def adm_analytics(callback: CallbackQuery) -> None:
    """Oxirgi 7 kunlik faollik va eng faol sotuvchilar."""
    if not is_admin(callback.from_user.id):
        await _deny(callback)
        return

    days = await db.get_daily_activity(7)
    top_sellers = await db.get_top_sellers(30, 5)

    totals = {
        "users": sum(day["users"] for day in days),
        "listings": sum(day["listings"] for day in days),
        "sold": sum(day["sold"] for day in days),
    }
    peak = max((day["listings"] for day in days), default=0)

    lines = [
        "📈 <b>Analitika — oxirgi 7 kun</b>",
        "━━━━━━━━━━━━━━━━━━━━",
        f"👥 Yangi aʼzolar: <b>+{totals['users']}</b>",
        f"📝 Yangi eʼlonlar: <b>{totals['listings']}</b>",
        f"✅ Sotilganlar: <b>{totals['sold']}</b>",
        "━━━━━━━━━━━━━━━━━━━━",
    ]
    for day in days:
        bar = "▓" * (min(10, round(day["listings"] / peak * 10)) if peak else 0)
        lines.append(
            f"<code>{day['date']}</code>  "
            f"👥{day['users']:<3} 📝{day['listings']:<3} ✅{day['sold']:<3} {bar}"
        )

    lines.append("━━━━━━━━━━━━━━━━━━━━")
    if top_sellers:
        lines.append("🏆 <b>Eng faol sotuvchilar (30 kun)</b>")
        for index, seller in enumerate(top_sellers, start=1):
            user = await db.get_user(int(seller["user_id"]))
            label = user_label(
                int(seller["user_id"]),
                (user or {}).get("username"),
                (user or {}).get("full_name"),
            )
            lines.append(f"{index}. {esc(label)} — <b>{seller['count']}</b> ta")
    else:
        lines.append("🏆 Hozircha sotuv statistikasi yoʻq.")

    text = "\n".join(lines)
    await callback.answer()
    if isinstance(callback.message, Message):
        try:
            await callback.message.edit_text(
                text, reply_markup=single_button_kb("⬅️ Orqaga", "adm_back")
            )
        except TelegramAPIError:
            await callback.message.answer(
                text, reply_markup=single_button_kb("⬅️ Orqaga", "adm_back")
            )


@router.callback_query(F.data == "adm_backup")
async def adm_backup(callback: CallbackQuery, bot: Bot) -> None:
    """Bazaning zaxira nusxasini yaratib, adminga yuboradi."""
    if not is_admin(callback.from_user.id):
        await _deny(callback)
        return

    await callback.answer("💾 Nusxa tayyorlanmoqda…")

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")
    dest = os.path.join(str(settings.get("BACKUP_DIR")), f"market_backup_{stamp}.sqlite3")

    ok = await db.backup_to(dest)
    if not ok:
        if isinstance(callback.message, Message):
            await callback.message.answer("⚠️ Zaxira nusxasini yaratib boʻlmadi.")
        return

    size_kb = max(1, os.path.getsize(dest) // 1024) if os.path.exists(dest) else 0
    try:
        await bot.send_document(
            callback.from_user.id,
            FSInputFile(dest),
            caption=(
                "💾 <b>Zaxira nusxa tayyor</b>\n\n"
                f"📅 {esc(stamp)}\n"
                f"📦 Hajmi: <b>{size_kb} KB</b>"
            ),
        )
    except TelegramAPIError as exc:
        logger.error("Zaxira nusxasini yuborib boʻlmadi: %s", exc)
        if isinstance(callback.message, Message):
            await callback.message.answer(f"❌ Faylni yuborib boʻlmadi: {esc(exc)}")


@router.callback_query(F.data.startswith("dstat_"))
async def deal_status_cb(callback: CallbackQuery, bot: Bot) -> None:
    """Admin bitim holatini o'zgartiradi (garant/yakunlandi/bekor)."""
    if not is_admin(callback.from_user.id):
        await _deny(callback)
        return

    parts = (callback.data or "").split("_", 2)
    if len(parts) < 3:
        await callback.answer("❌ Notoʻgʻri soʻrov.", show_alert=True)
        return

    deal_id_raw, status = parts[1], parts[2]
    if not deal_id_raw.isdigit() or status not in ("garant", "done", "cancelled"):
        await callback.answer("❌ Notoʻgʻri soʻrov.", show_alert=True)
        return

    deal = await db.update_deal_status(int(deal_id_raw), status)
    if deal is None:
        await callback.answer("❌ Bitim topilmadi.", show_alert=True)
        return

    labels = {
        "garant": "🛡️ Bitim garant jarayoniga oʻtdi",
        "done": "✅ Bitim yakunlandi",
        "cancelled": "❌ Bitim bekor qilindi",
    }
    await callback.answer("Holat yangilandi.")
    if isinstance(callback.message, Message):
        try:
            await callback.message.edit_reply_markup(reply_markup=deal_status_kb(int(deal_id_raw)))
        except TelegramAPIError:
            pass
        await callback.message.answer(
            f"{labels[status]}.\n\n🆔 Bitim: <b>#{deal_id_raw}</b>"
        )

    await _notify_deal_parties(bot, deal, labels[status])


async def _notify_deal_parties(bot: Bot, deal: dict, title: str) -> None:
    """Bitim ishtirokchilariga holat o'zgarishini bildiradi."""
    for user_id in {int(deal["seller_id"]), int(deal["buyer_id"])}:
        try:
            await bot.send_message(
                user_id,
                f"{title}\n\n"
                f"🆔 Bitim: <b>#{deal['id']}</b>\n"
                f"📋 Eʼlon: <b>#{deal['listing_id']}</b>\n\n"
                "Holatni «📥 Takliflar va bitimlar» boʻlimida koʻrishingiz mumkin.",
                disable_web_page_preview=True,
            )
        except TelegramAPIError as exc:
            logger.warning("Bitim xabari yuborilmadi (user=%s): %s", user_id, exc)


@router.callback_query(F.data == "adm_broadcast")
async def adm_broadcast(callback: CallbackQuery, state: FSMContext) -> None:
    """Tarqatish jarayonini boshlaydi."""
    if not is_admin(callback.from_user.id):
        await _deny(callback)
        return

    await state.set_state(AdminFSM.broadcast_content)
    await callback.answer()
    if isinstance(callback.message, Message):
        await callback.message.answer(BROADCAST_PROMPT, reply_markup=cancel_kb())


@router.callback_query(F.data == "adm_sub_channel")
async def adm_sub_channel(callback: CallbackQuery, state: FSMContext) -> None:
    """Kanallar bo'limini ochadi (e'lon kanali + majburiy kanal)."""
    if not is_admin(callback.from_user.id):
        await _deny(callback)
        return

    post = await get_channel_id()
    required = await get_required_channel()
    text = (
        "📡 <b>Kanallar boshqaruvi</b>\n\n"
        "Barcha kanallar bot ichidan sozlanadi.\n\n"
        f"📣 Eʼlon kanali: <code>{esc(post or 'sozlanmagan')}</code>\n"
        f"🔒 Majburiy kanal: <code>{esc(required or 'sozlanmagan')}</code>"
    )

    await state.clear()
    await callback.answer()
    if isinstance(callback.message, Message):
        markup = channels_kb(post_set=bool(post), required_set=bool(required))
        try:
            await callback.message.edit_text(text, reply_markup=markup)
        except TelegramAPIError:
            await callback.message.answer(text, reply_markup=markup)


@router.callback_query(F.data == "adm_post_channel")
async def adm_post_channel(callback: CallbackQuery, state: FSMContext) -> None:
    """E'lon kanalini sozlashni boshlaydi."""
    if not is_admin(callback.from_user.id):
        await _deny(callback)
        return

    current = await get_channel_id()
    await state.clear()
    await state.set_state(AdminFSM.set_channel_input)
    await state.update_data(channel_kind="post")
    await callback.answer()
    if isinstance(callback.message, Message):
        await callback.message.answer(
            f"📣 Hozirgi eʼlon kanali: <code>{esc(current or 'sozlanmagan')}</code>\n\n"
            f"{POST_CHANNEL_PROMPT}",
            reply_markup=cancel_kb(),
        )


@router.callback_query(F.data == "adm_sub_required")
async def adm_required_channel(callback: CallbackQuery, state: FSMContext) -> None:
    """Majburiy kanalni sozlashni boshlaydi."""
    if not is_admin(callback.from_user.id):
        await _deny(callback)
        return

    current = await get_required_channel()
    await state.clear()
    await state.set_state(AdminFSM.set_channel_input)
    await state.update_data(channel_kind="required")
    await callback.answer()
    if isinstance(callback.message, Message):
        await callback.message.answer(
            f"🔒 Hozirgi majburiy kanal: <code>{esc(current or 'sozlanmagan')}</code>\n\n"
            f"{CHANNEL_PROMPT}",
            reply_markup=cancel_kb(),
        )


# ---------------------------------------------------------------------------
# Adminlarni boshqarish
# ---------------------------------------------------------------------------
@router.callback_query(F.data == "adm_admins")
async def adm_admins(callback: CallbackQuery, state: FSMContext) -> None:
    """Adminlar ro'yxatini ko'rsatadi."""
    if not is_admin(callback.from_user.id):
        await _deny(callback)
        return

    await state.clear()
    ids = db.get_admin_ids()
    lines = ["👥 <b>Administratorlar</b>\n"]
    for index, admin_id in enumerate(ids, start=1):
        user = await db.get_user(admin_id)
        label = user_label(admin_id, (user or {}).get("username"), (user or {}).get("full_name"))
        role = " (asosiy)" if config.ADMIN_ID and admin_id == int(config.ADMIN_ID) else ""
        lines.append(f"{index}. <code>{admin_id}</code> — {esc(label)}{role}")
    lines.append("\n➕ Qoʻshish yoki ➖ oʻchirish uchun quyidagi tugmalardan foydalaning.")

    await callback.answer()
    if isinstance(callback.message, Message):
        text = "\n".join(lines)
        try:
            await callback.message.edit_text(text, reply_markup=admins_kb())
        except TelegramAPIError:
            await callback.message.answer(text, reply_markup=admins_kb())


@router.callback_query(F.data == "adm_add_admin")
async def adm_add_admin(callback: CallbackQuery, state: FSMContext) -> None:
    """Yangi admin qo'shishni boshlaydi."""
    if not is_admin(callback.from_user.id):
        await _deny(callback)
        return

    await state.clear()
    await state.set_state(AdminFSM.add_admin_id)
    await callback.answer()
    if isinstance(callback.message, Message):
        await callback.message.answer(ADMIN_ADD_PROMPT, reply_markup=cancel_kb())


@router.callback_query(F.data == "adm_remove_admin")
async def adm_remove_admin(callback: CallbackQuery, state: FSMContext) -> None:
    """Adminni o'chirishni boshlaydi."""
    if not is_admin(callback.from_user.id):
        await _deny(callback)
        return

    await state.clear()
    await state.set_state(AdminFSM.remove_admin_id)
    await callback.answer()
    if isinstance(callback.message, Message):
        await callback.message.answer(ADMIN_REMOVE_PROMPT, reply_markup=cancel_kb())


@router.callback_query(F.data == "adm_lookup")
async def adm_lookup(callback: CallbackQuery, state: FSMContext) -> None:
    """Foydalanuvchi qidirishni boshlaydi."""
    if not is_admin(callback.from_user.id):
        await _deny(callback)
        return

    await state.set_state(AdminFSM.lookup_user_id)
    await callback.answer()
    if isinstance(callback.message, Message):
        await callback.message.answer(LOOKUP_PROMPT, reply_markup=cancel_kb())


@router.callback_query(F.data == "adm_ban")
async def adm_ban(callback: CallbackQuery, state: FSMContext) -> None:
    """Qora ro'yxatga kiritishni boshlaydi."""
    if not is_admin(callback.from_user.id):
        await _deny(callback)
        return

    await state.clear()
    await state.set_state(AdminFSM.ban_identifier)
    await callback.answer()
    if isinstance(callback.message, Message):
        await callback.message.answer(BAN_PROMPT, reply_markup=cancel_kb())


@router.callback_query(F.data == "adm_blacklist")
async def adm_blacklist_view(callback: CallbackQuery) -> None:
    """Qora ro'yxatni ko'rsatadi."""
    if not is_admin(callback.from_user.id):
        await _deny(callback)
        return

    records = await db.get_blacklist(limit=30)
    if not records:
        text = "📋 <b>Qora roʻyxat boʻsh.</b>"
    else:
        lines = ["📋 <b>Qora roʻyxat</b> (oxirgi 30 ta)\n"]
        for record in records:
            lines.append(
                f"• <code>{esc(record.get('identifier'))}</code> — "
                f"{esc(record.get('reason') or 'sabab koʻrsatilmagan')}"
            )
        text = "\n".join(lines)

    await callback.answer()
    if isinstance(callback.message, Message):
        try:
            await callback.message.edit_text(
                text, reply_markup=single_button_kb("⬅️ Orqaga", "adm_back")
            )
        except TelegramAPIError:
            await callback.message.answer(
                text, reply_markup=single_button_kb("⬅️ Orqaga", "adm_back")
            )


@router.callback_query(F.data.startswith("adm_dm_"))
async def adm_dm_start(callback: CallbackQuery, state: FSMContext) -> None:
    """Foydalanuvchiga shaxsiy xabar yuborishni boshlaydi."""
    if not is_admin(callback.from_user.id):
        await _deny(callback)
        return

    raw_id = (callback.data or "").split("_", 2)[-1]
    if not raw_id.lstrip("-").isdigit():
        await callback.answer("❌ Notoʻgʻri ID.", show_alert=True)
        return

    target_id = int(raw_id)
    await state.set_state(AdminFSM.send_direct_msg_text)
    await state.update_data(dm_target=target_id)
    await callback.answer("✉️ Xabar matnini kiriting.")
    if isinstance(callback.message, Message):
        await callback.message.answer(
            f"{DM_PROMPT}\n\n👤 Qabul qiluvchi ID: <code>{target_id}</code>",
            reply_markup=cancel_kb(),
        )


# ---------------------------------------------------------------------------
# Admin FSM handlerlari
# ---------------------------------------------------------------------------
@router.message(AdminFSM.broadcast_content)
async def do_broadcast(message: Message, state: FSMContext, bot: Bot) -> None:
    """Xabarni barcha foydalanuvchilarga tarqatadi."""
    if not is_admin(message.from_user.id if message.from_user else None):
        return

    user_ids = await db.get_all_user_ids(only_active=True)
    await state.clear()

    if not user_ids:
        await message.answer("ℹ️ Foydalanuvchilar roʻyxati boʻsh.", reply_markup=main_menu_kb())
        return

    status_message = await message.answer(
        f"📢 Tarqatish boshlandi… (0/{len(user_ids)})"
    )

    success = 0
    failed = 0

    for index, user_id in enumerate(user_ids, start=1):
        if db.is_admin(user_id):
            continue
        try:
            await bot.copy_message(
                chat_id=user_id,
                from_chat_id=message.chat.id,
                message_id=message.message_id,
            )
            success += 1
        except TelegramForbiddenError:
            failed += 1
        except TelegramAPIError as exc:
            failed += 1
            logger.debug("Tarqatishda xatolik (user=%s): %s", user_id, exc)

        if index % 25 == 0 and status_message is not None:
            try:
                await status_message.edit_text(
                    f"📢 Tarqatish davom etmoqda… ({index}/{len(user_ids)})"
                )
            except TelegramAPIError:
                pass

        await asyncio.sleep(0.05)

    await message.answer(
        "📢 <b>Tarqatish yakunlandi!</b>\n\n"
        f"✅ Muvaffaqiyatli: <b>{success}</b>\n"
        f"❌ Yuborilmadi: <b>{failed}</b>\n"
        f"👥 Jami: <b>{len(user_ids)}</b>",
        reply_markup=main_menu_kb(),
    )


@router.message(AdminFSM.set_channel_input)
async def set_channel(message: Message, state: FSMContext, bot: Bot) -> None:
    """Kanalni (e'lon yoki majburiy) o'rnatadi.

    Matn ko'rinishidagi username/ID yoki kanaldan forward qilingan xabar
    qabul qilinadi.
    """
    if not is_admin(message.from_user.id if message.from_user else None):
        return

    data = await state.get_data()
    kind = "post" if data.get("channel_kind") == "post" else "required"

    raw = (message.text or "").strip()
    forwarded_chat = getattr(getattr(message, "forward_origin", None), "chat", None)

    if not raw and forwarded_chat is not None:
        raw = f"@{forwarded_chat.username}" if forwarded_chat.username else str(forwarded_chat.id)

    if not raw:
        await message.answer(
            "❌ Kanalni aniqlab boʻlmadi.\n\n"
            "Username/ID yuboring yoki kanaldan xabarni forward qiling.",
            reply_markup=cancel_kb(),
        )
        return

    if raw.startswith(("https://t.me/", "http://t.me/", "t.me/")):
        raw = "@" + raw.rstrip("/").split("/")[-1]
    elif not raw.startswith("@") and not raw.lstrip("-").isdigit():
        raw = "@" + raw.lstrip("@")

    try:
        chat = await bot.get_chat(raw)
    except TelegramAPIError as exc:
        logger.warning("Kanalni tekshirib boʻlmadi (%s): %s", raw, exc)
        await message.answer(
            "❌ <b>Kanalni topib boʻlmadi.</b>\n\n"
            "Tekshiring:\n"
            "• Username toʻgʻrimi?\n"
            "• Bot kanalda administrator qilib qoʻyilganmi?\n\n"
            "Qaytadan yuboring yoki «❌ Bekor qilish» tugmasini bosing."
        )
        return

    # Bot kanalda administrator ekanligini tekshiramiz — aks holda
    # aʼzolikni tekshirish ham, xabar joylash ham ishlamaydi.
    bot_status = ""
    try:
        me = await bot.get_me()
        member = await bot.get_chat_member(chat.id, me.id)
        bot_status = str(getattr(member, "status", ""))
    except TelegramAPIError as exc:
        logger.warning("Botning kanaldagi huquqini tekshirib boʻlmadi: %s", exc)

    if bot_status and bot_status not in ("administrator", "creator"):
        await message.answer(
            "⛔️ <b>Bot bu kanalda administrator emas.</b>\n\n"
            f"Kanal: <b>{esc(chat.title or raw)}</b>\n\n"
            "Iltimos, botni kanalga administrator qilib qoʻshing va "
            "qaytadan yuboring."
        )
        return

    channel_value = f"@{chat.username}" if chat.username else str(chat.id)
    if chat.username:
        channel_link = f"https://t.me/{chat.username}"
    else:
        channel_link = getattr(chat, "invite_link", None) or ""

    await db.set_channel(kind, channel_value, channel_link or "")
    await state.clear()

    title = "Eʼlon kanali" if kind == "post" else "Majburiy kanal"
    emoji = "📣" if kind == "post" else "🔒"
    await message.answer(
        f"✅ <b>{title} yangilandi!</b>\n\n"
        f"{emoji} Kanal: <b>{esc(chat.title or channel_value)}</b>\n"
        f"🔗 Qiymat: <code>{esc(channel_value)}</code>\n"
        f"🔗 Havola: {esc(channel_link or 'mavjud emas')}",
        reply_markup=main_menu_kb(),
    )


@router.message(AdminFSM.add_admin_id, F.text)
async def add_admin(message: Message, state: FSMContext, bot: Bot) -> None:
    """Yangi adminni qo'shadi."""
    admin_id = message.from_user.id if message.from_user else None
    if not is_admin(admin_id):
        return

    raw = (message.text or "").strip()
    target: Optional[dict] = None

    if raw.lstrip("-").isdigit():
        target = await db.get_user(int(raw))
        new_id = int(raw)
    else:
        target = await db.get_user_by_username(raw)
        new_id = int(target["user_id"]) if target else 0

    if not new_id or target is None:
        await message.answer(
            "❌ <b>Foydalanuvchi topilmadi.</b>\n\n"
            "U botga kamida bir marta /start bosgan boʻlishi kerak.\n"
            "Qaytadan ID yoki username yuboring.",
            reply_markup=cancel_kb(),
        )
        return

    if new_id == admin_id:
        await message.answer("ℹ️ Siz allaqachon administratorsiz.")
        return

    created = await db.add_admin(new_id)
    await state.clear()

    label = user_label(new_id, target.get("username"), target.get("full_name"))
    if created:
        await message.answer(
            "✅ <b>Yangi admin qoʻshildi!</b>\n\n"
            f"👤 {esc(label)}\n"
            f"🆔 <code>{new_id}</code>",
            reply_markup=main_menu_kb(),
        )
        try:
            await bot.send_message(
                new_id,
                "🎉 <b>Tabriklaymiz!</b>\n\n"
                "Siz botda administrator etib tayinlandingiz.\n"
                "Panelni ochish uchun <code>/admin</code> buyrugʻini yuboring.",
            )
        except TelegramAPIError as exc:
            logger.warning("Yangi adminga xabar yuborilmadi: %s", exc)
    else:
        await message.answer(
            f"ℹ️ <code>{new_id}</code> allaqachon administrator.",
            reply_markup=main_menu_kb(),
        )


@router.message(AdminFSM.remove_admin_id, F.text)
async def remove_admin(message: Message, state: FSMContext) -> None:
    """Adminni o'chiradi."""
    if not is_admin(message.from_user.id if message.from_user else None):
        return

    raw = (message.text or "").strip().lstrip("@")
    target = None if raw.lstrip("-").isdigit() else await db.get_user_by_username(raw)
    target_id = int(raw) if raw.lstrip("-").isdigit() else int((target or {}).get("user_id") or 0)

    if not target_id:
        await message.answer(
            "❌ Foydalanuvchi topilmadi. ID raqamini yuboring.",
            reply_markup=cancel_kb(),
        )
        return

    if config.ADMIN_ID and target_id == int(config.ADMIN_ID):
        await message.answer(
            "⛔️ Asosiy administratorni oʻchirib boʻlmaydi.\n\n"
            "U <code>.env</code> faylidagi <code>ADMIN_ID</code> orqali belgilangan.",
            reply_markup=main_menu_kb(),
        )
        return

    removed = await db.remove_admin(target_id)
    await state.clear()

    if removed:
        await message.answer(
            f"✅ <code>{target_id}</code> adminlar roʻyxatidan oʻchirildi.",
            reply_markup=main_menu_kb(),
        )
    else:
        await message.answer(
            f"ℹ️ <code>{target_id}</code> adminlar roʻyxatida yoʻq.",
            reply_markup=main_menu_kb(),
        )


@router.message(AdminFSM.lookup_user_id, F.text)
async def lookup_user(message: Message, state: FSMContext) -> None:
    """Foydalanuvchi haqida ma'lumot ko'rsatadi."""
    if not is_admin(message.from_user.id if message.from_user else None):
        return

    raw = (message.text or "").strip().lstrip("@")
    user: Optional[dict] = None

    if raw.lstrip("-").isdigit():
        user = await db.get_user(int(raw))
    else:
        user = await db.get_user_by_username(raw)

    await state.clear()

    if user is None:
        await message.answer(
            "❌ <b>Foydalanuvchi topilmadi.</b>\n\n"
            "U botga hali /start bosmagan boʻlishi mumkin.",
            reply_markup=main_menu_kb(),
        )
        return

    stats = await db.get_user_stats(int(user["user_id"]))
    is_banned = bool(user.get("is_banned"))
    blacklisted = await db.is_blacklisted(str(user["user_id"]))
    if blacklisted is None and user.get("username"):
        blacklisted = await db.is_blacklisted(str(user["username"]))

    text = (
        "👤 <b>Foydalanuvchi maʼlumotlari</b>\n\n"
        f"🆔 ID: <code>{user['user_id']}</code>\n"
        f"🔗 Username: {esc('@' + str(user['username']) if user.get('username') else '—')}\n"
        f"📛 Ism: {esc(user.get('full_name') or '—')}\n"
        f"📅 Roʻyxatdan oʻtgan: {esc(str(user.get('joined_at') or '—')[:19])}\n"
        f"🚫 Bloklangan: {'Ha' if is_banned else 'Yoʻq'}\n"
        f"⛔️ Qora roʻyxatda: {'Ha' if blacklisted else 'Yoʻq'}\n\n"
        "📋 <b>Eʼlonlar statistikasi</b>\n"
        f"• Jami: <b>{stats['total']}</b>\n"
        f"• Aktiv: <b>{stats['active']}</b>\n"
        f"• Kutilmoqda: <b>{stats['pending']}</b>\n"
        f"• Sotilgan: <b>{stats['sold']}</b>\n"
        f"• Rad etilgan: <b>{stats['rejected']}</b>"
    )

    await message.answer(
        text, reply_markup=dm_user_kb(int(user["user_id"])), disable_web_page_preview=True
    )


@router.message(AdminFSM.send_direct_msg_text)
async def send_direct_message(message: Message, state: FSMContext, bot: Bot) -> None:
    """Foydalanuvchiga shaxsiy xabarni yetkazadi."""
    if not is_admin(message.from_user.id if message.from_user else None):
        return

    data = await state.get_data()
    target_id = int(data.get("dm_target") or 0)
    await state.clear()

    if not target_id:
        await message.answer("⚠️ Qabul qiluvchi topilmadi.", reply_markup=main_menu_kb())
        return

    try:
        await bot.copy_message(
            chat_id=target_id,
            from_chat_id=message.chat.id,
            message_id=message.message_id,
        )
    except TelegramAPIError as exc:
        logger.warning("Shaxsiy xabar yuborilmadi (user=%s): %s", target_id, exc)
        await message.answer(
            f"❌ Xabar yuborilmadi.\n\nSababi: {esc(exc)}",
            reply_markup=main_menu_kb(),
        )
        return

    await message.answer(
        f"✅ Xabar <code>{target_id}</code> ga yuborildi.", reply_markup=main_menu_kb()
    )


@router.message(AdminFSM.ban_identifier, F.text)
async def ban_identifier(message: Message, state: FSMContext) -> None:
    """Qora ro'yxatga kiritiladigan identifikatorni qabul qiladi."""
    if not is_admin(message.from_user.id if message.from_user else None):
        return

    raw = (message.text or "").strip()
    identifier = db.normalize_identifier(raw)
    if len(identifier) < 3:
        await message.answer("❌ Identifikator juda qisqa. Qaytadan yuboring.")
        return

    await state.update_data(ban_identifier=identifier)
    await state.set_state(AdminFSM.ban_reason)
    await message.answer(
        f"👤 Identifikator: <code>{esc(identifier)}</code>\n\n{BAN_REASON_PROMPT}",
        reply_markup=cancel_kb(),
    )


@router.message(AdminFSM.ban_reason, F.text)
async def ban_reason(message: Message, state: FSMContext) -> None:
    """Sababni saqlab, qora ro'yxatga qo'shadi."""
    if not is_admin(message.from_user.id if message.from_user else None):
        return

    data = await state.get_data()
    identifier = str(data.get("ban_identifier") or "").strip()
    reason = (message.text or "").strip()[:300] or "Sabab koʻrsatilmagan"
    await state.clear()

    if not identifier:
        await message.answer(
            "⚠️ Identifikator yoʻqolib qoldi. Qaytadan boshlang.",
            reply_markup=main_menu_kb(),
        )
        return

    created = await db.add_to_blacklist(identifier, reason)

    if created:
        await message.answer(
            "✅ <b>Qora roʻyxatga qoʻshildi!</b>\n\n"
            f"👤 Identifikator: <code>{esc(identifier)}</code>\n"
            f"📝 Sababi: {esc(reason)}\n\n"
            "Endi bu foydalanuvchini «🛡️ Firibgarni tekshirish» boʻlimida tekshirish mumkin.",
            reply_markup=main_menu_kb(),
        )
    else:
        await message.answer(
            f"ℹ️ <code>{esc(identifier)}</code> allaqachon qora roʻyxatda mavjud.",
            reply_markup=main_menu_kb(),
        )


__all__ = ["router", "approve_listing", "reject_listing", "is_admin"]
