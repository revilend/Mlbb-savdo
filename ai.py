"""AI moderatsiya mijozi.

Bot **OpenAI-mos** `chat/completions` API'si bilan ishlaydi, shuning uchun
bitta kalit bilan OpenRouter, OpenAI, Groq, DeepInfra, Together, Mistral
yoki o'z serveringizdan foydalanish mumkin. Qo'shimcha ravishda **Google
Gemini** (`generateContent`) ham qo'llab-quvvatlanadi — kalit qaysi
provayderniki bo'lsa, `auto` rejimda o'zi aniqlaydi.

E'lon matni **va rasmlari** tahlil qilinadi: rasm fayllari Telegram'dan
yuklanib, modelga `data:`/base64 ko'rinishida yuboriladi.

Manzil (`AI_BASE_URL`), model (`AI_MODEL`) va kalit (`AI_API_KEY`) —
hammasi bot ichidagi paneldan o'zgartiriladi. Kalit ishlamay qolsa
«📋 Modellarni ko'rish» tugmasi orqali mavjud modellar ro'yxatini ko'rib,
to'g'risini tanlab qo'yish mumkin.

Moderatsiya **matn** asosida ishlaydi (rank, skinlar, narx, izoh, aloqa)
va `approve` / `reject` / `review` qarorini ishonch darajasi bilan qaytaradi.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Optional

import aiohttp

from settings import settings

logger = logging.getLogger(__name__)

#: Qaror turlari
APPROVE = "approve"
REJECT = "reject"
REVIEW = "review"

_DECISION_ALIASES: dict[str, str] = {
    "approve": APPROVE,
    "approved": APPROVE,
    "ok": APPROVE,
    "allow": APPROVE,
    "ha": APPROVE,
    "qabul": APPROVE,
    "accept": APPROVE,
    "reject": REJECT,
    "rejected": REJECT,
    "ban": REJECT,
    "block": REJECT,
    "blok": REJECT,
    "no": REJECT,
    "rad": REJECT,
    "review": REVIEW,
    "manual": REVIEW,
    "human": REVIEW,
    "review_manual": REVIEW,
    "tekshirish": REVIEW,
    "unknown": REVIEW,
}

RISK_LABELS: dict[str, str] = {
    "ok": "✅ Muammo topilmadi",
    "scam": "🚨 Firibgarlik belgisi",
    "spam": "📢 Spam / reklama",
    "duplicate": "♻️ Takroriy eʼlon",
    "offtopic": "🚫 Mavzuga mos emas",
    "incomplete": "📄 Maʼlumot yetarli emas",
    "other": "❔ Boshqa",
    "unknown": "❔ Nomaʼlum",
}

SYSTEM_PROMPT = (
    "Siz Mobile Legends: Bang Bang (MLBB) akkauntlarini sotish bo'yicha "
    "o'zbek tilidagi Telegram botning moderatorsiz. Sizga foydalanuvchi "
    "joylagan e'lon haqidagi ma'lumot va rasm(lar) beriladi. Vazifangiz: "
    "e'lonni TASDIQLASH, RAD ETISH yoki QO'LDA TEKSHIRISH uchun belgilash.\n\n"
    "RAD ETISH sabablari: firibgarlik belgilari (juda past narx + qimmat "
    "skinlar, «oldindan to'lov», shubhali aloqa, akkauntni qaytarib olish "
    "ishoralari), spam/reklama, ma'no va mazmunga aloqasi yo'q kontent, "
    "haqorat, takroriy e'lon.\n\n"
    "RASMLARNI HAM tekshir: rasm boshqa e'longa yoki begona shaxsga "
    "ishora qilmasin, akkaunt egasi bo'lib ko'rinsin, 'sotib olingan' deb "
    "yozilgan bo'lsa e'lon rad etiladi.\n\n"
    "FAQAT quyidagi JSON ko'rinishida javob bering, boshqa matn yozmang:\n"
    '{"decision": "approve|reject|review", "confidence": 0-100, '
    '"risk": "ok|scam|spam|duplicate|offtopic|incomplete|other", '
    '"reason": "o\'zbek tilida qisqa sabab (1-2 gap)"}'
)


class AIError(RuntimeError):
    """AI so'rovi bajarilmaganda ko'tariladi."""


@dataclass
class AIVerdict:
    """AI moderatsiya natijasi."""

    decision: str = REVIEW
    confidence: int = 0
    reason: str = ""
    risk: str = "unknown"
    model: str = ""
    raw: str = ""
    #: Tahlil qilindi, lekin rasm yuklab bo'lmadi
    photo_note: str = field(default="", repr=False)

    @property
    def approved(self) -> bool:
        return self.decision == APPROVE

    @property
    def rejected(self) -> bool:
        return self.decision == REJECT

    @property
    def label(self) -> str:
        return {
            APPROVE: "✅ TASDIQLASH tavsiya etiladi",
            REJECT: "⛔️️ RAD ETISH tavsiya etiladi",
            REVIEW: "🔍 QOʻLDA TEKSHIRISH kerak",
        }.get(self.decision, "🔍 QOʻLDA TEKSHIRISH kerak")

    def as_text(self) -> str:
        """Admin xabariga qo'shiladigan matn bloki."""
        lines = [
            "🤖 <b>AI tekshiruvi</b>",
            self.label,
            f"🎯 Isonch: <b>{self.confidence}%</b>",
            f"🏷 Turi: {RISK_LABELS.get(self.risk, RISK_LABELS['unknown'])}",
        ]
        if self.reason:
            lines.append(f"📝 Sabab: {self.reason}")
        if self.model:
            lines.append(f"⚙️ Model: <code>{self.model}</code>")
        if self.photo_note:
            lines.append(f"🖼 Rasmlar: {self.photo_note}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Sozlamalar
# ---------------------------------------------------------------------------
#: Google Gemini API manzili
GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"

#: Provayder bo'yicha standart modellar
DEFAULT_MODELS: dict[str, str] = {
    "openai": "gpt-4o-mini",
    "gemini": "gemini-3.8-flash",
}

PROVIDER_LABELS: dict[str, str] = {
    "openai": "OpenAI-mos (OpenRouter / OpenAI / Groq / …)",
    "gemini": "Google Gemini",
}

#: Bitta so'rovga biriktiriladigan rasm soni (kontekst va tezlik uchun)
MAX_PHOTOS = 3
#: Katta rasmni tashlab ketish chegarasi (bayt)
MAX_PHOTO_BYTES = 4 * 1024 * 1024

#: Kalit qaysi provayderga tegishli bo'lishini aniqlash uchun sinab
#: ko'riladigan odiiy OpenAI-mos manzillar. Kalit faqat shu ro'yxatdagi
#: manzillarga yuboriladi — boshqa hech qanday xizmatga emas.
KNOWN_ENDPOINTS: tuple[tuple[str, str], ...] = (
    ("https://openrouter.ai/api/v1", "OpenRouter"),
    ("https://api.openai.com/v1", "OpenAI"),
    ("https://api.groq.com/openai/v1", "Groq"),
    ("https://api.together.xyz/v1", "Together AI"),
    ("https://api.deepinfra.com/v1/openai", "DeepInfra"),
    ("https://api.mistral.ai/v1", "Mistral"),
)


def _api_key() -> str:
    return str(settings.get("AI_API_KEY") or "").strip()


def _configured_base() -> str:
    return str(settings.get("AI_BASE_URL") or "").strip().rstrip("/")


def _configured_model() -> str:
    return str(settings.get("AI_MODEL") or "").strip()


def provider() -> str:
    """Qaysi provayder ishlatilishi (`openai` yoki `gemini`).

    `auto` rejimda kalit va manzil ko'rinishidan aniqlanadi: `AIza...` bilan
    boshlanuvchi kalit yoki `generativelanguage.googleapis.com` manzili —
    Gemini, aks holda OpenAI-mos API.
    """
    explicit = str(settings.get("AI_PROVIDER") or "auto").strip().lower()
    if explicit in ("gemini", "google"):
        return "gemini"
    if explicit in ("openai", "openai_compatible", "openrouter", "groq", "auto"):
        if explicit != "auto":
            return "openai"
    if "generativelanguage.googleapis.com" in _configured_base():
        return "gemini"
    if _api_key().startswith("AIza"):
        return "gemini"
    return "openai"


def _model() -> str:
    """Joriy provayderga mos model nomi.

    OpenRouter modellari `provayder/model` ko'rinishida bo'ladi — bunday
    nom Gemini'da mavjud emas, shu sababli mos kelmasa standaultga qaytadi.
    """
    name = provider()
    raw = _configured_model()
    if not raw:
        return DEFAULT_MODELS[name]
    if name == "gemini" and "/" in raw and not raw.startswith("gemini"):
        return DEFAULT_MODELS["gemini"]
    if name == "openai" and raw.startswith("gemini"):
        return DEFAULT_MODELS["openai"]
    return raw


def _base_url() -> str:
    """So'rov yuboriladigan manzil (oxirgi `/` olib tashlangan)."""
    name = provider()
    base = _configured_base()
    if name == "gemini":
        # Gemini o'z manzilini boshqaradi — boshqa provayder manzili qo'yilgan
        # bo'lsa ham e'tiborsiz qoldiramiz.
        return GEMINI_BASE
    return base or "https://api.openai.com/v1"


def active_model() -> str:
    """Joriy sozlamalardan kelib chiqadigan model nomi (panellar uchun)."""
    return _model()


def active_base_url() -> str:
    """Joriy so'rov manzili (panellar uchun)."""
    return _base_url()


def _timeout() -> int:
    try:
        return int(settings.get("AI_TIMEOUT_SECONDS"))
    except (TypeError, ValueError):
        return 20


def is_enabled() -> bool:
    """AI moderatsiya yoqilganmi va kalit kiritilganmi?"""
    return settings.get_bool("AI_ENABLED") and bool(_api_key())


def config_summary() -> str:
    """Panelda ko'rsatiladigan qisqa holat."""
    if not settings.get_bool("AI_ENABLED"):
        return "⛔️ Oʻchirilgan"
    if not _api_key():
        return "⚠️ Kalit kiritilmagan"
    return (
        f"✅ Yoqilgan · {PROVIDER_LABELS[provider()]} · <code>{_model()}</code>"
    )


# ---------------------------------------------------------------------------
# Rasm tayyorlash (vision)
# ---------------------------------------------------------------------------
async def _photo_payload(bot: Any, listing: dict) -> tuple[list[tuple[str, str]], str]:
    """E'lon rasmlarini yuklab `(mime, base64)` juftliklarini qaytaradi.

    Rasm yuklanmasa ham moderatsiya davom etadi — faqat matn tahlil qilinadi,
    shuning uchun ogohlantirish matni ham qaytariladi.
    """
    photos = list(listing.get("photos") or [])[:MAX_PHOTOS]
    if not photos:
        return [], ""
    if bot is None:
        return [], "bot obyekti yo'q — faqat matn tahlil qilindi"

    prepared: list[tuple[str, str]] = []
    skipped = 0
    for file_id in photos:
        try:
            downloadable = await bot.download(file_id)
            data = await downloadable.read_bytes()
        except Exception as exc:  # noqa: BLE001 — rasm yuklanmasligi fatal emas
            logger.debug("Rasm yuklanmadi (%s): %s", file_id, exc)
            skipped += 1
            continue
        if not data:
            skipped += 1
            continue
        if len(data) > MAX_PHOTO_BYTES:
            skipped += 1
            continue
        mime = "image/jpeg"
        if data[:8] == b"\x89PNG\r\n\x1a\n":
            mime = "image/png"
        prepared.append((mime, base64.b64encode(data).decode("ascii")))

    notes = [f"{len(prepared)} ta rasm tahlil qilindi"]
    if skipped:
        notes.append(f"{skipped} ta yuklanmadi")
    return prepared, " · ".join(notes)


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
def _auth_error(status: int) -> AIError:
    """401/403 uchun aniq va foydali xabar."""
    name = provider()
    hint = PROVIDER_LABELS[name]
    if name == "gemini":
        extra = (
            "Kalit Google AI Studio'dan olingan bo'lishi kerak "
            "(aistudio.google.com/apikey), OpenRouter'dan emas."
        )
    else:
        extra = (
            f"Kiritilgan manzil: <code>{_base_url() or '—'}</code>. Kalit aynan shu "
            "provayderga tegishli bo'lishi kerak. «🤖 AI» → «📋 Modellarni "
            "koʻrish» orqali kalitingizga mavjud modellarni koʻring."
        )
    return AIError(f"Kalit qabul qilinmadi ({status}). {extra} [{hint}]")


async def _chat(text: str, images: list[tuple[str, str]]) -> str:
    """Matn va (ixtiyoriy) rasmlarni modelga yuborib, javob matnini qaytaradi."""
    key = _api_key()
    if not key:
        raise AIError("AI API kaliti kiritilmagan. «🤖 AI moderatsiya» boʻlimidan qoʻshing.")

    name = provider()
    url = f"{_base_url()}/models/{_model()}:generateContent?key={key}" if name == "gemini" else (
        f"{_base_url()}/chat/completions"
    )
    if name == "openai" and not _base_url():
        raise AIError("AI manzili (AI_BASE_URL) kiritilmagan.")

    if name == "gemini":
        headers = {"Content-Type": "application/json"}
        parts: list[dict[str, Any]] = [{"text": text}]
        parts.extend(
            {"inline_data": {"mime_type": mime, "data": payload}}
            for mime, payload in images
        )
        payload: dict[str, Any] = {
            "contents": [{"role": "user", "parts": parts}],
            "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
            "generationConfig": {"responseMimeType": "application/json"},
        }
    else:
        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "X-Title": "MLBB Market Bot",
        }
        content: Any = text
        if images:
            content = [{"type": "text", "text": text}] + [
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{payload}"},
                }
                for mime, payload in images
            ]
        payload = {
            "model": _model(),
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": content},
            ],
            "temperature": 0,
            "max_tokens": 500,
            "response_format": {"type": "json_object"},
        }

    timeout = aiohttp.ClientTimeout(total=_timeout())
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            for attempt in (1, 2):
                # Nusxa yuboriladi: `response_format` ni olib tashlash birinchi
                # urinishga tegmasligi kerak.
                async with session.post(url, json=dict(payload), headers=headers) as response:
                    body = await response.text()
                    if response.status == 400 and attempt == 1 and name == "openai":
                        # Ba'zi provayderlar `response_format` ni qo'llamaydi
                        payload.pop("response_format", None)
                        continue
                    if response.status in (401, 403):
                        raise _auth_error(response.status)
                    if response.status == 402:
                        raise AIError("AI hisobida mablagʻ yoʻq (402).")
                    if response.status == 404:
                        raise AIError(
                            f"Model topilmadi: <code>{_model()}</code>. "
                            "«📋 Modellarni koʻrish» tugmasi bilan mavjud "
                            "modellarni koʻring va toʻgʻrisini tanlang."
                        )
                    if response.status == 429:
                        raise AIError("Soʻrov chegarasi (429). Birozdan soʻng urinib koʻring.")
                    if response.status >= 400:
                        raise AIError(f"AI xatosi {response.status}: {body[:180]}")
                    break
            else:  # pragma: no cover — sikl har doim `break` bilan tugaydi
                raise AIError("AI javob bermadi.")
    except asyncio.TimeoutError as exc:
        # Python 3.11+ da asyncio.TimeoutError === TimeoutError
        raise AIError("AI javob bermadi (vaqt tugadi).") from exc
    except aiohttp.ClientError as exc:
        raise AIError(f"AI serverga ulanib boʻlmadi: {exc}") from exc

    return _extract_text(body, name)


