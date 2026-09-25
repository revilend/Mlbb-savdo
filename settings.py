"""Bot ichidan boshqariladigan runtime sozlamalar.

Ish printsipi:

* `.env` (ya'ni :mod:`config`) qiymatlari — **standart** qiymat bo'lib qoladi;
* admin panel orqali kiritilgan qiymatlar `settings` jadvalida
  ``cfg:<KALIT>`` ko'rinishida saqlanadi;
* :func:`get` har doim avval baza orqali kiritilgan qiymatni, bo'lmasa
  `.env` dagi standartni qaytaradi.

Shu tufayli botni **texnik bilimsiz** ham sozlash mumkin: kanal, narx
chegaralari, vaqtlar, AI kaliti va hokazo — hammasi bot ichida.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional

import config

# ---------------------------------------------------------------------------
# Doimiy qiymatlar
# ---------------------------------------------------------------------------
_TRUE_VALUES = {"1", "true", "yes", "on", "ha", "y", "yoqilgan"}
_FALSE_VALUES = {"0", "false", "no", "off", "yoq", "yo'q", "oʻchiq", "oʻchirilgan", "n"}

#: Sozlama guruhlari (admin panelda bo'limlar sifatida ko'rsatiladi)
GROUPS: dict[str, str] = {
    "prices": "💰 Narx va eʼlonlar",
    "time": "⏰ Vaqt va hisobot",
    "channels": "📣 Kanal va garant",
    "ai": "🤖 AI moderatsiya",
    "backup": "💾 Zaxira nusxa",
    "flood": "🐢 Anti-flood",
    "messages": "⏱ Xabarlar va tozalash",
}


@dataclass(frozen=True)
class Setting:
    """Bitta boshqariladigan sozlama tavsifi."""

    key: str
    label: str
    group: str
    kind: str  # 'int' | 'float' | 'bool' | 'str' | 'secret'
    env_attr: str = ""  # `config` dagi sukut qiymat atributi
    description: str = ""
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    unit: str = ""
    restart: bool = False
    minimum_length: Optional[int] = None

    @property
    def source_attr(self) -> str:
        """Standart qiymat olinadigan `config` atributi nomi."""
        return self.env_attr or self.key


#: Barcha boshqariladigan sozlamalar. Ro'yxat tartibi panelda ko'rinadigan tartib.
SETTINGS: tuple[Setting, ...] = (
    # --- Narx va e'lonlar -------------------------------------------------
    Setting("MIN_PRICE", "Eng kam narx", "prices", "int", minimum=0,
            maximum=100_000_000, unit="soʻm"),
    Setting("MAX_PRICE", "Eng yuqori narx", "prices", "int", minimum=1_000,
            maximum=1_000_000_000_000, unit="soʻm"),
    Setting("MAX_PHOTOS", "Eʼlonda maksimal rasm", "prices", "int",
            minimum=1, maximum=10, unit="ta"),
    Setting("MAX_DESCRIPTION_LENGTH", "Izoh uzunligi", "prices", "int",
            minimum=50, maximum=1_000, unit="belgi"),
    Setting("LISTING_TTL_DAYS", "Eʼlon amal muddati", "prices", "int",
            minimum=1, maximum=365, unit="kun"),
    Setting("BUMP_COOLDOWN_HOURS", "UP orasidagi tanaffus", "prices", "int",
            minimum=1, maximum=168, unit="soat"),
    Setting("SIMILAR_PRICE_TOLERANCE", "Oʻxshash narx farqi (±)", "prices",
            "float", minimum=0.05, maximum=2.0, unit="ulush"),
    Setting("REFERRAL_REWARD_VIP", "Referal uchun VIP", "prices", "int",
            minimum=0, maximum=100, unit="ta"),
    # --- Vaqt va hisobot --------------------------------------------------
    Setting("TZ_OFFSET_HOURS", "Vaqt mintaqasi (UTC±)", "time", "int",
            minimum=-12, maximum=14, unit="soat"),
    Setting("DIGEST_HOUR", "Kunlik hisobot — soat", "time", "int",
            minimum=0, maximum=23),
    Setting("DIGEST_MINUTE", "Kunlik hisobot — daqiqa", "time", "int",
            minimum=0, maximum=59),
    Setting("FEATURED_ENABLED", "Kunning tanlovi posti", "time", "bool"),
    Setting("FEATURED_HOUR", "Kunning tanlovi — soat", "time", "int",
            minimum=0, maximum=23),
    Setting("FEATURED_MINUTE", "Kunning tanlovi — daqiqa", "time", "int",
            minimum=0, maximum=59),
    # --- Kanal va garant --------------------------------------------------
    Setting("DEFAULT_CHANNEL_ID", "Asosiy kanal", "channels", "str",
            description="Masalan @mlbb_savdo yoki -1001234567890"),
    Setting("GARANT_USERNAME", "Garant akkaunti", "channels", "str",
            description="@ belgisisiz, masalan mlbbSATORU"),
    # --- AI moderatsiya ---------------------------------------------------
    Setting("AI_ENABLED", "AI moderatsiya", "ai", "bool",
            description="Eʼlonlarni AI orqali avtomatik tekshirish"),
    Setting("AI_API_KEY", "AI API kaliti", "ai", "secret",
            description="OpenRouter / OpenAI / Groq va h.k. kaliti"),
    Setting("AI_BASE_URL", "AI manzili (base URL)", "ai", "str",
            description="Masalan https://openrouter.ai/api/v1"),
    Setting("AI_MODEL", "AI modeli", "ai", "str",
            description="Masalan openai/gpt-4o-mini"),
    Setting("AI_AUTO_APPROVE", "Avtomatik tasdiqlash", "ai", "bool",
            description="AI ishonchli deb topsa eʼlon kanalga oʻzi chiqadi"),
    Setting("AI_MIN_CONFIDENCE", "Avtomatik tasdiqlash ishonchi", "ai", "int",
            minimum=0, maximum=100, unit="%"),
    Setting("AI_REJECT_SCAMS", "Firibgarlikni avtomatik rad etish", "ai", "bool",
            description="AI aniq firibgarlikni topsa eʼlon rad etiladi"),
    Setting("AI_TIMEOUT_SECONDS", "AI javob kutish vaqti", "ai", "int",
            minimum=5, maximum=120, unit="sek"),
    Setting("AI_EXTRA_RULES", "AI uchun qoʻshimcha qoidalar", "ai", "str",
            minimum_length=0,
            description="Boʻsh qoldirsangiz standart qoidalar ishlaydi"),
    # --- Zaxira nusxa -----------------------------------------------------
    Setting("BACKUP_ENABLED", "Kunlik zaxira nusxa", "backup", "bool"),
    Setting("BACKUP_HOUR", "Zaxira vaqti — soat", "backup", "int",
            minimum=0, maximum=23),
    Setting("BACKUP_KEEP", "Saqlanadigan nusxalar", "backup", "int",
            minimum=1, maximum=90, unit="ta"),
    Setting("BACKUP_DIR", "Nusxalar papkasi", "backup", "str"),
    # --- Anti-flood (restart kerak) ---------------------------------------
    Setting("FLOOD_PROTECTION", "Anti-flood himoyasi", "flood", "bool", restart=True),
    Setting("FLOOD_WINDOW_SECONDS", "Kuzatuv oynasi", "flood", "float",
            minimum=0.5, maximum=60, unit="sek", restart=True),
    Setting("FLOOD_MAX_EVENTS", "Oynadagi hodisalar", "flood", "int",
            minimum=1, maximum=200, restart=True),
    Setting("FLOOD_NOTICE_COOLDOWN", "Ogohlantirish tanaffusi", "flood", "float",
            minimum=0, maximum=60, unit="sek", restart=True),
    Setting("FLOOD_VIOLATION_LIMIT", "Mute chegarasi", "flood", "int",
            minimum=1, maximum=50, restart=True),
    Setting("FLOOD_MUTE_SECONDS", "Mute davomiyligi", "flood", "int",
            minimum=5, maximum=3_600, unit="sek", restart=True),
    Setting("FLOOD_MUTE_RESET_SECONDS", "Hisobni nolga tushirish", "flood", "int",
            minimum=10, maximum=3_600, unit="sek", restart=True),
    Setting("FLOOD_WARNING_TTL", "Ogohlantirish umri", "flood", "int",
            minimum=3, maximum=120, unit="sek", restart=True),
    Setting("FLOOD_DELETE_MESSAGES", "Spam xabarlarni oʻchirish", "flood", "bool",
            restart=True),
    Setting("FLOOD_NOTIFY", "Ogohlantirish yuborish", "flood", "bool", restart=True),
    Setting("FLOOD_BYPASS_ADMIN", "Adminlarni ozod qilish", "flood", "bool",
            restart=True),
    # --- Xabarlar va tozalash (restart kerak) ----------------------------
    Setting("SELF_DESTRUCT_ENABLED", "Xabarlarni oʻchirish xizmati", "messages",
            "bool", restart=True),
    Setting("SELF_DESTRUCT_DEFAULT_TTL", "Bot xabari umri", "messages", "int",
            minimum=0, maximum=86_400, unit="sek", restart=True),
    Setting("SELF_DESTRUCT_NOTICE_TTL", "Qisqa bildirishnoma umri", "messages",
            "int", minimum=0, maximum=3_600, unit="sek", restart=True),
    Setting("SELF_DESTRUCT_USER_MESSAGES", "Foydalanuvchi xabarlarini oʻchirish",
            "messages", "bool", restart=True),
    Setting("SELF_DESTRUCT_USER_TTL", "Foydalanuvchi xabari umri", "messages",
            "int", minimum=0, maximum=86_400, unit="sek", restart=True),
    Setting("CLEANER_TRACK_LIMIT", "/clean uchun yozuvlar", "messages", "int",
            minimum=5, maximum=500, restart=True),
)

#: Kalit -> Setting tez qidiruv uchun
SPEC: dict[str, Setting] = {item.key: item for item in SETTINGS}

#: Guruhdagi sozlamalar tartibi
_GROUP_ORDER: dict[str, list[str]] = {}
for _item in SETTINGS:
    _GROUP_ORDER.setdefault(_item.group, []).append(_item.key)


class SettingsError(ValueError):
    """Sozlama qiymati yaroqsiz bo'lganda ko'tariladi."""


# ---------------------------------------------------------------------------
# Tahlil va tekshirish
# ---------------------------------------------------------------------------
def parse_bool(text: str) -> Optional[bool]:
    """Matnni mantiqiy qiymatga aylantiradi (bilmagani uchun `None`)."""
    lowered = (text or "").strip().lower()
    if lowered in _TRUE_VALUES:
        return True
    if lowered in _FALSE_VALUES:
        return False
    return None


def _clean_number(text: str) -> str:
    """Raqamdan bo'shliq va ajratuvchi belgilarni olib tashlaydi."""
    return (text or "").replace(" ", "").replace("\u00a0", "").replace("_", "")


