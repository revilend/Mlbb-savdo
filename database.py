"""Ma'lumotlar bazasi qatlami (aiosqlite).

Barcha jadvallar `Database.connect()` chaqirilganda yaratiladi.
Butun modul bo'ylab bitta global `db` obyekti ishlatiladi.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

import aiosqlite

logger = logging.getLogger(__name__)

DB_PATH = "market_database.sqlite3"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS users (
    user_id   INTEGER PRIMARY KEY,
    username  TEXT,
    full_name TEXT,
    is_banned INTEGER DEFAULT 0,
    joined_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS listings (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL,
    listing_type    TEXT NOT NULL DEFAULT 'sell',
    rank_info       TEXT,
    skins_info      TEXT,
    price_numeric   INTEGER,
    price_display   TEXT,
    contact         TEXT,
    description     TEXT,
    is_vip          INTEGER DEFAULT 0,
    photos          TEXT,
    channel_msg_id  INTEGER,
    status          TEXT DEFAULT 'pending',
    last_bumped     TIMESTAMP,
    created_at      TIMESTAMP
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
"""


def utcnow_iso() -> str:
    """Hozirgi UTC vaqtni ISO ko'rinishida qaytaradi (sekundlar aniqligida)."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


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
        await self._conn.commit()
        logger.info("Maʼlumotlar bazasi tayyor: %s", self.path)

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

    # ------------------------------------------------------------------- users
    async def add_user(
        self,
        user_id: int,
        username: Optional[str] = None,
        full_name: Optional[str] = None,
    ) -> None:
        """Foydalanuvchini qo'shadi yoki ma'lumotlarini yangilaydi."""
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
    ) -> int:
        """Yangi e'lon yaratadi va uning ID sini qaytaradi."""
        photos = photos or []
        created = utcnow_iso()
        cursor = await self.conn.execute(
            """
            INSERT INTO listings (
                user_id, listing_type, rank_info, skins_info, price_numeric,
                price_display, contact, description, is_vip, photos,
                channel_msg_id, status, last_bumped, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, NULL, ?)
            """,
            (
                user_id,
                listing_type,
                rank_info,
                skins_info,
                price_numeric,
                price_display,
                contact,
                description,
                1 if is_vip else 0,
                json.dumps(photos, ensure_ascii=False),
                status,
                created,
            ),
        )
        await self.conn.commit()
        listing_id = int(cursor.lastrowid or 0)
        logger.info("Yangi eʼlon #%s (user=%s, turi=%s)", listing_id, user_id, listing_type)
        return listing_id

    async def get_listing(self, listing_id: int) -> Optional[dict]:
        """E'lonni ID bo'yicha qaytaradi."""
        async with self.conn.execute(
            "SELECT * FROM listings WHERE id = ?", (listing_id,)
        ) as cursor:
            row = await cursor.fetchone()
        return self._normalize_listing(row)

    async def update_listing_status(self, listing_id: int, status: str) -> None:
        """E'lon holatini o'zgartiradi."""
        await self.conn.execute(
            "UPDATE listings SET status = ? WHERE id = ?", (status, listing_id)
        )
        await self.conn.commit()

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
            "buy_requests": 0,
            "favorites": 0,
            "blacklist": 0,
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

        return result


# Global obyekt: barcha handlerlar shundan foydalanadi
db = Database()
