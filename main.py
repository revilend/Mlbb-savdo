"""Botni ishga tushiruvchi asosiy fayl.

Ishga tushirish:
    python main.py
"""

from __future__ import annotations

import asyncio
import glob
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

import config
from database import db
from handlers import (
    admin,
    calculator,
    catalog,
    common,
    favorites,
    garant,
    inbox,
    my_listings,
    offers,
    reviews,
    scam_check,
    search,
    sell,
    subscriptions,
)
from handlers.common import (
    edit_listing_card,
    seller_card_rating,
    seller_label_of,
    send_listing_card,
)
from keyboards import listing_action_kb, set_bot_username, single_button_kb
from middlewares import (
    SelfDestructMiddleware,
    UserMessageCleanerMiddleware,
    build_anti_flood,
    messages as message_registry,
)

logger = logging.getLogger(__name__)

BOT_COMMANDS = [
    BotCommand(command="start", description="Botni ishga tushirish"),
    BotCommand(command="cancel", description="Amalni bekor qilish"),
    BotCommand(command="clean", description="Chatni tozalash"),
    BotCommand(command="help", description="Yordam"),
    BotCommand(command="admin", description="Administrator paneli"),
]


def build_dispatcher() -> Dispatcher:
    """Barcha routerlarni to'g'ri tartibda ulanadi.

    Tartib muhim: `common` birinchi (bekor qilish, start, statistika),
    `fallback` esa eng oxirida ulanadi.
    """
    dispatcher = Dispatcher(storage=MemoryStorage())

    dispatcher.include_router(common.router)
    dispatcher.include_router(admin.router)
    dispatcher.include_router(sell.router)
    dispatcher.include_router(search.router)
    dispatcher.include_router(catalog.router)
    dispatcher.include_router(favorites.router)
    dispatcher.include_router(offers.router)
    dispatcher.include_router(inbox.router)
    dispatcher.include_router(reviews.router)
    dispatcher.include_router(subscriptions.router)
    dispatcher.include_router(calculator.router)
    dispatcher.include_router(scam_check.router)
    dispatcher.include_router(my_listings.router)
    dispatcher.include_router(garant.router)
    dispatcher.include_router(common.fallback_router)

    return dispatcher


def setup_protection_middlewares(
    dispatcher: Dispatcher,
    bot: Bot,
) -> Tuple[SelfDestructMiddleware, Optional[UserMessageCleanerMiddleware]]:
    """Anti-flood va xabarlarni tozalash middleware'larini ulaydi.

    :return: (self-destruct middleware, foydalanuvchi xabarlarini
             tozalovchi middleware yoki `None`)
    """
    # --- 1. O'z-o'zini o'chiruvchi xabarlar (session darajasida) -------------
    self_destruct = SelfDestructMiddleware(
        enabled=config.SELF_DESTRUCT_ENABLED,
        default_ttl=config.SELF_DESTRUCT_DEFAULT_TTL,
        registry=message_registry,
        skip_chat_ids=config.SELF_DESTRUCT_SKIP_CHAT_IDS,
        delete_user_messages=config.SELF_DESTRUCT_USER_MESSAGES,
    )
    bot.session.middleware(self_destruct)

    if config.SELF_DESTRUCT_ENABLED and config.SELF_DESTRUCT_DEFAULT_TTL > 0:
        logger.info(
            "Self-destruct yoqildi: bot xabarlari %ss dan keyin oʻchiriladi "
            "(istisno chatlar: %s).",
            config.SELF_DESTRUCT_DEFAULT_TTL,
            config.SELF_DESTRUCT_SKIP_CHAT_IDS or "yoʻq",
        )
    else:
        logger.info("Self-destruct oʻchirilgan.")

    # --- 2. Anti-flood — eng tashqi qatlam, routerlardan oldin ishlaydi ------
    # `db.admin_ids` jonli havola sifatida beriladi: panel orqali qo'shilgan
    # adminlar ham darhol cheklovdan ozod bo'ladi.
    anti_flood = build_anti_flood(db.admin_ids)
    if anti_flood is not None:
        # Bitta nusxa ikkala observer uchun ishlatiladi — hisob umumiy bo'lishi uchun
        dispatcher.message.outer_middleware(anti_flood)
        dispatcher.callback_query.outer_middleware(anti_flood)
        logger.info(
            "Anti-flood yoqildi: %s hodisa / %.1fs, mute %ss.",
            config.FLOOD_MAX_EVENTS,
            config.FLOOD_WINDOW_SECONDS,
            config.FLOOD_MUTE_SECONDS,
        )
    else:
        logger.info("Anti-flood oʻchirilgan (FLOOD_PROTECTION=false).")

    # --- 3. Foydalanuvchi xabarlarini tozalash (ixtiyoriy) -------------------
    user_cleaner: Optional[UserMessageCleanerMiddleware] = None
    if config.SELF_DESTRUCT_ENABLED and config.SELF_DESTRUCT_USER_MESSAGES:
        user_cleaner = UserMessageCleanerMiddleware(
            ttl=config.SELF_DESTRUCT_USER_TTL,
            skip_chat_ids=config.SELF_DESTRUCT_SKIP_CHAT_IDS,
        )
        dispatcher.message.outer_middleware(user_cleaner)
        logger.info(
            "Foydalanuvchi xabarlari %ss dan keyin oʻchiriladi.",
            config.SELF_DESTRUCT_USER_TTL,
        )

    return self_destruct, user_cleaner