def validate(spec: Setting, text: str) -> Any:
    """Qiymatni tekshiradi va tayyor (tiplangan) ko'rinishini qaytaradi.

    :raises SettingsError: qiymat yaroqsiz bo'lsa.
    """
    raw = (text or "").strip()

    if spec.kind == "bool":
        value = parse_bool(raw)
        if value is None:
            raise SettingsError(
                "Faqat «yoqish» yoki «oʻchirish» tanlanadi (tugma orqali)."
            )
        return value

    if spec.kind == "int":
        cleaned = _clean_number(raw)
        try:
            number = int(cleaned)
        except (TypeError, ValueError) as exc:
            raise SettingsError("Butun son kiriting. Masalan: 14") from exc
        _check_range(spec, number)
        return number

    if spec.kind == "float":
        cleaned = _clean_number(raw).replace(",", ".")
        try:
            value = float(cleaned)
        except (TypeError, ValueError) as exc:
            raise SettingsError("Son kiriting. Masalan: 0.3") from exc
        _check_range(spec, value)
        return value

    if spec.kind == "secret":
        if len(raw) < 8:
            raise SettingsError("Kalit juda qisqa (kamida 8 belgi).")
        if len(raw) > 400:
            raise SettingsError("Kalit juda uzun.")
        return raw

    # 'str'
    minimum = 1 if spec.minimum_length is None else spec.minimum_length
    if len(raw) < minimum:
        raise SettingsError("Qiymat boʻsh boʻlmasligi kerak.")
    if len(raw) > 300:
        raise SettingsError("Qiymat juda uzun (300 belgidan oshmasin).")

    if spec.key == "AI_BASE_URL" and not raw.startswith(("http://", "https://")):
        raise SettingsError("Manzil http:// yoki https:// bilan boshlanishi kerak.")
    if spec.key == "GARANT_USERNAME":
        cleaned = raw.lstrip("@").strip()
        if not re.fullmatch(r"[A-Za-z0-9_]{3,32}", cleaned):
            raise SettingsError("Username faqat harf, raqam va _ dan iborat boʻlsin.")
        return cleaned
    if spec.key == "DEFAULT_CHANNEL_ID":
        cleaned = raw.strip()
        if not (cleaned.startswith("@") or cleaned.lstrip("-").isdigit()):
            raise SettingsError("Kanal @username yoki -100... koʻrinishida boʻlsin.")
        return cleaned
    return raw


