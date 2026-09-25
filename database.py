"""Ma'lumotlar bazasi qatlami (aiosqlite).

Barcha jadvallar `Database.connect()` chaqirilganda yaratiladi.
Butun modul bo'ylab bitta global `db` obyekti ishlatiladi.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

import aiosqlite

import config

logger = logging.getLogger(__name__)

DB_PATH = config.DB_PATH

_SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS users (
    user_id     INTEGER PRIMARY KEY,
    username    TEXT,
    full_name   TEXT,
    is_banned   INTEGER DEFAULT 0,
    referred_by INTEGER,
    free_vip    INTEGER DEFAULT 0,
    joined_at   TIMESTAMP
);

CREATE TABLE IF NOT EXISTS listings (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL,
    listing_type    TEXT NOT NULL DEFAULT 'sell',
    listing_mode    TEXT NOT NULL DEFAULT 'sell',
    trade_wanted    TEXT,
    rank_info       TEXT,
    skins_info      TEXT,
    price_numeric   INTEGER,
    price_display   TEXT,
    old_price       TEXT,
    contact         TEXT,
    description     TEXT,
    is_vip          INTEGER DEFAULT 0,
    photos          TEXT,
    channel_msg_id  INTEGER,
    status          TEXT DEFAULT 'pending',
    last_bumped     TIMESTAMP,
    sold_at         TIMESTAMP,
    expires_at      TIMESTAMP,
    created_at      TIMESTAMP
);

CREATE TABLE IF NOT EXISTS reviews (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id  INTEGER,
    seller_id   INTEGER NOT NULL,
    reviewer_id INTEGER NOT NULL,
    rating      INTEGER NOT NULL,
    comment     TEXT,
    created_at  TIMESTAMP,
    UNIQUE (reviewer_id, seller_id)
);

CREATE TABLE IF NOT EXISTS saved_searches (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    min_price  INTEGER,
    max_price  INTEGER,
    keyword    TEXT,
    created_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS offers (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id INTEGER NOT NULL,
    buyer_id   INTEGER NOT NULL,
    seller_id  INTEGER NOT NULL,
    amount     INTEGER,
    offer_text TEXT,
    is_trade   INTEGER DEFAULT 0,
    status     TEXT DEFAULT 'pending',
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS deals (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id INTEGER NOT NULL,
    seller_id  INTEGER NOT NULL,
    buyer_id   INTEGER NOT NULL,
    amount     INTEGER,
    status     TEXT DEFAULT 'new',
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS favorites (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    listing_id INTEGER NOT NULL,
    UNIQUE (user_id, listing_id)
);

CREATE TABLE IF NOT EXISTS blacklist (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    identifier TEXT UNIQUE,
    reason     TEXT,
    added_at   TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_listings_status ON listings (status);
CREATE INDEX IF NOT EXISTS idx_listings_user   ON listings (user_id);
CREATE INDEX IF NOT EXISTS idx_favorites_user  ON favorites (user_id);
CREATE INDEX IF NOT EXISTS idx_listings_sold   ON listings (sold_at);
CREATE INDEX IF NOT EXISTS idx_reviews_seller  ON reviews (seller_id);
CREATE INDEX IF NOT EXISTS idx_offers_seller   ON offers (seller_id);
CREATE INDEX IF NOT EXISTS idx_offers_buyer    ON offers (buyer_id);
CREATE INDEX IF NOT EXISTS idx_deals_users     ON deals (buyer_id, seller_id);
CREATE INDEX IF NOT EXISTS idx_searches_user   ON saved_searches (user_id);
"""

#: Jadval nomi -> qo'shilishi mumkin bo'lgan ustunlar ro'yxati.
#: `CREATE TABLE IF NOT EXISTS` mavjud jadvalga ustun qo'shmaydi, shu sababli
#: har bir ustun alohida tekshirilib, yetishmasa `ALTER TABLE` bilan qo'shiladi.
_MIGRATIONS: tuple[tuple[str, str, str], ...] = (
    (
        "listings",
        "listing_mode",
        "ALTER TABLE listings ADD COLUMN listing_mode TEXT NOT NULL DEFAULT 'sell'",
    ),
    ("listings", "trade_wanted", "ALTER TABLE listings ADD COLUMN trade_wanted TEXT"),
    ("listings", "old_price", "ALTER TABLE listings ADD COLUMN old_price TEXT"),
    ("listings", "sold_at", "ALTER TABLE listings ADD COLUMN sold_at TIMESTAMP"),
    ("listings", "expires_at", "ALTER TABLE listings ADD COLUMN expires_at TIMESTAMP"),
    ("users", "referred_by", "ALTER TABLE users ADD COLUMN referred_by INTEGER"),
    ("users", "free_vip", "ALTER TABLE users ADD COLUMN free_vip INTEGER DEFAULT 0"),
)


def _runtime():
    """Runtime sozlamalar do'konini kechiktirib import qiladi.

    `settings` moduli bazaga yozish uchun shu modulga murojaat qiladi, shu
    sababli aylanma importdan qochish uchun import funksiya ichida bajariladi.
    """
    from settings import settings as runtime

    return runtime


def utcnow_iso() -> str:
    """Hozirgi UTC vaqtni ISO ko'rinishida qaytaradi (sekundlar aniqligida)."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# ---------------------------------------------------------------------------
# Doimiy disk tekshiruvi
# ---------------------------------------------------------------------------
def _longest_mount(path: str) -> str:
    """Yo'l uchun mos keladigan eng uzun mount nuqtasi (`/proc/mounts` dan)."""
    try:
        real = str(Path(path).expanduser().resolve())
    except OSError:
        return ""
    best = ""
    try:
        with open("/proc/mounts", encoding="utf-8") as handle:
            for line in handle:
                parts = line.split()
                if len(parts) < 2:
                    continue
                mount = parts[1].replace("\\040", " ")
                if (real == mount or real.startswith(mount.rstrip("/") + "/")) and len(
                    mount
                ) > len(best):
                    best = mount
    except OSError:
        return ""
    return best


def on_render() -> bool:
    """Bot Render'da ishlayotganmi (Render `RENDER` o'zgaruvini qo'yadi)."""
    return bool(os.environ.get("RENDER")) or str(Path.cwd()).startswith("/opt/render")


def storage_is_persistent(path: str) -> bool:
    """Ma'lumotlar bazasi alohida mount qilingan diskda joylashganmi.

    Render'da disk ulanmagan bo'lsa, baza kodi bilan bir xil vaqtincha
    (ephemeral) diskda turadi va har bir redeploy'da yo'qoladi. Baza va
    kod turgan mount turli bo'lsa — demak, alohida disk ulangan.
    """
    db_mount = _longest_mount(path)
    code_mount = _longest_mount(os.getcwd())
    if not db_mount:
        return False
    return db_mount != code_mount


def storage_report(path: str) -> str:
    """Disk holati haqidagi bir qatorli hisobot (loglar uchun)."""
    mount = _longest_mount(path) or "nomaʼlum"
    if not on_render():
        return f"Mahalliy muhit — bazaning joylashuvi: {mount}"
    if storage_is_persistent(path):
        return f"✅ Doimiy diskka ulangan (mount: {mount}) — redeploy'da maʼlumot saqlanadi."
    return (
        f"⚠️ DOIMIY DISK ULanmagan! Bazaning joylashuvi: {mount}. "
        "Har bir redeploy'da BARCHA eʼlonlar va reytinglar yoʻqoladi. "
        "Render Dashboard → xizmat → Disk → Add disk bilan disk ulang."
    )


def days_from_now_iso(days: int) -> str:
    """Hozirdan `days` kun keyingi vaqtni ISO ko'rinishida qaytaradi."""
    return (
        datetime.now(timezone.utc) + timedelta(days=int(days))
    ).replace(microsecond=0).isoformat()