def _extract_text(body: str, name: str) -> str:
    """Provayder javobidan matnni ajratib oladi."""
    try:
        data = json.loads(body)
    except ValueError as exc:
        raise AIError("AI javobi tahlil qilinmadi.") from exc
    try:
        if name == "gemini":
            return str(data["candidates"][0]["content"]["parts"][0]["text"] or "")
        return str(data["choices"][0]["message"]["content"] or "")
    except (KeyError, IndexError, TypeError) as exc:
        raise AIError("AI javobi kutilgan koʻrinishda emas.") from exc


# ---------------------------------------------------------------------------
# Modellar ro'yxati
# ---------------------------------------------------------------------------
async def list_models() -> list[str]:
    """Kalit ishlatadigan provayderda mavjud modellarni qaytaradi.

    Kalit noto'g'ri bo'lsa foydalanuvchi shu yerda darhol bilsin.
    """
    key = _api_key()
    if not key:
        raise AIError("AI API kaliti kiritilmagan.")

    name = provider()
    if name == "gemini":
        url = f"{GEMINI_BASE}/models?key={key}"
        headers: dict[str, str] = {}
    else:
        url = f"{_base_url()}/models"
        headers = {"Authorization": f"Bearer {key}"}

    timeout = aiohttp.ClientTimeout(total=_timeout())
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers=headers) as response:
                body = await response.text()
                if response.status in (401, 403):
                    raise _auth_error(response.status)
                if response.status >= 400:
                    raise AIError(f"Modellarni olib boʻlmadi ({response.status}): {body[:180]}")
    except asyncio.TimeoutError as exc:
        raise AIError("Modellar roʻyxatini olishda vaqt tugadi.") from exc
    except aiohttp.ClientError as exc:
        raise AIError(f"AI serverga ulanib boʻlmadi: {exc}") from exc

    try:
        data = json.loads(body)
    except ValueError as exc:
        raise AIError("Modallar javobi tahlil qilinmadi.") from exc

    if name == "gemini":
        models = [
            str(item.get("name") or "").removeprefix("models/")
            for item in data.get("models") or []
        ]
    else:
        models = [str(item.get("id") or "") for item in data.get("data") or []]

    cleaned = sorted({m for m in models if m})
    if not cleaned:
        raise AIError("Provayder modellar roʻyxatini qaytarmadi.")
    return cleaned


