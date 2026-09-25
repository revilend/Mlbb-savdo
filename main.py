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
from aiohttp import web

import config
from database import db, storage_report
from handlers import (
    admin,
    bot_rating,
    calculator,
    catalog,
    comments,
    common,
    favorites,
    garant,
    inbox,
    market,
    my_listings,
    offers,
    reviews,
    scam_check,
    search,
    sell,
    settings_panel,
    subscriptions,
)
from handlers.common import (
    edit_listing_card,
    seller_card_rating,
    seller_label_of,
    send_listing_card,
)
from keyboards import listing_action_kb, set_bot_username, single_button_kb
from settings import settings
from middlewares import (
    SelfDestructMiddleware,
    UserMessageCleanerMiddleware,
    LatestMenuMiddleware,
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
    dispatcher.include_router(settings_panel.router)
    dispatcher.include_router(garant.router)
    dispatcher.include_router(market.router)
    dispatcher.include_router(comments.router)
    dispatcher.include_router(bot_rating.router)
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

    # --- 3. Menyudagi eski javobni almashtirish -----------------------------
    if config.SELF_DESTRUCT_REPLACE_OLD:
        dispatcher.message.outer_middleware(LatestMenuMiddleware())
        logger.info("Shaxsiy chatda faqat eng soʻngi menyu javobi saqlanadi.")

    # --- 4. Foydalanuvchi xabarlarini tozalash (ixtiyoriy) -------------------
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
    tz = timezone(timedelta(hours=int(settings.get("TZ_OFFSET_HOURS"))))
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
    return seconds_until(int(settings.get("DIGEST_HOUR")), int(settings.get("DIGEST_MINUTE")), now)


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
            settings.get("DIGEST_HOUR"),
            settings.get("DIGEST_MINUTE"),
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
                f"<b>{settings.get('LISTING_TTL_DAYS')} kunga</b> yangilash uchun "
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


#: Fon sikllari sozlama o'chirilganini qanchalik tez-tez tekshiradi (sekund)
IDLE_CHECK_INTERVAL = 60


async def daily_featured_task(bot: Bot) -> None:
    """Har kuni belgilangan vaqtda kanalga tanlangan e'lonni joylaydi.

    Sozlama bot ichidan o'chirilsa, sikl kutish rejimiga o'tadi va
    qayta yoqilganda darhol ishlashda davom etadi.
    """
    while True:
        if not settings.get_bool("FEATURED_ENABLED"):
            await asyncio.sleep(IDLE_CHECK_INTERVAL)
            continue

        delay = seconds_until(
            int(settings.get("FEATURED_HOUR")), int(settings.get("FEATURED_MINUTE"))
        )
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            raise

        try:
            if settings.get_bool("FEATURED_ENABLED"):
                await send_featured_post(bot)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("Kunning tanlovini yuborishda xatolik: %s", exc)

        await asyncio.sleep(IDLE_CHECK_INTERVAL)


async def run_backup() -> Optional[str]:
    """Bazadan zaxira nusxa oladi va eski nusxalarni tozalaydi."""
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")
    backup_dir = str(settings.get("BACKUP_DIR"))
    dest = os.path.join(backup_dir, f"market_backup_{stamp}.sqlite3")
    if not await db.backup_to(dest):
        return None

    pattern = os.path.join(backup_dir, "market_backup_*.sqlite3")
    backups = sorted(glob.glob(pattern))
    keep = max(1, int(settings.get("BACKUP_KEEP")))
    for stale in backups[: max(0, len(backups) - keep)]:
        try:
            os.remove(stale)
            logger.info("Eski nusxa oʻchirildi: %s", stale)
        except OSError as exc:
            logger.warning("Eski nusxani oʻchirib boʻlmadi (%s): %s", stale, exc)
    return dest


async def daily_backup_task() -> None:
    """Har kuni bir marta bazaning zaxira nusxasini oladigan fon sikli."""
    while True:
        if not settings.get_bool("BACKUP_ENABLED"):
            await asyncio.sleep(IDLE_CHECK_INTERVAL)
            continue

        delay = seconds_until(int(settings.get("BACKUP_HOUR")), 0)
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            raise

        try:
            if settings.get_bool("BACKUP_ENABLED"):
                await run_backup()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("Zaxira nusxa olishda xatolik: %s", exc)

        await asyncio.sleep(IDLE_CHECK_INTERVAL)


def start_background_tasks(bot: Bot) -> List[asyncio.Task]:
    """Kunlik hisobot, e'lon muddati, tanlov posti va zaxira vazifalarini ishga tushiradi."""
    # Barcha vazifalar doim ishga tushiriladi — yoqish/o'chirish bot ichidan
    # boshqariladi, shuning uchun restart talab qilinmaydi.
    return [
        start_daily_digest(bot),
        asyncio.create_task(listing_expiry_task(bot), name="listing_expiry"),
        asyncio.create_task(daily_featured_task(bot), name="daily_featured"),
        asyncio.create_task(daily_backup_task(), name="daily_backup"),
    ]


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


async def start_health_server() -> Optional[web.AppRunner]:
    """Render Web Service uchun health endpoint ishga tushiradi.

    Render Worker'ga ``PORT`` berilmaydi; bunday holatda portni band qilib
    bot polling'ini xavf ostiga qoʻymaslik uchun health server ishga tushirilmaydi.
    Web Service'ga esa Render ``PORT`` muhit oʻzgaruvchisini avtomatik beradi.
    """
    raw_port = str(os.getenv("PORT") or "").strip()
    if not raw_port:
        logger.debug("PORT berilmagan — health server ishga tushirilmaydi.")
        return None

    try:
        port = int(raw_port)
    except (TypeError, ValueError):
        logger.warning("PORT notoʻgʻri: %r — health server oʻtkazib yuboriladi", raw_port)
        return None
    if not 1 <= port <= 65535:
        logger.warning("PORT diapazonidan tashqarida: %s — health server oʻtkazib yuboriladi", port)
        return None

    async def health(_: web.Request) -> web.Response:
        return web.Response(text="MLBB Market bot is running\n")

    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_get("/health", health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=port)
    await site.start()
    logger.info("Health endpoint 0.0.0.0:%s portida ishga tushdi", port)
    return runner


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

    # Baza doimiy diskda turib turmaganini darhol ochiq aytib beramiz —
    # aks holda har bir redeploy'da e'lonlar yo'qoladi.
    storage_status = storage_report(config.DB_PATH)
    if "DOIMIY DISK ULanmagan" in storage_status:
        logger.error("%s", storage_status)
    else:
        logger.info("%s", storage_status)

    # Bot ichidan kiritilgan sozlamalarni yuklaymiz (`.env` — standart qiymat)
    settings.load(await db.get_settings_by_prefix(settings.PREFIX))
    logger.info(
        "Sozlamalar yuklandi: %s tadan %s tasi bot ichidan oʻzgartirilgan.",
        settings.total_count(),
        settings.overridden_count(),
    )

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
    health_runner: Optional[web.AppRunner] = None
    polling_task: Optional[asyncio.Task] = None

    try:
        health_runner = await start_health_server()
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("Polling boshlandi. Toʻxtatish uchun Ctrl+C bosing.")
        polling_task = asyncio.create_task(
            dispatcher.start_polling(
                bot,
                allowed_updates=dispatcher.resolve_used_update_types(),
            ),
            name="telegram_polling",
        )
        await polling_task
    finally:
        if polling_task is not None and not polling_task.done():
            polling_task.cancel()
            try:
                await polling_task
            except asyncio.CancelledError:
                pass
        if health_runner is not None:
            await health_runner.cleanup()
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