def day_bounds_iso(
    offset_hours: Optional[int] = None,
    now: Optional[datetime] = None,
) -> tuple[str, str]:
    """Berilgan soat siljishidagi "bugun"ning boshi va oxirini UTC ISO da qaytaradi.

    Natija `utcnow_iso()` bilan bir xil formatda bo'lgani uchun SQL'da
    satr ko'rinishida solishtirish to'g'ri ishlaydi.
    """
    if offset_hours is None:
        hours = int(_runtime().get("TZ_OFFSET_HOURS"))
    else:
        hours = int(offset_hours)
    tz = timezone(timedelta(hours=hours))
    current = (now or datetime.now(timezone.utc)).astimezone(tz)
    start_local = current.replace(hour=0, minute=0, second=0, microsecond=0)
    end_local = start_local + timedelta(days=1)
    start = start_local.astimezone(timezone.utc).replace(microsecond=0)
    end = end_local.astimezone(timezone.utc).replace(microsecond=0)
    return start.isoformat(), end.isoformat()


def parse_dt(value: Any) -> Optional[datetime]:
    """ISO matn yoki datetime qiymatini timezone-aware datetime ga aylantiradi."""
    if not value:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip().replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
                try:
                    dt = datetime.strptime(text, fmt)
                    break
                except ValueError:
                    continue
            else:
                return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


