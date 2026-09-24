"""Middleware'lar to'plami.

* :class:`AntiFloodMiddleware` — spamga qarshi cheklov.
* :class:`SelfDestructMiddleware` — o'z-o'zini o'chiruvchi xabarlar.
* :func:`temporary` / :func:`permanent` — handler ichida TTL boshqaruvi.
* :data:`messages` — chat bo'yicha xabar tarixi (`/clean` uchun).
"""

from __future__ import annotations

from middlewares.anti_flood import AntiFloodMiddleware, build_anti_flood
from middlewares.self_destruct import (
    MessageRegistry,
    SelfDestructMiddleware,
    UserMessageCleanerMiddleware,
    cleanup_registry,
    delete_later,
    delete_silently,
    messages,
    permanent,
    sweep_chat,
    temporary,
)

__all__ = [
    "AntiFloodMiddleware",
    "MessageRegistry",
    "SelfDestructMiddleware",
    "UserMessageCleanerMiddleware",
    "build_anti_flood",
    "cleanup_registry",
    "delete_later",
    "delete_silently",
    "messages",
    "permanent",
    "sweep_chat",
    "temporary",
]
