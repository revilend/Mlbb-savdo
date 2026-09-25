"""Bot handlerlari (routerlar to'plami).

Har bir modul o'zining `router` obyektini eksport qiladi va ular
`main.build_dispatcher()` ichida Dispatcher'ga ulanadi.
"""

from __future__ import annotations

__all__ = [
    "admin",
    "calculator",
    "catalog",
    "common",
    "favorites",
    "garant",
    "inbox",
    "moderation",
    "my_listings",
    "offers",
    "reviews",
    "scam_check",
    "search",
    "sell",
    "settings_panel",
    "subscriptions",
]
