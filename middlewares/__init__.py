"""Middleware'lar to'plami.

* :class:`AntiFloodMiddleware` — spamga qarshi cheklov.
* :class:`SelfDestructMiddleware` — o'z-o'zini o'chiruvchi xabarlar.
* :class:`LatestMenuMiddleware` — menyu javobidan oldingi xabarlarni tozalash.
* :func:`temporary` / :func:`permanent` — handler ichida TTL boshqaruvi.
* :data:`messages` — chat bo'yicha xabar tarixi (`/clean` uchun).
"""

from __future__ import annotations

from middlewares.anti_flood import AntiFloodMiddleware, build_anti_flood
from middlewares.self_destruct import (
    MessageRegistry,
    LatestMenuMiddleware,
    SelfDestructMiddleware,
    UserMessageCleanerMiddleware,
    cleanup_registry,
    delete_later,
    delete_silently,
    messages,
    permanent,
    replace_previous,
    sweep_chat,
    temporary,
)

__all__ = [
    "AntiFloodMiddleware",
    "MessageRegistry",
    "LatestMenuMiddleware",
    "SelfDestructMiddleware",
    "UserMessageCleanerMiddleware",
    "build_anti_flood",
    "cleanup_registry",
    "delete_later",
    "delete_silently",
    "messages",
    "permanent",
    "replace_previous",
    "sweep_chat",
    "temporary",
]
