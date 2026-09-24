"""FSM holatlari (aiogram 3 StatesGroup)."""

from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class SellFSM(StatesGroup):
    """Akkaunt sotish anketasi."""

    rank = State()
    skins = State()
    price = State()
    is_vip = State()
    contact = State()
    description = State()
    photos = State()


class SearchFSM(StatesGroup):
    """Xaridor so'rovi (sotib olish / almashtirish) anketasi."""

    search_type = State()
    requirements = State()
    budget = State()
    contact = State()


class OfferFSM(StatesGroup):
    """Sotuvchiga narx taklif qilish."""

    waiting_amount = State()


class CalcFSM(StatesGroup):
    """Akkaunt narxini hisoblash."""

    rank = State()
    collector_count = State()
    legend_count = State()
    epic_count = State()


class ScamCheckFSM(StatesGroup):
    """Firibgarni tekshirish."""

    waiting_query = State()


class AdminFSM(StatesGroup):
    """Administrator amallari."""

    broadcast_content = State()
    set_channel_input = State()
    lookup_user_id = State()
    send_direct_msg_text = State()
    ban_identifier = State()
    ban_reason = State()
