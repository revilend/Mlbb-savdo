"""Bot konfiguratsiyasi.

Barcha sozlamalar `.env` faylidan (yoki muhit o'zgaruvchilaridan) o'qiladi.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent

# .env faylini loyiha ildizidan yuklaymiz (mavjud bo'lmasa jim o'tadi)
load_dotenv(BASE_DIR / ".env")

_TRUE_VALUES = {"1", "true", "yes", "on", "ha", "y"}
_FALSE_VALUES = {"0", "false", "no", "off", "yoq", "yo'q", "n"}


def _env_str(name: str, default: str = "") -> str:
    """Muhit o'zgaruvchisini matn sifatida o'qish."""
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip()


def _env_int(name: str, default: int = 0) -> int:
    """Muhit o'zgaruvchisini butun son sifatida o'qish."""
    raw = _env_str(name)
    if not raw:
        return default
    cleaned = "".join(ch for ch in raw if ch.isdigit() or ch == "-")
    try:
        return int(cleaned)
    except ValueError:
        return default


def _env_float(name: str, default: float = 0.0) -> float:
    """Muhit o'zgaruvchisini o'nlik son sifatida o'qish."""
    raw = _env_str(name).replace(",", ".")
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_bool(name: str, default: bool = False) -> bool:
    """Muhit o'zgaruvchisini mantiqiy qiymat sifatida o'qish."""
    raw = _env_str(name).lower()
    if not raw:
        return default
    if raw in _TRUE_VALUES:
        return True
    if raw in _FALSE_VALUES:
        return False
    return default


def _env_int_list(name: str, default: tuple[int, ...] = ()) -> list[int]:
    """Vergul bilan ajratilgan ID ro'yxatini o'qish (masalan: ``1,42,-100123``)."""
    raw = _env_str(name)
    if not raw:
        return list(default)
    result: list[int] = []
    for chunk in raw.replace(";", ",").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        cleaned = "".join(ch for ch in chunk if ch.isdigit() or ch == "-")
        if cleaned.lstrip("-").isdigit():
            result.append(int(cleaned))
    return result or list(default)


# --- Asosiy sozlamalar -------------------------------------------------------
BOT_TOKEN: str = _env_str("BOT_TOKEN")
ADMIN_ID: int = _env_int("ADMIN_ID", 0)
DEFAULT_CHANNEL_ID: str = _env_str("DEFAULT_CHANNEL_ID", "@mlbb_savdo")

_garant_raw = _env_str("GARANT_USERNAME", "my_garant")
GARANT_USERNAME: str = _garant_raw.lstrip("@").strip() or "my_garant"
GARANT_URL: str = f"https://t.me/{GARANT_USERNAME}"

# --- Baza --------------------------------------------------------------------
DB_PATH: str = _env_str("DB_PATH", "market_database.sqlite3") or "market_database.sqlite3"

# --- Bot identifikatori ------------------------------------------------------
# Ishga tushganda `bot.get_me()` orqali avtomatik aniqlanadi;
# bu qiymat faqat zaxira sifatida ishlatiladi (masalan, testlarda).
BOT_USERNAME: str = _env_str("BOT_USERNAME").lstrip("@")

# --- Kunlik hisobot ---------------------------------------------------------
# Hisobot mahalliy vaqt bilan yuboriladi; Oʻzbekiston = UTC+5.
TZ_OFFSET_HOURS: int = max(-12, min(14, _env_int("TZ_OFFSET_HOURS", 5)))
DIGEST_HOUR: int = min(23, max(0, _env_int("DIGEST_HOUR", 23)))
DIGEST_MINUTE: int = min(59, max(0, _env_int("DIGEST_MINUTE", 59)))

# --- AI moderatsiya ---------------------------------------------------------
# Bu qiymatlar bot ichidagi «🤖 AI moderatsiya» panelidan ham o'zgartiriladi;
# bu yerdagilar faqat standart (boshlang'ich) qiymat hisoblanadi.
AI_ENABLED: bool = _env_bool("AI_ENABLED", False)
AI_API_KEY: str = _env_str("AI_API_KEY")
AI_BASE_URL: str = (
    _env_str("AI_BASE_URL", "https://openrouter.ai/api/v1")
    or "https://openrouter.ai/api/v1"
)
AI_MODEL: str = _env_str("AI_MODEL", "openai/gpt-4o-mini") or "openai/gpt-4o-mini"
AI_AUTO_APPROVE: bool = _env_bool("AI_AUTO_APPROVE", False)
AI_MIN_CONFIDENCE: int = min(100, max(0, _env_int("AI_MIN_CONFIDENCE", 70)))
AI_REJECT_SCAMS: bool = _env_bool("AI_REJECT_SCAMS", True)
AI_TIMEOUT_SECONDS: int = max(5, min(120, _env_int("AI_TIMEOUT_SECONDS", 20)))
AI_EXTRA_RULES: str = _env_str("AI_EXTRA_RULES")