async def set_bot_commands(bot: Bot) -> None:
    """Telegram menyusidagi buyruqlarni o'rnatadi."""
    try:
        await bot.set_my_commands(BOT_COMMANDS)
    except TelegramAPIError as exc:
        logger.warning("Buyruqlarni oʻrnatib boʻlmadi: %s", exc)


def seconds_until(hour: int, minute: int, now: Optional[datetime] = None) -> float:
    """Mahalliy vaqt bo'yicha keyingi `hour:minute` gacha qolgan sekundlar."""
    tz = timezone(timedelta(hours=config.TZ_OFFSET_HOURS))
    current = (now or datetime.now(timezone.utc)).astimezone(tz)
    target = current.replace(hour=int(hour), minute=int(minute), second=0, microsecond=0)
    if target <= current:
        target += timedelta(days=1)
    return max(1.0, (target - current).total_seconds())


def seconds_until_digest(now: Optional[datetime] = None) -> float:
    """Keyingi kunlik hisobotgacha qolgan sekundlar soni.

    Hisobot mahalliy vaqt (`config.TZ_OFFSET_HOURS`) bo'yicha
    `DIGEST_HOUR:DIGEST_MINUTE` da yuboriladi (sukut: 23:59).
    """
    return seconds_until(config.DIGEST_HOUR, config.DIGEST_MINUTE, now)


async def send_daily_digest(bot: Bot) -> None:
    """Kunlik hisobotni barcha adminlarga yuboradi."""
    new_users, new_listings, sold_listings = await db.get_today_stats()
    text = (
        "📊 <b>KUNLIK HISOBOT:</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 Bugungi yangi a'zolar: <b>+{new_users}</b>\n"
        f"📝 Yangi eʼlonlar: <b>{new_listings}</b>\n"
        f"✅ Sotilgan akkauntlar: <b>{sold_listings}</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Tizim 24/7 rejimida faol."
    )

    for admin_id in db.get_admin_ids():
        try:
            await bot.send_message(admin_id, text, disable_web_page_preview=True)
        except TelegramAPIError as exc:
            logger.warning("Kunlik hisobot yuborilmadi (admin=%s): %s", admin_id, exc)


def start_daily_digest(bot: Bot) -> asyncio.Task:
    """Kunlik hisobot vazifasini fonda ishga tushiradi."""
    return asyncio.create_task(daily_digest_task(bot), name="daily_digest")