class Database:
    """aiosqlite ustidagi yupqa, qulay qatlam."""

    def __init__(self, path: str = DB_PATH) -> None:
        self.path = path
        self._conn: Optional[aiosqlite.Connection] = None
        self.restore_lock = asyncio.Lock()
        # Jonli to'plam: anti-flood middleware shu obyektga havola saqlaydi,
        # shuning uchun admin qo'shilganda/o'chirilganda u avtomatik yangilanadi.
        self.admin_ids: set[int] = {int(config.ADMIN_ID)} if config.ADMIN_ID else set()

    # ------------------------------------------------------------------ ulanish
    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError(
                "Maʼlumotlar bazasi ulanmagan. Avval `await db.connect()` chaqiring."
            )
        return self._conn

    async def connect(self) -> None:
        """Ulanishni ochadi va jadvallarni yaratadi."""
        if self._conn is not None:
            return
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL;")
        await self._conn.execute("PRAGMA foreign_keys=ON;")
        await self._conn.executescript(_SCHEMA)
        await self._apply_migrations()
        await self._conn.commit()
        await self.refresh_admins()
        logger.info("Maʼlumotlar bazasi tayyor: %s", self.path)

    async def _apply_migrations(self) -> None:
        """Yetishmayotgan ustunlarni qo'shadi (idempotent)."""
        existing: dict[str, set[str]] = {}
        for table, _column, _statement in _MIGRATIONS:
            if table in existing:
                continue
            async with self._conn.execute(f"PRAGMA table_info({table})") as cursor:  # type: ignore[union-attr]
                existing[table] = {row["name"] for row in await cursor.fetchall()}

        for table, column, statement in _MIGRATIONS:
            if column in existing.get(table, set()):
                continue
            await self._conn.execute(statement)  # type: ignore[union-attr]
            existing.setdefault(table, set()).add(column)
            logger.info("Migratsiya qoʻllandi: %s.%s", table, column)

    async def close(self) -> None:
        """Ulanishni yopadi."""
        if self._conn is not None:
            await self._conn.close()
            self._conn = None
            logger.info("Maʼlumotlar bazasi ulanishi yopildi.")

    # ------------------------------------------------------------- yordamchilar
    @staticmethod
    def _normalize_listing(row: Optional[aiosqlite.Row]) -> Optional[dict]:
        """Qatorni dict ga aylantiradi va `photos` ni ro'yxatga o'giradi."""
        if row is None:
            return None
        data = dict(row)
        raw = data.get("photos")
        photos: list[str] = []
        if raw:
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    photos = [str(item) for item in parsed if item]
            except (TypeError, ValueError, json.JSONDecodeError):
                photos = []
        data["photos"] = photos
        return data

    @staticmethod
    def _normalize_rows(rows: Any) -> list[dict]:
        result: list[dict] = []
        for row in rows:
            normalized = Database._normalize_listing(row)
            if normalized is not None:
                result.append(normalized)
        return result

    # ---------------------------------------------------------------- settings
    async def get_setting(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """Sozlamani o'qish."""
        async with self.conn.execute("SELECT value FROM settings WHERE key = ?", (key,)) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return default
        value = row["value"]
        return value if value is not None else default

    async def set_setting(self, key: str, value: Any) -> None:
        """Sozlamani saqlash (mavjud bo'lsa yangilaydi)."""
        await self.conn.execute(
            """
            INSERT INTO settings (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, "" if value is None else str(value)),
        )
        await self.conn.commit()

    async def delete_setting(self, key: str) -> bool:
        """Sozlamani o'chiradi (standart qiymatga qaytarish uchun)."""
        cursor = await self.conn.execute("DELETE FROM settings WHERE key = ?", (key,))
        await self.conn.commit()
        return bool(cursor.rowcount)

    async def get_settings_by_prefix(self, prefix: str) -> dict[str, str]:
        """Berilgan prefiks bilan boshlanadigan barcha sozlamalarni qaytaradi."""
        escaped = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        async with self.conn.execute(
            "SELECT key, value FROM settings WHERE key LIKE ? ESCAPE '\\'",
            (escaped + "%",),
        ) as cursor:
            rows = await cursor.fetchall()
        return {str(row["key"]): str(row["value"] or "") for row in rows}

    # ------------------------------------------------------------------ admins
    #: `settings` jadvalidagi adminlar ro'yxati kaliti
    ADMIN_SETTING_KEY = "admin_ids"

    @staticmethod
    def _parse_ids(raw: Optional[str]) -> set[int]:
        """Vergul/bo'shliq bilan ajratilgan ID ro'yxatini to'plamga aylantiradi."""
        result: set[int] = set()
        for chunk in re.split(r"[,\s;]+", str(raw or "")):
            chunk = chunk.strip()
            if chunk.lstrip("-").isdigit():
                result.add(int(chunk))
        return result

    async def refresh_admins(self) -> set[int]:
        """Adminlar ro'yxatini bazadan qayta o'qiydi.

        Asosiy administrator (`.env` dagi `ADMIN_ID`) har doim ro'yxatda bo'ladi
        va uni bot ichidan o'chirib bo'lmaydi.
        """
        stored = await self.get_setting(self.ADMIN_SETTING_KEY, "")
        ids = self._parse_ids(stored)
        if config.ADMIN_ID:
            ids.add(int(config.ADMIN_ID))
        self.admin_ids.clear()
        self.admin_ids.update(ids)
        return set(ids)

    def is_admin(self, user_id: Optional[int]) -> bool:
        """Foydalanuvchi administrator ekanmi (jonli to'plam asosida)."""
        if not user_id:
            return False
        return int(user_id) in self.admin_ids

    def get_admin_ids(self) -> list[int]:
        """Adminlar ID lari (asosiysi birinchi turadi)."""
        primary = int(config.ADMIN_ID) if config.ADMIN_ID else None
        others = sorted(uid for uid in self.admin_ids if uid != primary)
        return ([primary] if primary else []) + others

    async def add_admin(self, user_id: int) -> bool:
        """Yangi admin qo'shadi. Allaqachon mavjud bo'lsa `False` qaytaradi."""
        user_id = int(user_id)
        if user_id in self.admin_ids:
            return False
        ids = set(self.admin_ids)
        ids.add(user_id)
        await self._save_admins(ids)
        logger.info("Yangi admin qoʻshildi: %s", user_id)
        return True

    async def remove_admin(self, user_id: int) -> bool:
        """Adminni o'chiradi. Asosiy adminni o'chirib bo'lmaydi."""
        user_id = int(user_id)
        if config.ADMIN_ID and user_id == int(config.ADMIN_ID):
            return False
        if user_id not in self.admin_ids:
            return False
        ids = {uid for uid in self.admin_ids if uid != user_id}
        await self._save_admins(ids)
        logger.info("Admin o'chirildi: %s", user_id)
        return True

    async def _save_admins(self, ids: Iterable[int]) -> None:
        """Adminlar to'plamini bazaga yozadi va jonli to'plamni yangilaydi."""
        ordered = sorted({int(uid) for uid in ids})
        await self.set_setting(self.ADMIN_SETTING_KEY, ",".join(str(uid) for uid in ordered))
        self.admin_ids.clear()
        self.admin_ids.update(ordered)
        if config.ADMIN_ID:
            self.admin_ids.add(int(config.ADMIN_ID))

    # ---------------------------------------------------------------- channels
    async def get_post_channel(self) -> str:
        """E'lonlar joylanadigan kanal (admin panelda sozlanadi)."""
        stored = await self.get_setting("post_channel")
        if stored:
            return stored.strip()
        fallback = await self.get_setting("required_channel")
        return (fallback or _runtime().get("DEFAULT_CHANNEL_ID") or "").strip()

    async def get_post_channel_link(self) -> str:
        """E'lon kanali uchun havola."""
        stored = await self.get_setting("post_channel_link")
        if stored:
            return stored.strip()
        channel = await self.get_post_channel()
        return f"https://t.me/{channel.lstrip('@')}" if channel.startswith("@") else ""

    async def get_required_channel(self) -> str:
        """Majburiy a'zolik tekshiriladigan kanal."""
        stored = await self.get_setting("required_channel")
        return (stored or _runtime().get("DEFAULT_CHANNEL_ID") or "").strip()

    async def get_required_channel_link(self) -> str:
        """Majburiy kanal uchun havola."""
        stored = await self.get_setting("required_channel_link")
        if stored:
            return stored.strip()
        channel = await self.get_required_channel()
        return f"https://t.me/{channel.lstrip('@')}" if channel.startswith("@") else ""

    async def set_channel(self, kind: str, value: str, link: str = "") -> None:
        """Kanalni saqlaydi. `kind`: `'post'` yoki `'required'`."""
        key = "post_channel" if kind == "post" else "required_channel"
        await self.set_setting(key, value)
        await self.set_setting(key + "_link", link or "")

    # ------------------------------------------------------------------- users
    async def add_user(
        self,
        user_id: int,
        username: Optional[str] = None,
        full_name: Optional[str] = None,
    ) -> bool:
        """Foydalanuvchini qo'shadi yoki ma'lumotlarini yangilaydi.

        Qaytaradi: foydalanuvchi **yangi** bo'lsa `True`, avvaldan mavjud
        bo'lsa `False` (referal bonusini ikki marta bermaslik uchun kerak).
        """
        # `ON CONFLICT DO UPDATE` da `rowcount` har doim 1 bo'ladi, shuning uchun
        # foydalanuvchi yangi ekanligini alohida so'rov bilan aniqlaymiz.
        async with self.conn.execute(
            "SELECT 1 FROM users WHERE user_id = ? LIMIT 1", (int(user_id),)
        ) as cursor:
            existed = await cursor.fetchone() is not None

        await self.conn.execute(
            """
            INSERT INTO users (user_id, username, full_name, joined_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username  = excluded.username,
                full_name = excluded.full_name
            """,
            (user_id, username, full_name, utcnow_iso()),
        )
        await self.conn.commit()
        return not existed

    async def get_user(self, user_id: int) -> Optional[dict]:
        """Bitta foydalanuvchini qaytaradi."""
        async with self.conn.execute(
            "SELECT * FROM users WHERE user_id = ?", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
        return dict(row) if row else None

    async def get_user_by_username(self, username: str) -> Optional[dict]:
        """Foydalanuvchini username bo'yicha qidiradi (@ belgisisiz)."""
        clean = (username or "").lstrip("@").strip()
        if not clean:
            return None
        async with self.conn.execute(
            "SELECT * FROM users WHERE LOWER(username) = LOWER(?) LIMIT 1", (clean,)
        ) as cursor:
            row = await cursor.fetchone()
        return dict(row) if row else None

    async def get_all_user_ids(self, only_active: bool = True) -> list[int]:
        """Barcha (yoki bloklanmagan) foydalanuvchi ID larini qaytaradi."""
        query = "SELECT user_id FROM users"
        if only_active:
            query += " WHERE is_banned = 0"
        query += " ORDER BY user_id"
        async with self.conn.execute(query) as cursor:
            rows = await cursor.fetchall()
        return [int(row["user_id"]) for row in rows]

    async def count_users(self) -> int:
        """Jami foydalanuvchilar soni."""
        async with self.conn.execute("SELECT COUNT(*) AS cnt FROM users") as cursor:
            row = await cursor.fetchone()
        return int(row["cnt"]) if row else 0

    async def set_user_ban(self, user_id: int, banned: bool = True) -> None:
        """Foydalanuvchini bloklaydi yoki blokdan chiqaradi."""
        await self.conn.execute(
            "UPDATE users SET is_banned = ? WHERE user_id = ?",
            (1 if banned else 0, user_id),
        )
        await self.conn.commit()

    async def get_user_stats(self, user_id: int) -> dict[str, int]:
        """Foydalanuvchining e'lonlari bo'yicha statistika."""
        stats = {"total": 0, "pending": 0, "active": 0, "sold": 0, "rejected": 0}
        async with self.conn.execute(
            "SELECT status, COUNT(*) AS cnt FROM listings WHERE user_id = ? GROUP BY status",
            (user_id,),
        ) as cursor:
            async for row in cursor:
                count = int(row["cnt"])
                status = str(row["status"] or "")
                stats["total"] += count
                if status in stats:
                    stats[status] = count
        return stats

    # ---------------------------------------------------------------- listings
    async def create_listing(
        self,
        user_id: int,
        listing_type: str,
        rank_info: str = "",
        skins_info: str = "",
        price_numeric: Optional[int] = None,
        price_display: str = "",
        contact: str = "",
        description: str = "",
        is_vip: int = 0,
        photos: Optional[list[str]] = None,
        status: str = "pending",
        listing_mode: str = "sell",
        trade_wanted: Optional[str] = None,
    ) -> int:
        """Yangi e'lon yaratadi va uning ID sini qaytaradi.

        :param listing_mode: `'sell'` — oddiy sotuv, `'trade'` — barter (almashish).
        :param trade_wanted: barter rejimida qanday akkaunt kerakligi.
        """
        photos = photos or []
        created = utcnow_iso()
        mode = "trade" if str(listing_mode).lower() == "trade" else "sell"
        cursor = await self.conn.execute(
            """
            INSERT INTO listings (
                user_id, listing_type, listing_mode, trade_wanted,
                rank_info, skins_info, price_numeric,
                price_display, old_price, contact, description, is_vip, photos,
                channel_msg_id, status, last_bumped, sold_at, expires_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, NULL, ?, NULL, NULL, ?, ?)
            """,
            (
                user_id,
                listing_type,
                mode,
                (trade_wanted or None) if mode == "trade" else None,
                rank_info,
                skins_info,
                price_numeric,
                price_display,
                contact,
                description,
                1 if is_vip else 0,
                json.dumps(photos, ensure_ascii=False),
                status,
                days_from_now_iso(int(_runtime().get("LISTING_TTL_DAYS"))),
                created,
            ),
        )
        await self.conn.commit()
        listing_id = int(cursor.lastrowid or 0)
        logger.info(
            "Yangi eʼlon #%s (user=%s, turi=%s, rejim=%s)",
            listing_id,
            user_id,
            listing_type,
            mode,
        )
        return listing_id

    async def get_listing(self, listing_id: int) -> Optional[dict]:
        """E'lonni ID bo'yicha qaytaradi."""
        async with self.conn.execute(
            "SELECT * FROM listings WHERE id = ?", (listing_id,)
        ) as cursor:
            row = await cursor.fetchone()
        return self._normalize_listing(row)

    async def update_listing_status(self, listing_id: int, status: str) -> None:
        """E'lon holatini o'zgartiradi.

        E'lon yopilganda (`sold` / `found`) `sold_at` ham belgilanadi —
        kunlik hisobotda "bugun sotilganlar" ni to'g'ri sanash uchun kerak.
        """
        closed = status in ("sold", "found")
        await self.conn.execute(
            """
            UPDATE listings
               SET status = ?,
                   sold_at = CASE WHEN ? THEN COALESCE(sold_at, ?) ELSE sold_at END
             WHERE id = ?
            """,
            (status, 1 if closed else 0, utcnow_iso(), listing_id),
        )
        await self.conn.commit()

    async def update_listing_price(
        self,
        listing_id: int,
        new_price_num: int,
        new_price_display: str,
    ) -> Optional[dict]:
        """Narxni tushiradi: eski narx `old_price` ga saqlanadi.

        Qaytaradi: yangilangan e'lon (topilmasa `None`).
        """
        listing = await self.get_listing(listing_id)
        if listing is None:
            return None

        previous = (
            listing.get("price_display")
            or (f"{int(listing['price_numeric']):,}".replace(",", " ") + " soʻm"
                if listing.get("price_numeric") else None)
        )

        await self.conn.execute(
            """
            UPDATE listings
               SET old_price = ?, price_numeric = ?, price_display = ?
             WHERE id = ?
            """,
            (previous, int(new_price_num), str(new_price_display), listing_id),
        )
        await self.conn.commit()
        logger.info(
            "Eʼlon #%s narxi yangilandi: %s -> %s",
            listing_id,
            previous,
            new_price_display,
        )
        return await self.get_listing(listing_id)

    async def get_favorited_user_ids(self, listing_id: int) -> list[int]:
        """E'lonni sevimlilarga qo'shgan foydalanuvchilar ID si."""
        async with self.conn.execute(
            "SELECT user_id FROM favorites WHERE listing_id = ? ORDER BY id", (listing_id,)
        ) as cursor:
            rows = await cursor.fetchall()
        return [int(row["user_id"]) for row in rows]

    async def get_today_stats(self, offset_hours: Optional[int] = None) -> tuple[int, int, int]:
        """Bugungi ko'rsatkichlar: (yangi a'zolar, yangi e'lonlar, sotilganlar).

        "Bugun" mahalliy vaqt (`config.TZ_OFFSET_HOURS`) bo'yicha hisoblanadi.
        """
        start, end = day_bounds_iso(offset_hours)

        async with self.conn.execute(
            "SELECT COUNT(*) AS cnt FROM users WHERE joined_at >= ? AND joined_at < ?",
            (start, end),
        ) as cursor:
            row = await cursor.fetchone()
        new_users = int(row["cnt"]) if row else 0

        async with self.conn.execute(
            "SELECT COUNT(*) AS cnt FROM listings WHERE created_at >= ? AND created_at < ?",
            (start, end),
        ) as cursor:
            row = await cursor.fetchone()
        new_listings = int(row["cnt"]) if row else 0

        async with self.conn.execute(
            "SELECT COUNT(*) AS cnt FROM listings WHERE sold_at >= ? AND sold_at < ?",
            (start, end),
        ) as cursor:
            row = await cursor.fetchone()
        sold_listings = int(row["cnt"]) if row else 0

        return new_users, new_listings, sold_listings

    async def set_channel_message_id(self, listing_id: int, message_id: int) -> None:
        """Kanalga joylangan xabar ID sini saqlaydi."""
        await self.conn.execute(
            "UPDATE listings SET channel_msg_id = ? WHERE id = ?",
            (int(message_id), listing_id),
        )
        await self.conn.commit()

    async def update_bump_time(self, listing_id: int, when: Optional[str] = None) -> None:
        """E'lonni ko'tarish (UP) vaqtini yangilaydi."""
        await self.conn.execute(
            "UPDATE listings SET last_bumped = ? WHERE id = ?",
            (when or utcnow_iso(), listing_id),
        )
        await self.conn.commit()

    async def get_user_listings(
        self, user_id: int, statuses: Optional[list[str]] = None
    ) -> list[dict]:
        """Foydalanuvchining e'lonlari (yangidan eskiga)."""
        query = "SELECT * FROM listings WHERE user_id = ?"
        params: list[Any] = [user_id]
        if statuses:
            placeholders = ", ".join("?" for _ in statuses)
            query += f" AND status IN ({placeholders})"
            params.extend(statuses)
        query += " ORDER BY id DESC"
        async with self.conn.execute(query, tuple(params)) as cursor:
            rows = await cursor.fetchall()
        return self._normalize_rows(rows)

    async def get_random_active_listing(self) -> Optional[dict]:
        """Tasodifiy aktiv e'lonni qaytaradi."""
        async with self.conn.execute(
            "SELECT * FROM listings WHERE status = 'active' ORDER BY RANDOM() LIMIT 1"
        ) as cursor:
            row = await cursor.fetchone()
        return self._normalize_listing(row)

    async def get_featured_listing(self) -> Optional[dict]:
        """«Kunning tanlovi» uchun e'lon: VIP e'lonlar ustuvor, keyin tasodifiy."""
        async with self.conn.execute(
            """
            SELECT * FROM listings
             WHERE status = 'active'
             ORDER BY is_vip DESC, RANDOM()
             LIMIT 1
            """
        ) as cursor:
            row = await cursor.fetchone()
        return self._normalize_listing(row)

    async def get_filtered_listings(
        self,
        min_p: Optional[int] = None,
        max_p: Optional[int] = None,
        limit: int = 20,
    ) -> list[dict]:
        """Narx oralig'i bo'yicha aktiv e'lonlarni qaytaradi."""
        query = "SELECT * FROM listings WHERE status = 'active'"
        params: list[Any] = []
        if min_p is not None:
            query += " AND price_numeric IS NOT NULL AND price_numeric >= ?"
            params.append(int(min_p))
        if max_p is not None:
            query += " AND price_numeric IS NOT NULL AND price_numeric <= ?"
            params.append(int(max_p))
        query += " ORDER BY is_vip DESC, id DESC LIMIT ?"
        params.append(int(limit))
        async with self.conn.execute(query, tuple(params)) as cursor:
            rows = await cursor.fetchall()
        return self._normalize_rows(rows)

    async def get_active_listings(self, limit: int = 20) -> list[dict]:
        """Barcha aktiv e'lonlar (yangidan eskiga)."""
        async with self.conn.execute(
            "SELECT * FROM listings WHERE status = 'active' ORDER BY id DESC LIMIT ?",
            (int(limit),),
        ) as cursor:
            rows = await cursor.fetchall()
        return self._normalize_rows(rows)

    async def get_pending_listings(self, limit: int = 20) -> list[dict]:
        """Moderatsiya kutilayotgan e'lonlar."""
        async with self.conn.execute(
            "SELECT * FROM listings WHERE status = 'pending' ORDER BY id ASC LIMIT ?",
            (int(limit),),
        ) as cursor:
            rows = await cursor.fetchall()
        return self._normalize_rows(rows)

    async def delete_listing(self, listing_id: int) -> None:
        """E'lonni (va unga bog'liq sevimlilarni) o'chiradi."""
        await self.conn.execute("DELETE FROM favorites WHERE listing_id = ?", (listing_id,))
        await self.conn.execute("DELETE FROM listings WHERE id = ?", (listing_id,))
        await self.conn.commit()

    # --------------------------------------------------------------- favorites
    async def add_favorite(self, user_id: int, listing_id: int) -> bool:
        """Sevimlilarga qo'shadi. Yangi qo'shilgan bo'lsa True."""
        cursor = await self.conn.execute(
            "INSERT OR IGNORE INTO favorites (user_id, listing_id) VALUES (?, ?)",
            (user_id, listing_id),
        )
        await self.conn.commit()
        return bool(cursor.rowcount)

    async def remove_favorite(self, user_id: int, listing_id: int) -> bool:
        """Sevimlilardan olib tashlaydi. O'chirilgan bo'lsa True."""
        cursor = await self.conn.execute(
            "DELETE FROM favorites WHERE user_id = ? AND listing_id = ?",
            (user_id, listing_id),
        )
        await self.conn.commit()
        return bool(cursor.rowcount)

    async def get_favorites(self, user_id: int) -> list[dict]:
        """Foydalanuvchining sevimli e'lonlari."""
        async with self.conn.execute(
            """
            SELECT l.* FROM favorites AS f
            JOIN listings AS l ON l.id = f.listing_id
            WHERE f.user_id = ?
            ORDER BY f.id DESC
            """,
            (user_id,),
        ) as cursor:
            rows = await cursor.fetchall()
        return self._normalize_rows(rows)

    async def is_favorite(self, user_id: int, listing_id: int) -> bool:
        """E'lon sevimlilarda bor-yo'qligini tekshiradi."""
        async with self.conn.execute(
            "SELECT 1 FROM favorites WHERE user_id = ? AND listing_id = ? LIMIT 1",
            (user_id, listing_id),
        ) as cursor:
            row = await cursor.fetchone()
        return row is not None

    async def count_favorites(self, listing_id: int) -> int:
        """E'lonni nechta foydalanuvchi saqlaganini qaytaradi."""
        async with self.conn.execute(
            "SELECT COUNT(*) AS cnt FROM favorites WHERE listing_id = ?", (listing_id,)
        ) as cursor:
            row = await cursor.fetchone()
        return int(row["cnt"]) if row else 0

    # --------------------------------------------------------------- blacklist
    @staticmethod
    def normalize_identifier(identifier: str) -> str:
        """Identifikatorni bir xil ko'rinishga keltiradi (@, bo'shliqlar olib tashlanadi)."""
        return (identifier or "").strip().lstrip("@").strip()

    async def is_blacklisted(self, identifier: str) -> Optional[dict]:
        """Qora ro'yxatda bor bo'lsa yozuvni qaytaradi, aks holda None."""
        clean = self.normalize_identifier(identifier)
        if not clean:
            return None
        async with self.conn.execute(
            "SELECT * FROM blacklist WHERE LOWER(identifier) = LOWER(?) LIMIT 1", (clean,)
        ) as cursor:
            row = await cursor.fetchone()
        return dict(row) if row else None

    async def add_to_blacklist(self, identifier: str, reason: str = "") -> bool:
        """Qora ro'yxatga qo'shadi. Yangi qo'shilgan bo'lsa True, mavjud bo'lsa False."""
        clean = self.normalize_identifier(identifier)
        if not clean:
            return False
        cursor = await self.conn.execute(
            "INSERT OR IGNORE INTO blacklist (identifier, reason, added_at) VALUES (?, ?, ?)",
            (clean, reason or "Sabab koʻrsatilmagan", utcnow_iso()),
        )
        await self.conn.commit()
        return bool(cursor.rowcount)

    async def get_blacklist(self, limit: int = 50) -> list[dict]:
        """Qora ro'yxatdagi yozuvlar."""
        async with self.conn.execute(
            "SELECT * FROM blacklist ORDER BY id DESC LIMIT ?", (int(limit),)
        ) as cursor:
            rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def remove_from_blacklist(self, identifier: str) -> bool:
        """Qora ro'yxatdan olib tashlaydi."""
        clean = self.normalize_identifier(identifier)
        if not clean:
            return False
        cursor = await self.conn.execute(
            "DELETE FROM blacklist WHERE LOWER(identifier) = LOWER(?)", (clean,)
        )
        await self.conn.commit()
        return bool(cursor.rowcount)

    # ------------------------------------------- listings: tahrir va amal muddati
    #: `update_listing_fields()` orqali o'zgartirish mumkin bo'lgan ustunlar.
    EDITABLE_LISTING_FIELDS = frozenset(
        {
            "price_numeric",
            "price_display",
            "old_price",
            "description",
            "contact",
            "rank_info",
            "skins_info",
            "trade_wanted",
        }
    )

    async def update_listing_fields(self, listing_id: int, **fields: Any) -> Optional[dict]:
        """E'lonning ruxsat etilgan maydonlarini yangilaydi."""
        allowed = {key: value for key, value in fields.items() if key in self.EDITABLE_LISTING_FIELDS}
        if not allowed:
            return await self.get_listing(listing_id)

        assignments = ", ".join(f"{key} = ?" for key in allowed)
        params: list[Any] = list(allowed.values()) + [int(listing_id)]
        await self.conn.execute(
            f"UPDATE listings SET {assignments} WHERE id = ?", tuple(params)
        )
        await self.conn.commit()
        logger.info("Eʼlon #%s tahrirlandi: %s", listing_id, ", ".join(allowed))
        return await self.get_listing(listing_id)

    async def touch_listing_expiry(self, listing_id: int, days: Optional[int] = None) -> None:
        """E'lonning amal muddatini hozirdan boshlab uzaytiradi."""
        ttl = int(_runtime().get("LISTING_TTL_DAYS")) if days is None else max(1, int(days))
        await self.conn.execute(
            "UPDATE listings SET expires_at = ? WHERE id = ?",
            (days_from_now_iso(ttl), int(listing_id)),
        )
        await self.conn.commit()

    async def get_expired_listings(self, limit: int = 50) -> list[dict]:
        """Muddati o'tgan, lekin hali arxivga tushmagan aktiv e'lonlar."""
        async with self.conn.execute(
            """
            SELECT * FROM listings
             WHERE status = 'active'
               AND expires_at IS NOT NULL
               AND expires_at <= ?
             ORDER BY id ASC
             LIMIT ?
            """,
            (utcnow_iso(), int(limit)),
        ) as cursor:
            rows = await cursor.fetchall()
        return self._normalize_rows(rows)

    async def get_similar_listings(self, listing_id: int, limit: int = 3) -> list[dict]:
        """O'xshash aktiv e'lonlar (narx oralig'i va rank bo'yicha)."""
        base = await self.get_listing(listing_id)
        if base is None:
            return []

        query = "SELECT * FROM listings WHERE status = 'active' AND id != ?"
        params: list[Any] = [int(listing_id)]

        price = base.get("price_numeric")
        if price:
            tolerance = float(_runtime().get("SIMILAR_PRICE_TOLERANCE"))
            low = int(int(price) * (1 - tolerance))
            high = int(int(price) * (1 + tolerance))
            query += " AND price_numeric IS NOT NULL AND price_numeric BETWEEN ? AND ?"
            params.extend([low, high])
        else:
            rank = (base.get("rank_info") or "").strip()
            if rank:
                query += " AND rank_info = ?"
                params.append(rank)

        rank_value = (base.get("rank_info") or "").strip()
        query += " ORDER BY (rank_info = ?) DESC, is_vip DESC, id DESC LIMIT ?"
        params.extend([rank_value, int(limit)])

        async with self.conn.execute(query, tuple(params)) as cursor:
            rows = await cursor.fetchall()
        return self._normalize_rows(rows)

    # ------------------------------------------------------------------ reviews
    async def add_review(
        self,
        listing_id: Optional[int],
        seller_id: int,
        reviewer_id: int,
        rating: int,
        comment: str = "",
    ) -> bool:
        """Sotuvchi haqida sharh qoldiradi (bir foydalanuvchi — bitta sharh)."""
        score = max(1, min(5, int(rating)))
        cursor = await self.conn.execute(
            """
            INSERT INTO reviews (listing_id, seller_id, reviewer_id, rating, comment, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(reviewer_id, seller_id) DO UPDATE SET
                listing_id = excluded.listing_id,
                rating     = excluded.rating,
                comment    = excluded.comment,
                created_at = excluded.created_at
            """,
            (
                int(listing_id) if listing_id else None,
                int(seller_id),
                int(reviewer_id),
                score,
                (comment or "")[:300],
                utcnow_iso(),
            ),
        )
        await self.conn.commit()
        return bool(cursor.rowcount)

    async def get_seller_rating(self, seller_id: int) -> tuple[float, int]:
        """Sotuvchining o'rtacha bahosi va sharhlar soni: (o'rtacha, soni)."""
        async with self.conn.execute(
            "SELECT AVG(rating) AS avg_rating, COUNT(*) AS cnt FROM reviews WHERE seller_id = ?",
            (int(seller_id),),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None or not row["cnt"]:
            return 0.0, 0
        return round(float(row["avg_rating"] or 0.0), 1), int(row["cnt"])

    async def get_seller_reviews(self, seller_id: int, limit: int = 5) -> list[dict]:
        """Sotuvchi haqidagi oxirgi sharhlar."""
        async with self.conn.execute(
            """
            SELECT * FROM reviews
             WHERE seller_id = ?
             ORDER BY id DESC
             LIMIT ?
            """,
            (int(seller_id), int(limit)),
        ) as cursor:
            rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def get_seller_stats(self, seller_id: int) -> dict:
        """Sotuvchi profili uchun umumiy statistika."""
        seller_id = int(seller_id)
        score, count = await self.get_seller_rating(seller_id)
        async with self.conn.execute(
            """
            SELECT
                SUM(CASE WHEN status = 'sold'   THEN 1 ELSE 0 END) AS sold,
                SUM(CASE WHEN status = 'active' THEN 1 ELSE 0 END) AS active
            FROM listings WHERE user_id = ?
            """,
            (seller_id,),
        ) as cursor:
            row = await cursor.fetchone()
        user = await self.get_user(seller_id)
        return {
            "rating": score,
            "reviews": count,
            "sold": int((row["sold"] if row else 0) or 0),
            "active": int((row["active"] if row else 0) or 0),
            "joined_at": (user or {}).get("joined_at"),
            "free_vip": int((user or {}).get("free_vip") or 0),
        }

    async def get_recent_reviews(self, limit: int = 10, offset: int = 0) -> list[dict]:
        """Barcha sotuvchilar bo'yicha oxirgi qo'yilgan sharhlar."""
        async with self.conn.execute(
            """
            SELECT * FROM reviews
             ORDER BY id DESC
             LIMIT ? OFFSET ?
            """,
            (int(limit), int(offset)),
        ) as cursor:
            rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def has_reviewed(self, reviewer_id: int, seller_id: int) -> bool:
        """Foydalanuvchi bu sotuvchi haqida sharh qoldirganmi?"""
        async with self.conn.execute(
            "SELECT 1 FROM reviews WHERE reviewer_id = ? AND seller_id = ? LIMIT 1",
            (int(reviewer_id), int(seller_id)),
        ) as cursor:
            row = await cursor.fetchone()
        return row is not None

    # ---------------------------------------------------------- saved searches
    async def add_saved_search(
        self,
        user_id: int,
        min_price: Optional[int] = None,
        max_price: Optional[int] = None,
        keyword: str = "",
    ) -> int:
        """Saqlangan qidiruv (obuna) yaratadi va uning ID sini qaytaradi."""
        cursor = await self.conn.execute(
            """
            INSERT INTO saved_searches (user_id, min_price, max_price, keyword, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                int(user_id),
                int(min_price) if min_price else None,
                int(max_price) if max_price else None,
                (keyword or "").strip()[:120],
                utcnow_iso(),
            ),
        )
        await self.conn.commit()
        return int(cursor.lastrowid or 0)

    async def get_saved_searches(self, user_id: int) -> list[dict]:
        """Foydalanuvchining saqlangan qidiruvlari."""
        async with self.conn.execute(
            "SELECT * FROM saved_searches WHERE user_id = ? ORDER BY id DESC",
            (int(user_id),),
        ) as cursor:
            rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def remove_saved_search(self, search_id: int, user_id: Optional[int] = None) -> bool:
        """Saqlangan qidiruvni o'chiradi (egasi tekshiriladi)."""
        query = "DELETE FROM saved_searches WHERE id = ?"
        params: list[Any] = [int(search_id)]
        if user_id is not None:
            query += " AND user_id = ?"
            params.append(int(user_id))
        cursor = await self.conn.execute(query, tuple(params))
        await self.conn.commit()
        return bool(cursor.rowcount)

    async def match_saved_searches(self, listing: dict) -> list[dict]:
        """E'longa mos keladigan obunalar (e'lon egasidan tashqari)."""
        owner_id = int(listing.get("user_id") or 0)
        price = listing.get("price_numeric")
        haystack = " ".join(
            str(listing.get(field) or "")
            for field in ("rank_info", "skins_info", "description", "trade_wanted")
        ).lower()

        matches: list[dict] = []
        for search in await self.get_all_saved_searches():
            if int(search["user_id"]) == owner_id:
                continue
            low, high = search.get("min_price"), search.get("max_price")
            if low is not None or high is not None:
                if not price:
                    continue
                if low is not None and int(price) < int(low):
                    continue
                if high is not None and int(price) > int(high):
                    continue
            keyword = str(search.get("keyword") or "").strip().lower()
            if keyword and keyword not in haystack:
                continue
            matches.append(search)
        return matches

    async def get_all_saved_searches(self) -> list[dict]:
        """Barcha saqlangan qidiruvlar (mos kelishini hisoblash uchun)."""
        async with self.conn.execute("SELECT * FROM saved_searches ORDER BY id ASC") as cursor:
            rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    # ------------------------------------------------------------------- offers
    async def create_offer(
        self,
        listing_id: int,
        buyer_id: int,
        seller_id: int,
        amount: Optional[int] = None,
        offer_text: str = "",
        is_trade: bool = False,
    ) -> int:
        """Taklifni bazaga saqlaydi va uning ID sini qaytaradi."""
        now = utcnow_iso()
        cursor = await self.conn.execute(
            """
            INSERT INTO offers (
                listing_id, buyer_id, seller_id, amount, offer_text,
                is_trade, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?)
            """,
            (
                int(listing_id),
                int(buyer_id),
                int(seller_id),
                int(amount) if amount else None,
                (offer_text or "")[:300],
                1 if is_trade else 0,
                now,
                now,
            ),
        )
        await self.conn.commit()
        return int(cursor.lastrowid or 0)

    async def get_offer(self, offer_id: int) -> Optional[dict]:
        """Taklifni ID bo'yicha qaytaradi."""
        async with self.conn.execute("SELECT * FROM offers WHERE id = ?", (int(offer_id),)) as cursor:
            row = await cursor.fetchone()
        return dict(row) if row else None

    async def update_offer_status(self, offer_id: int, status: str) -> Optional[dict]:
        """Taklif holatini yangilaydi va joriy yozuvni qaytaradi."""
        await self.conn.execute(
            "UPDATE offers SET status = ?, updated_at = ? WHERE id = ?",
            (str(status), utcnow_iso(), int(offer_id)),
        )
        await self.conn.commit()
        return await self.get_offer(offer_id)

    async def get_user_offers(
        self,
        user_id: int,
        side: str = "all",
        limit: int = 10,
        only_pending: bool = False,
    ) -> list[dict]:
        """Foydalanuvchiga tegishli takliflar (`side`: all/seller/buyer)."""
        query = "SELECT * FROM offers WHERE 1 = 1"
        params: list[Any] = []
        if side == "seller":
            query += " AND seller_id = ?"
            params.append(int(user_id))
        elif side == "buyer":
            query += " AND buyer_id = ?"
            params.append(int(user_id))
        else:
            query += " AND (seller_id = ? OR buyer_id = ?)"
            params.extend([int(user_id), int(user_id)])
        if only_pending:
            query += " AND status = 'pending'"
        query += " ORDER BY id DESC LIMIT ?"
        params.append(int(limit))
        async with self.conn.execute(query, tuple(params)) as cursor:
            rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def count_pending_offers(self, seller_id: int) -> int:
        """Sotuvchida javob kutilayotgan takliflar soni."""
        async with self.conn.execute(
            "SELECT COUNT(*) AS cnt FROM offers WHERE seller_id = ? AND status = 'pending'",
            (int(seller_id),),
        ) as cursor:
            row = await cursor.fetchone()
        return int(row["cnt"]) if row else 0

    # -------------------------------------------------------------------- deals
    async def create_deal(
        self,
        listing_id: int,
        seller_id: int,
        buyer_id: int,
        amount: Optional[int] = None,
    ) -> int:
        """Yangi bitimni qayd etadi va uning ID sini qaytaradi."""
        now = utcnow_iso()
        cursor = await self.conn.execute(
            """
            INSERT INTO deals (listing_id, seller_id, buyer_id, amount, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'new', ?, ?)
            """,
            (
                int(listing_id),
                int(seller_id),
                int(buyer_id),
                int(amount) if amount else None,
                now,
                now,
            ),
        )
        await self.conn.commit()
        return int(cursor.lastrowid or 0)

    async def get_deal(self, deal_id: int) -> Optional[dict]:
        """Bitimni ID bo'yicha qaytaradi."""
        async with self.conn.execute("SELECT * FROM deals WHERE id = ?", (int(deal_id),)) as cursor:
            row = await cursor.fetchone()
        return dict(row) if row else None

    async def get_buyer_deal(self, listing_id: int, buyer_id: int) -> Optional[dict]:
        """E'lonni xaridor sifatida olgan foydalanuvchining bitimi (oxirgisi)."""
        async with self.conn.execute(
            """
            SELECT * FROM deals
             WHERE listing_id = ? AND buyer_id = ?
             ORDER BY id DESC
             LIMIT 1
            """,
            (int(listing_id), int(buyer_id)),
        ) as cursor:
            row = await cursor.fetchone()
        return dict(row) if row else None

    async def get_listing_buyers(self, listing_id: int) -> list[int]:
        """E'lonni xaridor sifatida olgan foydalanuvchilar ID ro'yxati."""
        async with self.conn.execute(
            "SELECT DISTINCT buyer_id FROM deals WHERE listing_id = ?",
            (int(listing_id),),
        ) as cursor:
            rows = await cursor.fetchall()
        return [int(row["buyer_id"]) for row in rows]

    async def update_deal_status(self, deal_id: int, status: str) -> Optional[dict]:
        """Bitim holatini yangilaydi va joriy yozuvni qaytaradi."""
        await self.conn.execute(
            "UPDATE deals SET status = ?, updated_at = ? WHERE id = ?",
            (str(status), utcnow_iso(), int(deal_id)),
        )
        await self.conn.commit()
        return await self.get_deal(deal_id)

    async def get_user_deals(self, user_id: int, limit: int = 10) -> list[dict]:
        """Foydalanuvchi ishtirok etgan bitimlar."""
        async with self.conn.execute(
            """
            SELECT * FROM deals
             WHERE seller_id = ? OR buyer_id = ?
             ORDER BY id DESC
             LIMIT ?
            """,
            (int(user_id), int(user_id), int(limit)),
        ) as cursor:
            rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    # ---------------------------------------------------------------- referallar
    async def set_referrer(self, user_id: int, referrer_id: int) -> bool:
        """Yangi foydalanuvchiga taklif qilgan do'stini biriktiradi."""
        user_id, referrer_id = int(user_id), int(referrer_id)
        if user_id == referrer_id:
            return False

        # Foydalanuvchi yozuvi hali bo'lmasa ham ishlashi uchun avval uni yaratamiz
        await self.conn.execute(
            "INSERT OR IGNORE INTO users (user_id, joined_at) VALUES (?, ?)",
            (user_id, utcnow_iso()),
        )
        cursor = await self.conn.execute(
            "UPDATE users SET referred_by = ? WHERE user_id = ? AND referred_by IS NULL",
            (referrer_id, user_id),
        )
        await self.conn.commit()
        return bool(cursor.rowcount)

    async def count_referrals(self, referrer_id: int) -> int:
        """Taklif qilingan do'stlar soni."""
        async with self.conn.execute(
            "SELECT COUNT(*) AS cnt FROM users WHERE referred_by = ?", (int(referrer_id),)
        ) as cursor:
            row = await cursor.fetchone()
        return int(row["cnt"]) if row else 0

    async def add_free_vip(self, user_id: int, count: int = 1) -> int:
        """Foydalanuvchiga bepul VIP e'lon kreditlarini qo'shadi."""
        await self.conn.execute(
            "UPDATE users SET free_vip = COALESCE(free_vip, 0) + ? WHERE user_id = ?",
            (max(0, int(count)), int(user_id)),
        )
        await self.conn.commit()
        return await self.get_free_vip(user_id)

    async def get_free_vip(self, user_id: int) -> int:
        """Foydalanuvchidagi bepul VIP kreditlari soni."""
        async with self.conn.execute(
            "SELECT COALESCE(free_vip, 0) AS cnt FROM users WHERE user_id = ?", (int(user_id),)
        ) as cursor:
            row = await cursor.fetchone()
        return int(row["cnt"]) if row else 0

    async def consume_free_vip(self, user_id: int) -> bool:
        """Bitta bepul VIP kreditini sarflaydi. Kredit bo'lmasa `False`."""
        cursor = await self.conn.execute(
            "UPDATE users SET free_vip = free_vip - 1 WHERE user_id = ? AND COALESCE(free_vip, 0) > 0",
            (int(user_id),),
        )
        await self.conn.commit()
        return bool(cursor.rowcount)

    # ------------------------------------------------------------- analitika
    async def get_daily_activity(
        self,
        days: int = 7,
        offset_hours: Optional[int] = None,
    ) -> list[dict]:
        """Oxirgi `days` kun uchun kunlik ko'rsatkichlar."""
        shift = int(_runtime().get("TZ_OFFSET_HOURS")) if offset_hours is None else int(offset_hours)
        tz = timezone(timedelta(hours=shift))
        now_local = datetime.now(timezone.utc).astimezone(tz)
        result: list[dict] = []

        for index in range(max(1, int(days)) - 1, -1, -1):
            day = now_local - timedelta(days=index)
            start_local = day.replace(hour=0, minute=0, second=0, microsecond=0)
            end_local = start_local + timedelta(days=1)
            start = start_local.astimezone(timezone.utc).replace(microsecond=0).isoformat()
            end = end_local.astimezone(timezone.utc).replace(microsecond=0).isoformat()

            async with self.conn.execute(
                "SELECT COUNT(*) AS cnt FROM users WHERE joined_at >= ? AND joined_at < ?",
                (start, end),
            ) as cursor:
                row = await cursor.fetchone()
            users = int(row["cnt"]) if row else 0

            async with self.conn.execute(
                "SELECT COUNT(*) AS cnt FROM listings WHERE created_at >= ? AND created_at < ?",
                (start, end),
            ) as cursor:
                row = await cursor.fetchone()
            listings = int(row["cnt"]) if row else 0

            async with self.conn.execute(
                "SELECT COUNT(*) AS cnt FROM listings WHERE sold_at >= ? AND sold_at < ?",
                (start, end),
            ) as cursor:
                row = await cursor.fetchone()
            sold = int(row["cnt"]) if row else 0

            result.append(
                {
                    "date": start_local.strftime("%d.%m"),
                    "users": users,
                    "listings": listings,
                    "sold": sold,
                }
            )
        return result

    async def get_top_sellers(self, days: int = 30, limit: int = 5) -> list[dict]:
        """Oxirgi `days` kunda eng ko'p akkaunt sotgan foydalanuvchilar."""
        since = (
            datetime.now(timezone.utc) - timedelta(days=max(1, int(days)))
        ).replace(microsecond=0).isoformat()
        async with self.conn.execute(
            """
            SELECT user_id, COUNT(*) AS cnt
              FROM listings
             WHERE status IN ('sold', 'found')
               AND COALESCE(sold_at, created_at) >= ?
             GROUP BY user_id
             ORDER BY cnt DESC, user_id ASC
             LIMIT ?
            """,
            (since, int(limit)),
        ) as cursor:
            rows = await cursor.fetchall()
        return [{"user_id": int(row["user_id"]), "count": int(row["cnt"])} for row in rows]

    # ---------------------------------------------------------------- zaxira
    async def backup_to(self, dest_path: str) -> bool:
        """Bazaning izchil nusxasini `dest_path` ga yozadi.

        Avval WAL jurnali checkpoint qilinadi (nusxa to'liq bo'lishi uchun),
        so'ng fayl alohida oqimda ko'chiriladi — event loop bloklanmasin.
        """
        try:
            await self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            await self.conn.commit()
        except Exception as exc:  # checkpoint ishlamasa ham nusxa olishga harakat qilamiz
            logger.warning("WAL checkpoint bajarilmadi: %s", exc)

        try:
            os.makedirs(os.path.dirname(os.path.abspath(dest_path)), exist_ok=True)
            await asyncio.to_thread(shutil.copy2, self.path, dest_path)
            logger.info("Baza nusxasi saqlandi: %s", dest_path)
            return True
        except OSError as exc:
            logger.error("Baza nusxasini saqlab boʻlmadi: %s", exc)
            return False

    async def validate_restore_file(self, source_path: str) -> tuple[bool, str]:
        """Tiklash uchun yuklangan faylning SQLite va sxema mosligini tekshiradi."""
        path = Path(source_path).expanduser()
        try:
            if not path.is_file():
                return False, "Fayl topilmadi."
            if path.stat().st_size < 32:
                return False, "Fayl juda kichik yoki boʻsh."
            with path.open("rb") as source:
                if source.read(16) != b"SQLite format 3\x00":
                    return False, "Fayl SQLite maʼlumotlar bazasi emas."
        except OSError as exc:
            return False, f"Faylni tekshirib boʻlmadi: {exc}"

        def _check() -> tuple[bool, str]:
            try:
                uri = f"file:{path.resolve().as_posix()}?mode=ro"
                with sqlite3.connect(uri, uri=True, timeout=5) as conn:
                    result = conn.execute("PRAGMA integrity_check").fetchone()
                    if not result or str(result[0]).lower() != "ok":
                        return False, "SQLite integritet tekshiruvi muvaffaqiyatsiz."
                    tables = {
                        str(row[0])
                        for row in conn.execute(
                            "SELECT name FROM sqlite_master WHERE type = 'table'"
                        )
                    }
                required = {"settings", "users", "listings"}
                missing = sorted(required - tables)
                if missing:
                    return False, "Baza sxemasi mos emas. Yetishmayotgan jadvallar: " + ", ".join(missing)
                return True, ""
            except (OSError, sqlite3.Error) as exc:
                return False, f"SQLite faylni ochib boʻlmadi: {exc}"

        return await asyncio.to_thread(_check)

    async def restore_from(self, source_path: str) -> tuple[bool, str]:
        """Tasdiqlangan SQLite nusxasini atomik ravishda joriy bazaga tiklaydi.

        Tiklashdan oldin joriy bazaning alohida nusxasi yaratiladi. Agar yangi
        fayl ochilmasa yoki sxema mos kelmasa, avvalgi baza qaytariladi.
        """
        source = Path(source_path).expanduser()
        async with self.restore_lock:
            ok, reason = await self.validate_restore_file(str(source))
            if not ok:
                return False, reason
            if source.resolve() == Path(self.path).resolve():
                return False, "Tiklash fayli joriy bazaning oʻzi boʻlmasligi kerak."

            if self._conn is None:
                return False, "Maʼlumotlar bazasi ulanmagan."
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
            safety_path = f"{self.path}.pre_restore_{stamp}"
            if not await self.backup_to(safety_path):
                return False, "Tiklashdan oldin xavfsizlik nusxasi yaratib boʻlmadi."

            await self.close()
            staged_path: Optional[str] = None
            replaced = False
            try:
                parent = Path(self.path).resolve().parent
                parent.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(
                    prefix="restore_", suffix=".sqlite3", dir=parent, delete=False
                ) as staged:
                    staged_path = staged.name
                await asyncio.to_thread(shutil.copy2, source, staged_path)
                os.replace(staged_path, self.path)
                staged_path = None
                replaced = True
                for suffix in ("-wal", "-shm"):
                    try:
                        os.remove(self.path + suffix)
                    except FileNotFoundError:
                        pass
                await self.connect()
                return True, safety_path
            except Exception as exc:
                logger.exception("Bazani tiklashda xatolik")
                try:
                    await self.close()
                except Exception:
                    logger.exception("Tiklashdan keyin bazani yopib boʻlmadi")
                if replaced:
                    try:
                        os.replace(safety_path, self.path)
                    except OSError:
                        logger.exception("Xavfsizlik nusxasini qaytarib boʻlmadi")
                try:
                    await self.connect()
                except Exception:
                    logger.exception("Tiklashdan keyin bazani ulab boʻlmadi")
                return False, f"Tiklash yakunlanmadi: {exc}"
            finally:
                if staged_path:
                    try:
                        os.remove(staged_path)
                    except OSError:
                        pass

    # ------------------------------------------------------------------- stats
    async def get_stats(self) -> tuple[int, int, int]:
        """(jami foydalanuvchilar, aktiv e'lonlar, sotilgan akkauntlar)."""
        async with self.conn.execute("SELECT COUNT(*) AS cnt FROM users") as cursor:
            row = await cursor.fetchone()
        total_users = int(row["cnt"]) if row else 0

        async with self.conn.execute(
            "SELECT COUNT(*) AS cnt FROM listings WHERE status = 'active'"
        ) as cursor:
            row = await cursor.fetchone()
        active_listings = int(row["cnt"]) if row else 0

        async with self.conn.execute(
            "SELECT COUNT(*) AS cnt FROM listings WHERE status IN ('sold', 'found')"
        ) as cursor:
            row = await cursor.fetchone()
        sold_listings = int(row["cnt"]) if row else 0

        return total_users, active_listings, sold_listings

    async def get_detailed_stats(self) -> dict[str, int]:
        """Batafsil statistika (admin panel uchun)."""
        result = {
            "users": 0,
            "banned": 0,
            "listings": 0,
            "pending": 0,
            "active": 0,
            "sold": 0,
            "rejected": 0,
            "expired": 0,
            "buy_requests": 0,
            "favorites": 0,
            "blacklist": 0,
            "reviews": 0,
            "offers": 0,
            "pending_offers": 0,
            "deals": 0,
            "open_deals": 0,
        }
        async with self.conn.execute("SELECT COUNT(*) AS cnt FROM users") as cursor:
            row = await cursor.fetchone()
        result["users"] = int(row["cnt"]) if row else 0

        async with self.conn.execute(
            "SELECT COUNT(*) AS cnt FROM users WHERE is_banned = 1"
        ) as cursor:
            row = await cursor.fetchone()
        result["banned"] = int(row["cnt"]) if row else 0

        async with self.conn.execute(
            "SELECT status, COUNT(*) AS cnt FROM listings GROUP BY status"
        ) as cursor:
            async for row in cursor:
                count = int(row["cnt"])
                status = str(row["status"] or "")
                result["listings"] += count
                if status in result:
                    result[status] = count

        async with self.conn.execute(
            "SELECT COUNT(*) AS cnt FROM listings WHERE listing_type = 'buy'"
        ) as cursor:
            row = await cursor.fetchone()
        result["buy_requests"] = int(row["cnt"]) if row else 0

        async with self.conn.execute("SELECT COUNT(*) AS cnt FROM favorites") as cursor:
            row = await cursor.fetchone()
        result["favorites"] = int(row["cnt"]) if row else 0

        async with self.conn.execute("SELECT COUNT(*) AS cnt FROM blacklist") as cursor:
            row = await cursor.fetchone()
        result["blacklist"] = int(row["cnt"]) if row else 0

        async with self.conn.execute("SELECT COUNT(*) AS cnt FROM reviews") as cursor:
            row = await cursor.fetchone()
        result["reviews"] = int(row["cnt"]) if row else 0

        async with self.conn.execute("SELECT COUNT(*) AS cnt FROM offers") as cursor:
            row = await cursor.fetchone()
        result["offers"] = int(row["cnt"]) if row else 0

        async with self.conn.execute(
            "SELECT COUNT(*) AS cnt FROM offers WHERE status = 'pending'"
        ) as cursor:
            row = await cursor.fetchone()
        result["pending_offers"] = int(row["cnt"]) if row else 0

        async with self.conn.execute("SELECT COUNT(*) AS cnt FROM deals") as cursor:
            row = await cursor.fetchone()
        result["deals"] = int(row["cnt"]) if row else 0

        async with self.conn.execute(
            "SELECT COUNT(*) AS cnt FROM deals WHERE status IN ('new', 'garant')"
        ) as cursor:
            row = await cursor.fetchone()
        result["open_deals"] = int(row["cnt"]) if row else 0

        return result


# Global obyekt: barcha handlerlar shundan foydalanadi
db = Database()
