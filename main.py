"""Botni ishga tushiruvchi asosiy fayl.

Ishga tushirish:
    python main.py
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

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
    my_listings,
    offers,
    scam_check,
    search,
    sell,
)
from keyboards import set_bot_username
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


def seconds_until_digest(now: Optional[datetime] = None) -> float:
    """Keyingi kunlik hisobotgacha qolgan sekundlar soni.

    Hisobot mahalliy vaqt (`config.TZ_OFFSET_HOURS`) bo'yicha
    `DIGEST_HOUR:DIGEST_MINUTE` da yuboriladi (sukut: 23:59).
    """
    tz = timezone(timedelta(hours=config.TZ_OFFSET_HOURS))
    current = (now or datetime.now(timezone.utc)).astimezone(tz)
    target = current.replace(
        hour=config.DIGEST_HOUR,
        minute=config.DIGEST_MINUTE,
        second=0,
        microsecond=0,
    )
    if target <= current:
        target += timedelta(days=1)
    return max(1.0, (target - current).total_seconds())


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

    digest_task = start_daily_digest(bot)

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("Polling boshlandi. Toʻxtatish uchun Ctrl+C bosing.")
        await dispatcher.start_polling(
            bot,
            allowed_updates=dispatcher.resolve_used_update_types(),
        )
    finally:
        digest_task.cancel()
        try:
            await digest_task
        except asyncio.CancelledError:
            pass
        except Exception as exc:  # tozalashda hech qanday xatolik ko'tarilmasin
            logger.debug("Kunlik hisobot vazifasi toʻxtatildi: %s", exc)
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