async def daily_digest_task(bot: Bot) -> None:
    """Har kuni belgilangan vaqtda adminlarga hisobot yuboradigan fon sikli."""
    while True:
        delay = seconds_until_digest()
        logger.info(
            "Kunlik hisobot %02d:%02d da yuboriladi (%.0f sekunddan keyin).",
            config.DIGEST_HOUR,
            config.DIGEST_MINUTE,
            delay,
        )
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            raise

        try:
            await send_daily_digest(bot)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # hisobot yiqilsa ham sikl davom etadi
            logger.error("Kunlik hisobotni yuborishda xatolik: %s", exc)

        # Kun chegarasidan o'tib ketmaslik uchun qisqa pauza
        await asyncio.sleep(60)


# ---------------------------------------------------------------------------
# Fon vazifalari: e'lon muddati, kunning tanlovi, zaxira nusxa
# ---------------------------------------------------------------------------
#: Muddati o'tgan e'lonlarni qanchalik tez-tez tekshirish (sekund)
EXPIRY_CHECK_INTERVAL = 3600


async def expire_overdue_listings(bot: Bot) -> int:
    """Amal muddati o'tgan e'lonlarni arxivlaydi va egalarini ogohlantiradi."""
    listings = await db.get_expired_listings(limit=50)
    if not listings:
        return 0

    channel_id = await db.get_post_channel()
    for listing in listings:
        listing_id = int(listing["id"])
        await db.update_listing_status(listing_id, "expired")
        updated = await db.get_listing(listing_id) or listing

        if channel_id and updated.get("channel_msg_id"):
            await edit_listing_card(
                bot,
                channel_id,
                int(updated["channel_msg_id"]),
                updated,
                markup=None,
                header="⌛️ <b>MUDDATI TUGADI</b>",
            )

        try:
            await bot.send_message(
                int(updated["user_id"]),
                "⌛️ <b>Eʼloningiz amal muddati tugadi.</b>\n\n"
                f"🆔 Eʼlon raqami: <b>#{listing_id}</b>\n\n"
                "Eʼlon kanaldan yashirildi. Uni yana "
                f"<b>{config.LISTING_TTL_DAYS} kunga</b> yangilash uchun "
                "quyidagi tugmani bosing.",
                reply_markup=single_button_kb(
                    "🔄 Eʼlonni yangilash", f"renew_{listing_id}"
                ),
            )
        except TelegramAPIError as exc:
            logger.warning("Muddat xabari yuborilmadi (user=%s): %s", updated.get("user_id"), exc)

    return len(listings)


async def listing_expiry_task(bot: Bot) -> None:
    """Muddati o'tgan e'lonlarni soatiga bir marta tekshiradigan fon sikli."""
    while True:
        try:
            count = await expire_overdue_listings(bot)
            if count:
                logger.info("Muddati o'tgan %s ta eʼlon arxivlandi.", count)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # bitta xato sikl toʻxtamasin
            logger.error("Eʼlon muddatini tekshirishda xatolik: %s", exc)

        try:
            await asyncio.sleep(EXPIRY_CHECK_INTERVAL)
        except asyncio.CancelledError:
            raise


async def send_featured_post(bot: Bot) -> bool:
    """Kanalga «Kunning tanlovi» e'lonini joylaydi (VIP e'lonlar ustuvor)."""
    listing = await db.get_featured_listing()
    if listing is None:
        return False

    channel_id = await db.get_post_channel()
    if not channel_id:
        logger.info("Kunning tanlovi yuborilmadi: kanal sozlanmagan.")
        return False

    try:
        await send_listing_card(
            bot,
            channel_id,
            listing,
            markup=listing_action_kb(listing),
            header="🌟 <b>KUNNING TANLOVI</b>",
            seller_label=await seller_label_of(listing),
            seller_rating=await seller_card_rating(listing),
        )
    except TelegramAPIError as exc:
        logger.error("Kunning tanlovini joylab boʻlmadi: %s", exc)
        return False
    return True


