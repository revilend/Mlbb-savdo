"""AI moderatsiya mijozi.

Bot **OpenAI-mos** `chat/completions` API'si bilan ishlaydi, shuning uchun
bitta kalit bilan OpenRouter, OpenAI, Groq, DeepInfra, Together, Mistral yoki
o'z serveringizdan foydalanish mumkin. Manzil (`AI_BASE_URL`), model
(`AI_MODEL`) va kalit (`AI_API_KEY`) — hammasi bot ichidagi paneldan
o'zgartiriladi.

Moderatsiya **matn** asosida ishlaydi (rank, skinlar, narx, izoh, aloqa) va
`approve` / `reject` / `review` qarorini ishonch darajasi bilan qaytaradi.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
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
    "block": REJECT,
    "blocked": REJECT,
    "deny": REJECT,
    "rad": REJECT,
    "scam": REJECT,
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
    "joylagan e'lon haqidagi ma'lumot beriladi. Vazifangiz: e'lonni "
    "TASDIQLASH, RAD ETISH yoki QO'LDA TEKSHIRISH uchun belgilash.\n\n"
    "RAD ETISH sabablari: firibgarlik belgilari (juda past narx + qimmat "
    "skinlar, «oldindan to'lov», shubhali aloqa, akkauntni qaytarib olish "
    "ishoralari), spam/reklama, mavzuga aloqasi yo'q kontent, haqorat, "
    "takroriy e'lon, bo'sh yoki ma'nosiz ma'lumot.\n"
    "TASDIQLASH: oddiy, tushunarli va qoidalarga mos e'lon.\n"
    "QO'LDA TEKSHIRISH: shubha bor, lekin aniq qoidabuzarlik yo'q.\n\n"
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
            REJECT: "⛔️ RAD ETISH tavsiya etiladi",
            REVIEW: "🔍 QOʻLDA TEKSHIRISH kerak",
        }.get(self.decision, "🔍 QOʻLDA TEKSHIRISH kerak")

    def as_text(self) -> str:
        """Admin xabariga qo'shiladigan matn bloki."""
        lines = [
            "🤖 <b>AI tekshiruvi</b>",
            self.label,
            f"🎯 Ishonch: <b>{self.confidence}%</b>",
            f"🏷 Turi: {RISK_LABELS.get(self.risk, RISK_LABELS['unknown'])}",
        ]
        if self.reason:
            lines.append(f"📝 Sabab: {self.reason}")
        if self.model:
            lines.append(f"⚙️ Model: <code>{self.model}</code>")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Sozlamalar
# ---------------------------------------------------------------------------
def _api_key() -> str:
    return str(settings.get("AI_API_KEY") or "").strip()


def _base_url() -> str:
    return str(settings.get("AI_BASE_URL") or "").strip().rstrip("/")


def _model() -> str:
    return str(settings.get("AI_MODEL") or "").strip()


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
    return f"✅ Yoqilgan · <code>{_model()}</code>"


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
async def _chat(messages: list[dict[str, str]], *, json_mode: bool = True) -> str:
    """OpenAI-mos `chat/completions` so'rovini yuboradi va matnni qaytaradi."""
    api_key = _api_key()
    if not api_key:
        raise AIError("AI API kaliti kiritilmagan. «🤖 AI moderatsiya» boʻlimidan qoʻshing.")

    url = f"{_base_url()}/chat/completions"
    payload: dict[str, Any] = {
        "model": _model(),
        "messages": messages,
        "temperature": 0,
        "max_tokens": 400,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "X-Title": "MLBB Market Bot",
    }

    timeout = aiohttp.ClientTimeout(total=_timeout())
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            for attempt in (1, 2):
                async with session.post(url, json=dict(payload), headers=headers) as response:
                    body = await response.text()
                    if response.status == 400 and attempt == 1 and json_mode:
                        # Ba'zi provayderlar `response_format` ni qo'llamaydi
                        payload.pop("response_format", None)
                        continue
                    if response.status == 401:
                        raise AIError("Kalit notoʻgʻri (401). Kalitni tekshiring.")
                    if response.status == 402:
                        raise AIError("AI hisobida mablagʻ yoʻq (402).")
                    if response.status == 429:
                        raise AIError("Soʻrovlar chegarasi (429). Birozdan soʻng urinib koʻring.")
                    if response.status >= 400:
                        raise AIError(
                            f"AI xatosi {response.status}: {body[:180]}"
                        )
                    break
    except asyncio.TimeoutError as exc:
        # Python 3.11+ da asyncio.TimeoutError === TimeoutError
        raise AIError("AI javob bermadi (vaqt tugadi).") from exc
    except aiohttp.ClientError as exc:
        raise AIError(f"AI serverga ulanib boʻlmadi: {exc}") from exc

    try:
        data = json.loads(body)
    except ValueError as exc:
        raise AIError("AI javobi tahlil qilinmadi.") from exc

    try:
        return str(data["choices"][0]["message"]["content"] or "")
    except (KeyError, IndexError, TypeError) as exc:
        raise AIError("AI javobi kutilgan koʻrinishda emas.") from exc


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


def parse_verdict(text: str, model: str = "") -> AIVerdict:
    """AI javobini :class:`AIVerdict` ga aylantiradi."""
    data = _extract_json(text)
    if not data:
        return AIVerdict(
            decision=REVIEW,
            confidence=0,
            reason="AI javobini tushunib boʻlmadi, qoʻlda tekshiring.",
            risk="unknown",
            model=model,
            raw=text[:400],
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
    )


def _extra_rules() -> str:
    rules = str(settings.get("AI_EXTRA_RULES") or "").strip()
    if not rules:
        return ""
    return f"\n\nQO'SHIMCHA QOIDALAR (albatta rioya qiling):\n{rules}"


def _listing_brief(listing: dict) -> str:
    """E'lon ma'lumotlarini AI uchun ixcham matnga aylantiradi."""
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
    fields.append(f"Rasmlar soni: {len(listing.get('photos') or [])}")
    return "\n".join(fields)


# ---------------------------------------------------------------------------
# Asosiy funksiyalar
# ---------------------------------------------------------------------------
async def moderate_listing(listing: dict) -> AIVerdict:
    """E'lonni AI orqali tekshiradi.

    :raises AIError: sozlama to'liq bo'lmasa yoki so'rov bajarilmasa.
    """
    if not settings.get_bool("AI_ENABLED"):
        raise AIError("AI moderatsiya oʻchirilgan.")
    model = _model()
    content = _listing_brief(listing) + _extra_rules()

    raw = await _chat(
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": content},
        ]
    )
    verdict = parse_verdict(raw, model=model)
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
    raw = await _chat(
        [
            {"role": "system", "content": "You reply only with compact JSON."},
            {
                "role": "user",
                "content": 'Return exactly this JSON: {"ok": true, "lang": "uz"}',
            },
        ]
    )
    data = _extract_json(raw)
    if data is None:
        raise AIError(f"Javob JSON emas: {raw[:120]}")
    return raw.strip()[:200]


def should_auto_approve(verdict: AIVerdict) -> bool:
    """AI natijasi asosida e'lonni avtomatik tasdiqlash kerakmi?"""
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
    """AI natijasi asosida e'lonni avtomatik rad etish kerakmi?"""
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


__all__ = [
    "AIError",
    "AIVerdict",
    "APPROVE",
    "REJECT",
    "REVIEW",
    "RISK_LABELS",
    "config_summary",
    "is_enabled",
    "moderate_listing",
    "parse_verdict",
    "should_auto_approve",
    "should_auto_reject",
    "test_connection",
]