# ---------------------------------------------------------------------------
# Tahlil
# ---------------------------------------------------------------------------
def _extract_json(text: str) -> Optional[dict]:
    """Matndan birinchi JSON obyektini ajratib oladi."""
    if not text:
        return None
    start = text.find("{")
    end = text.rfind("}")
    candidates = []
    if start != -1 and end > start:
        candidates.append(text[start:end + 1])
    candidates.append(text)
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def parse_verdict(text: str, model: str = "", photo_note: str = "") -> AIVerdict:
    """Model javobini :class:`AIVerdict` ga aylantiradi."""
    data = _extract_json(text)
    if data is None:
        return AIVerdict(
            decision=REVIEW,
            confidence=0,
            reason="AI javobini tushunib boʻlmadi, qoʻlda tekshiring.",
            risk="other",
            model=model,
            raw=text[:400],
            photo_note=photo_note,
        )

    decision_raw = str(data.get("decision") or data.get("qaror") or "").strip().lower()
    decision = _DECISION_ALIASES.get(decision_raw, REVIEW)
    try:
        confidence = int(float(data.get("confidence", data.get("ishonch", 0))))
    except (TypeError, ValueError):
        confidence = 0
    confidence = max(0, min(100, confidence))
    risk = str(data.get("risk") or data.get("risk_type") or "unknown").strip().lower()
    if risk not in RISK_LABELS:
        risk = "other" if risk else "unknown"
    reason = str(data.get("reason") or data.get("sabab") or "").strip()
    reason = re.sub(r"\s+", " ", reason)[:280]

    return AIVerdict(
        decision=decision,
        confidence=confidence,
        reason=reason,
        risk=risk,
        model=model,
        raw=text[:400],
        photo_note=photo_note,
    )