async def daily_featured_task(bot: Bot) -> None:
    """Har kuni belgilangan vaqtda kanalga tanlangan e'lonni joylaydi."""
    while True:
        delay = seconds_until(config.FEATURED_HOUR, config.FEATURED_MINUTE)
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            raise

        try:
            await send_featured_post(bot)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("Kunning tanlovini yuborishda xatolik: %s", exc)

        await asyncio.sleep(60)


async def run_backup() -> Optional[str]:
    """Bazadan zaxira nusxa oladi va eski nusxalarni tozalaydi."""
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")
    dest = os.path.join(config.BACKUP_DIR, f"market_backup_{stamp}.sqlite3")
    if not await db.backup_to(dest):
        return None

    pattern = os.path.join(config.BACKUP_DIR, "market_backup_*.sqlite3")
    backups = sorted(glob.glob(pattern))
    for stale in backups[: max(0, len(backups) - config.BACKUP_KEEP)]:
        try:
            os.remove(stale)
            logger.info("Eski nusxa oʻchirildi: %s", stale)
        except OSError as exc:
            logger.warning("Eski nusxani oʻchirib boʻlmadi (%s): %s", stale, exc)
    return dest


async def daily_backup_task() -> None:
    """Har kuni bir marta bazaning zaxira nusxasini oladigan fon sikli."""
    while True:
        delay = seconds_until(config.BACKUP_HOUR, 0)
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            raise

        try:
            await run_backup()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("Zaxira nusxa olishda xatolik: %s", exc)

        await asyncio.sleep(60)


def start_background_tasks(bot: Bot) -> List[asyncio.Task]:
    """Kunlik hisobot, e'lon muddati, tanlov posti va zaxira vazifalarini ishga tushiradi."""
    tasks: List[asyncio.Task] = [start_daily_digest(bot)]
    tasks.append(asyncio.create_task(listing_expiry_task(bot), name="listing_expiry"))

    if config.FEATURED_ENABLED:
        tasks.append(asyncio.create_task(daily_featured_task(bot), name="daily_featured"))
    if config.BACKUP_ENABLED:
        tasks.append(asyncio.create_task(daily_backup_task(), name="daily_backup"))

    return tasks


async def stop_background_tasks(tasks: List[asyncio.Task]) -> None:
    """Fon vazifalarini bekor qilib, xatoliklarni yutadi."""
    for task in tasks:
        task.cancel()
    for task in tasks:
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception as exc:  # tozalashda xatolik ko'tarilmasin
            logger.debug("Fon vazifasi toʻxtatildi: %s", exc)


async def main() -> None:
    """Botni ishga tushiradi."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    )

    try:
        config.validate()
    except SystemExit as exc:
        logger.error("%s", exc)
        logger.error(
            "`env.example` faylini `.env` nomi bilan nusxalab, qiymatlarni toʻldiring."
        )
        raise

    await db.connect()

    bot = Bot(
        token=config.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dispatcher = build_dispatcher()
    self_destruct, user_cleaner = setup_protection_middlewares(dispatcher, bot)

    try:
        me = await bot.get_me()
        set_bot_username(me.username)
        logger.info("Bot ishga tushdi: @%s (ID: %s)", me.username, me.id)
    except TelegramAPIError as exc:
        logger.error("Bot tokenini tekshirib boʻlmadi: %s", exc)
        await self_destruct.shutdown()
        await bot.session.close()
        await db.close()
        raise SystemExit(1) from exc

    await set_bot_commands(bot)

    background_tasks = start_background_tasks(bot)

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("Polling boshlandi. Toʻxtatish uchun Ctrl+C bosing.")
        await dispatcher.start_polling(
            bot,
            allowed_updates=dispatcher.resolve_used_update_types(),
        )
    finally:
        await stop_background_tasks(background_tasks)
        await self_destruct.shutdown()
        if user_cleaner is not None:
            await user_cleaner.shutdown()
        await bot.session.close()
        await db.close()
        logger.info("Bot toʻxtatildi.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Foydalanuvchi tomonidan toʻxtatildi.")