def _check_range(spec: Setting, value: float) -> None:
    """Son qiymatni ruxsat etilgan oraliqda tekshiradi."""
    if spec.minimum is not None and value < spec.minimum:
        raise SettingsError(f"Qiymat {spec.minimum} dan kichik boʻlmasin.")
    if spec.maximum is not None and value > spec.maximum:
        raise SettingsError(f"Qiymat {spec.maximum} dan katta boʻlmasin.")


def mask_secret(value: str) -> str:
    """Maxfiy qiymatni ko'rsatish uchun niqoblaydi."""
    if not value:
        return "— sozlanmagan"
    if len(value) <= 10:
        return "•" * len(value)
    return f"{value[:4]}…{value[-4:]}"


# ---------------------------------------------------------------------------
# Do'kon
# ---------------------------------------------------------------------------
class SettingsStore:
    """Bazadagi ustun qiymatlarni xotirada saqlaydigan yupqa qatlam."""

    PREFIX = "cfg:"

    #: Eski `my_garant` placeholder'ini yangi garant akkauntiga ko'chirish.
    #: Doimiy diskda eski qiymat qolib ketsa, tugma yana `@my_garant` ko'rsatardi.
    _LEGACY_MIGRATIONS = {"GARANT_USERNAME": ("my_garant", config.DEFAULT_GARANT_USERNAME)}

    def __init__(self) -> None:
        self._raw: dict[str, str] = {}

    # ------------------------------------------------------------- yuklash
    def load(self, raw: dict[str, str]) -> None:
        """Bazadan o'qilgan qiymatlarni xotiraga oladi.

        Kalitlar ``cfg:`` prefiksi bilan ham, usiz ham qabul qilinadi;
        noma'lum kalitlar e'tiborsiz qoldiriladi.
        """
        values: dict[str, str] = {}
        for key, value in (raw or {}).items():
            clean = key[len(self.PREFIX):] if key.startswith(self.PREFIX) else key
            if clean in SPEC:
                values[clean] = value
        self._migrate_legacy(values)
        self._raw = values

    @staticmethod
    def _migrate_legacy(values: dict[str, str]) -> None:
        """Eski placeholder qiymatlarni joriy standartga almashtiradi."""
        for key, (old, new) in SettingsStore._LEGACY_MIGRATIONS.items():
            if key in values and values[key] == old and new != old:
                values[key] = new

    def as_dict(self) -> dict[str, str]:
        """Xotiradagi qiymatlar nusxasi (testlar uchun foydali)."""
        return dict(self._raw)

    # --------------------------------------------------------------- o'qish
    @staticmethod
    def spec(key: str) -> Setting:
        """Kalit bo'yicha sozlama tavsifini qaytaradi."""
        try:
            return SPEC[key]
        except KeyError as exc:  # pragma: no cover - ichki xatolik himoyasi
            raise SettingsError(f"Nomaʼlum sozlama: {key}") from exc

    def is_overridden(self, key: str) -> bool:
        """Qiymat bot ichidan o'zgartirilganmi?"""
        return key in self._raw

    def source(self, key: str) -> str:
        """`'bot'` — bot ichidan kiritilgan, `'env'` — standart qiymat."""
        return "bot" if self.is_overridden(key) else "env"

    def default(self, key: str) -> Any:
        """`.env` dagi standart qiymat."""
        spec = self.spec(key)
        value = getattr(config, spec.source_attr, None)
        if spec.kind == "bool" and value is None:
            return False
        if spec.kind in ("int", "float") and value is None:
            return 0
        if spec.kind in ("str", "secret") and value is None:
            return ""
        return value

    def get(self, key: str) -> Any:
        """Amaldagi qiymat: avval bot ichidan kiritilgan, keyin standart."""
        spec = self.spec(key)
        if key in self._raw:
            try:
                return validate(spec, self._raw[key])
            except SettingsError:
                # Baza buzilgan bo'lsa standartga qaytamiz — bot ishlashda davom etsin
                pass
        return self.default(key)

    def get_str(self, key: str) -> str:
        """Qiymatni matn sifatida qaytaradi."""
        value = self.get(key)
        if isinstance(value, bool):
            return "true" if value else "false"
        return "" if value is None else str(value)

    def get_bool(self, key: str) -> bool:
        """Qiymatni mantiqiy ko'rinishda qaytaradi."""
        value = self.get(key)
        if isinstance(value, bool):
            return value
        parsed = parse_bool(str(value))
        return bool(parsed) if parsed is not None else False

    def display(self, key: str) -> str:
        """Panelda ko'rsatiladigan qisqa qiymat."""
        spec = self.spec(key)
        value = self.get(key)

        if spec.kind == "bool":
            return "✅ Yoqilgan" if value else "⛔️ Oʻchirilgan"
        if spec.kind == "secret":
            return mask_secret(str(value or ""))
        if spec.kind in ("int", "float"):
            if spec.kind == "float":
                text = f"{value:g}"
            else:
                number = int(value)
                text = f"{number:,}".replace(",", " ") if 1_000 <= number < 1_000_000_000 else str(number)
            return text + (f" {spec.unit}" if spec.unit else "")
        text = str(value or "—")
        return text if len(text) <= 40 else text[:37] + "…"

    def edit_hint(self, key: str) -> str:
        """FSM so'rovida ko'rsatiladigan izoh."""
        spec = self.spec(key)
        if spec.kind == "int":
            hint = f"Butun son kiriting ({spec.minimum}–{spec.maximum})"
            return hint + (f", {spec.unit}" if spec.unit else "")
        if spec.kind == "float":
            return f"Son kiriting ({spec.minimum}–{spec.maximum})"
        if spec.kind == "secret":
            return "Yangi kalitni yuboring (xabar o'chirilmaydi — ehtiyot boʻling)"
        return spec.description or "Yangi qiymatni yuboring"

    # ------------------------------------------------------------- yozish
    async def set(self, key: str, text: str) -> tuple[bool, str]:
        """Qiymatni tekshirib, bazaga va xotiraga yozadi."""
        spec = SPEC.get(key)
        if spec is None:
            return False, "❌ Nomaʼlum sozlama."

        try:
            value = validate(spec, text)
        except SettingsError as exc:
            return False, f"❌ {exc}"

        stored = self._serialize(spec, value)
        # Kechiktirilgan import: `database` shu modulga murojaat qiladi
        from database import db

        await db.set_setting(self.PREFIX + key, stored)
        self._raw[key] = stored
        return True, f"✅ <b>{spec.label}</b> → {self.display(key)}"

    async def reset(self, key: str) -> bool:
        """Sozlamani `.env` dagi standart qiymatga qaytaradi."""
        if key not in SPEC:
            return False
        was_overridden = key in self._raw
        from database import db

        await db.delete_setting(self.PREFIX + key)
        self._raw.pop(key, None)
        return was_overridden

    async def reset_group(self, group: str) -> int:
        """Guruhdagi barcha sozlamalarni standartga qaytaradi."""
        count = 0
        for key in _GROUP_ORDER.get(group, []):
            if await self.reset(key):
                count += 1
        return count

    @staticmethod
    def _serialize(spec: Setting, value: Any) -> str:
        """Qiymatni bazaga yoziladigan matnga aylantiradi."""
        if spec.kind == "bool":
            return "true" if value else "false"
        return str(value)

    # -------------------------------------------------------------- panel
    @staticmethod
    def group_items(group: str) -> list[Setting]:
        """Guruhdagi sozlamalar ro'yxati (tartib saqlanadi)."""
        return [SPEC[key] for key in _GROUP_ORDER.get(group, [])]

    @staticmethod
    def group_label(group: str) -> str:
        """Guruh uchun ko'rinadigan nom."""
        return GROUPS.get(group, group)

    def overridden_count(self) -> int:
        """Bot ichidan o'zgartirilgan sozlamalar soni."""
        return sum(1 for key in self._raw if key in SPEC)

    @staticmethod
    def total_count() -> int:
        """Jami boshqariladigan sozlamalar soni."""
        return len(SETTINGS)


#: Global do'kon: butun bot shundan foydalanadi
settings = SettingsStore()


__all__ = [
    "GROUPS",
    "SETTINGS",
    "SPEC",
    "Setting",
    "SettingsError",
    "SettingsStore",
    "mask_secret",
    "parse_bool",
    "settings",
    "validate",
]