def _extra_rules() -> str:
    rules = str(settings.get("AI_EXTRA_RULES") or "").strip()
    if not rules:
        return ""
    return "\n\nQO'SHIMCHA QOIDALAR (albatta rioya qiling):\n" + rules


def _listing_brief(listing: dict) -> str:
    """E'lon ma'lumotlari AI uchun ixcham matnga aylantiriladi."""
    kind = {
        "buy": "XARIDOR SO'ROVI (foydalanuvchi akkaunt sotib olmoqchi)",
        "sell": "SOTUVCHI E'LONI",
    }.get(str(listing.get("listing_type") or "sell"), "E'LON")
    mode = "ALMASHISH (barter)" if str(listing.get("listing_mode")) == "trade" else "SOTISH"
    fields = [
        f"Turi: {kind}",
        f"Rejim: {mode}",
        f"Rank: {listing.get('rank_info') or '—'}",
        f"Skinlar/qahramonlar: {listing.get('skins_info') or '—'}",
        f"Narx: {listing.get('price_display') or listing.get('price_numeric') or 'kelishilgan'}",
        f"VIP: {'ha' if listing.get('is_vip') else 'yoʻq'}",
        f"Mos keladigan eʼlon raqami: #{listing.get('id')}",
    ]
    if listing.get("trade_wanted"):
        fields.append(f"Almashish talabi: {listing['trade_wanted']}")
    if listing.get("description"):
        fields.append(f"Izoh: {listing['description']}")
    if listing.get("contact"):
        fields.append(f"Aloqa: {listing['contact']}")
    fields.append(f"Rasm soni: {len(listing.get('photos') or [])}")
    return "\n".join(fields)


