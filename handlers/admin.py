"""Administrator paneli.

Moderatsiya (tasdiqlash/rad etish), xabar tarqatish, majburiy kanal,
foydalanuvchini qidirish, shaxsiy xabar yuborish va qora ro'yxat.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

import config
from database import db
from handlers.common import (
    ADMIN_PANEL_TEXT,
    esc,
    get_channel_id,
    send_listing_card,
    seller_label_of,
    status_label,
    user_label,
)
from keyboards import (
    admin_panel_kb,
    cancel_kb,
    dm_user_kb,
    listing_action_kb,
    main_menu_kb,
    single_button_kb,
)
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
    """Foydalanuvchi administrator ekanmi?"""
    return bool(user_id) and user_id == config.ADMIN_ID


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

    header = (
        "🆕 <b>Yangi xaridor soʻrovi</b>"
        if listing.get("listing_type") == "buy"
        else "🔥 <b>Yangi akkaunt sotuvda</b>"
    )

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
    if message is not None:
        await db.set_channel_message_id(listing_id, message.message_id)
    await db.update_bump_time(listing_id)

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
        f"🔴 Sotilgan: <b>{stats['sold']}</b>\n"
        f"🚫 Rad etilgan: <b>{stats['rejected']}</b>\n"
        f"🛒 Xaridor soʻrovlari: <b>{stats['buy_requests']}</b>\n"
        f"⭐️ Sevimlilarga qoʻshilganlar: <b>{stats['favorites']}</b>\n"
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
    """Majburiy kanalni sozlashni boshlaydi."""
    if not is_admin(callback.from_user.id):
        await _deny(callback)
        return

    current = await get_channel_id()
    await state.set_state(AdminFSM.set_channel_input)
    await callback.answer()
    if isinstance(callback.message, Message):
        await callback.message.answer(
            f"📣 Hozirgi kanal: <code>{esc(current or 'sozlanmagan')}</code>\n\n{CHANNEL_PROMPT}",
            reply_markup=cancel_kb(),
        )


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
        if user_id == config.ADMIN_ID:
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


@router.message(AdminFSM.set_channel_input, F.text)
async def set_channel(message: Message, state: FSMContext, bot: Bot) -> None:
    """Majburiy kanalni o'rnatadi."""
    if not is_admin(message.from_user.id if message.from_user else None):
        return

    raw = (message.text or "").strip()
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

    channel_value = f"@{chat.username}" if chat.username else str(chat.id)
    if chat.username:
        channel_link = f"https://t.me/{chat.username}"
    else:
        channel_link = getattr(chat, "invite_link", None) or ""

    await db.set_setting("required_channel", channel_value)
    await db.set_setting("required_channel_link", channel_link or "")
    await state.clear()

    await message.answer(
        "✅ <b>Majburiy kanal yangilandi!</b>\n\n"
        f"📣 Kanal: <b>{esc(chat.title or channel_value)}</b>\n"
        f"🔗 Qiymat: <code>{esc(channel_value)}</code>\n"
        f"🔗 Havola: {esc(channel_link or 'mavjud emas')}",
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
