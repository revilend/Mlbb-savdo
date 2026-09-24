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
    "my_listings",
    "offers",
    "scam_check",
    "search",
    "sell",
]