# --- Biznes qoidalari --------------------------------------------------------
MAX_PHOTOS: int = 10
MAX_DESCRIPTION_LENGTH: int = 300
BUMP_COOLDOWN_HOURS: int = 24
MIN_PRICE: int = 1_000
MAX_PRICE: int = 100_000_000_000
# E'lonning amal qilish muddati (kun). Muddati o'tgan e'lon arxivga tushadi
# va egasi «🔄 Yangilash» tugmasi orqali uni qayta tiklay oladi.
LISTING_TTL_DAYS: int = max(1, _env_int("LISTING_TTL_DAYS", 14))
# O'xshash e'lonlar qidiruvida narx farqi (±foiz)
SIMILAR_PRICE_TOLERANCE: float = max(0.05, _env_float("SIMILAR_PRICE_TOLERANCE", 0.3))
# Referal: har bir taklif qilingan do'st uchun beriladigan bepul VIP e'lonlar
REFERRAL_REWARD_VIP: int = max(0, _env_int("REFERRAL_REWARD_VIP", 1))

# --- Kunning tanlovi posti ---------------------------------------------------
# Kanalga har kuni tanlangan (VIP/tasodifiy) e'lonni chiqaradigan post.
FEATURED_ENABLED: bool = _env_bool("FEATURED_ENABLED", True)
FEATURED_HOUR: int = min(23, max(0, _env_int("FEATURED_HOUR", 12)))
FEATURED_MINUTE: int = min(59, max(0, _env_int("FEATURED_MINUTE", 0)))

# --- Zaxira nusxa (backup) ---------------------------------------------------
BACKUP_ENABLED: bool = _env_bool("BACKUP_ENABLED", True)
BACKUP_DIR: str = _env_str("BACKUP_DIR", "backups") or "backups"
BACKUP_HOUR: int = min(23, max(0, _env_int("BACKUP_HOUR", 3)))
BACKUP_KEEP: int = max(1, _env_int("BACKUP_KEEP", 7))

# --- Anti-flood (spam himoyasi) ---------------------------------------------
# Sukut bo'yicha "yumshatilgan" rejim: oddiy foydalanuvchi sezmaydi, lekin
# botni Telegram tomonidan cheklanishdan himoya qiladi.
FLOOD_PROTECTION: bool = _env_bool("FLOOD_PROTECTION", True)
FLOOD_WINDOW_SECONDS: float = max(0.5, _env_float("FLOOD_WINDOW_SECONDS", 5.0))
FLOOD_MAX_EVENTS: int = max(1, _env_int("FLOOD_MAX_EVENTS", 12))
FLOOD_NOTICE_COOLDOWN: float = max(0.0, _env_float("FLOOD_NOTICE_COOLDOWN", 4.0))
FLOOD_VIOLATION_LIMIT: int = max(1, _env_int("FLOOD_VIOLATION_LIMIT", 5))
FLOOD_MUTE_SECONDS: int = max(5, _env_int("FLOOD_MUTE_SECONDS", 30))
FLOOD_MUTE_RESET_SECONDS: int = max(10, _env_int("FLOOD_MUTE_RESET_SECONDS", 120))
FLOOD_WARNING_TTL: int = max(3, _env_int("FLOOD_WARNING_TTL", 6))
# Yumshoq rejim: foydalanuvchining xabarlari o'chirilmaydi
FLOOD_DELETE_MESSAGES: bool = _env_bool("FLOOD_DELETE_MESSAGES", False)
# Umuman ogohlantirmasdan jim turish (faqat takroriy so'rovni o'tkazib yuboradi)
FLOOD_NOTIFY: bool = _env_bool("FLOOD_NOTIFY", True)
FLOOD_BYPASS_ADMIN: bool = _env_bool("FLOOD_BYPASS_ADMIN", True)

# --- O'z-o'zini o'chiruvchi xabarlar ----------------------------------------
SELF_DESTRUCT_ENABLED: bool = _env_bool("SELF_DESTRUCT_ENABLED", True)
SELF_DESTRUCT_DEFAULT_TTL: int = max(0, _env_int("SELF_DESTRUCT_DEFAULT_TTL", 300))
SELF_DESTRUCT_NOTICE_TTL: int = max(0, _env_int("SELF_DESTRUCT_NOTICE_TTL", 12))
SELF_DESTRUCT_USER_MESSAGES: bool = _env_bool("SELF_DESTRUCT_USER_MESSAGES", False)
SELF_DESTRUCT_USER_TTL: int = max(0, _env_int("SELF_DESTRUCT_USER_TTL", 600))
CLEANER_TRACK_LIMIT: int = max(5, _env_int("CLEANER_TRACK_LIMIT", 40))
# Kanallar/guruhlar va administrator chati hech qachon tozalanmaydi
SELF_DESTRUCT_SKIP_CHAT_IDS: list[int] = _env_int_list(
    "SELF_DESTRUCT_SKIP_CHAT_IDS", default=(ADMIN_ID,) if ADMIN_ID else ()
)


def validate() -> None:
    """Majburiy sozlamalar to'ldirilganligini tekshiradi."""
    missing: list[str] = []
    if not BOT_TOKEN:
        missing.append("BOT_TOKEN")
    if not ADMIN_ID:
        missing.append("ADMIN_ID")
    if missing:
        raise SystemExit(
            "❌ Quyidagi sozlamalar .env faylida koʻrsatilmagan: " + ", ".join(missing)
        )