# ---------------------------------------------------------------------------
# Asosiy funksiyalar
# ---------------------------------------------------------------------------
async def moderate_listing(listing: dict, bot: Any = None) -> AIVerdict:
    """E'lonni AI orqali tekshiradi (matn + rasmlar).

    :raises AIError: sozlama to'liq bo'lmasa yoki so'rov bajarilmasa.
    """
    if not settings.get_bool("AI_ENABLED"):
        raise AIError("AI moderatsiya oʻchirilgan.")

    images, photo_note = await _photo_payload(bot, listing)
    brief = _listing_brief(listing)
    if images:
        brief += f"\nRasm: e'londa {len(images)} ta rasm bor, ularni ham tekshir."
    text = brief + _extra_rules()

    raw = await _chat(text, images)
    verdict = parse_verdict(raw, model=_model(), photo_note=photo_note)
    logger.info(
        "AI moderatsiya (#%s): %s (%s%%, %s)",
        listing.get("id"),
        verdict.decision,
        verdict.confidence,
        verdict.risk,
    )
    return verdict


async def test_connection() -> str:
    """Ulanish va kalitni tekshiradi. Muvaffaqiyatda model javobini qaytaradi."""
    raw = await _chat("Faqat qisqa JSON qaytar: {\"ok\": true, \"lang\": \"uz\"}", [])
    data = _extract_json(raw)
    if data is None:
        raise AIError(f"Javob JSON emas: {raw[:120]}")
    return raw.strip()[:200]


def should_auto_approve(verdict: AIVerdict) -> bool:
    """AI javobiga asosida e'lonni avtomatik tasdiqlash kerakmi?"""
    if not verdict.approved:
        return False
    if not settings.get_bool("AI_AUTO_APPROVE"):
        return False
    try:
        threshold = int(settings.get("AI_MIN_CONFIDENCE"))
    except (TypeError, ValueError):
        threshold = 70
    return verdict.confidence >= threshold


def should_auto_reject(verdict: AIVerdict) -> bool:
    """AI javobiga asosida e'lonni avtomatik rad etish kerakmi?"""
    if not verdict.rejected:
        return False
    if not settings.get_bool("AI_REJECT_SCAMS"):
        return False
    if verdict.risk not in ("scam", "spam", "offtopic"):
        return False
    try:
        threshold = int(settings.get("AI_MIN_CONFIDENCE"))
    except (TypeError, ValueError):
        threshold = 70
    return verdict.confidence >= threshold


async def probe_endpoints() -> list[tuple[str, str, str]]:
    """Kalit qaysi provayderda ishlashini aniqlaydi.

    Ro'yxatdagi manzillarning `/models` ga yengil so'rov yuboriladi — bu
    generatsiya qilmaydi, faqat kalit qabul qilinadimi tekshiradi.

    :return: `(base_url, nomi, natija)` uchliklari; `natija` `✅` yoki `❌ sabab`.
    """
    key = _api_key()
    if not key:
        raise AIError("AI API kaliti kiritilmagan.")

    timeout = aiohttp.ClientTimeout(total=8)
    results: list[tuple[str, str, str]] = []
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            for base, name in KNOWN_ENDPOINTS:
                try:
                    async with session.get(
                        f"{base}/models", headers={"Authorization": f"Bearer {key}"}
                    ) as response:
                        if response.status in (200, 201):
                            results.append((base, name, "✅ ishlaydi"))
                        elif response.status in (401, 403):
                            results.append((base, name, "❌ kalit mos kelmadi"))
                        elif response.status == 429:
                            results.append((base, name, "⚠️ chegara tugagan"))
                        else:
                            results.append((base, name, f"❌ {response.status}"))
                except asyncio.TimeoutError:
                    results.append((base, name, "❌ javob bermadi"))
                except aiohttp.ClientError as exc:
                    results.append((base, name, f"❌ {type(exc).__name__}"))
    except aiohttp.ClientError as exc:
        raise AIError(f"AI serverga ulanib boʻlmadi: {exc}") from exc

    return results


__all__ = [
    "AIError",
    "AIVerdict",
    "APPROVE",
    "GEMINI_BASE",
    "KNOWN_ENDPOINTS",
    "REJECT",
    "REVIEW",
    "RISK_LABELS",
    "active_base_url",
    "active_model",
    "config_summary",
    "DEFAULT_MODELS",
    "PROVIDER_LABELS",
    "is_enabled",
    "list_models",
    "moderate_listing",
    "parse_verdict",
    "probe_endpoints",
    "provider",
    "should_auto_approve",
    "should_auto_reject",
    "test_connection",
]
