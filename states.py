"""FSM holatlari (aiogram 3 StatesGroup)."""

from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class SellFSM(StatesGroup):
    """Akkaunt sotish yoki almashtirish (barter) anketasi."""

    mode = State()          # '💰 Sotish' yoki '🔄 Almashish'
    rank = State()
    skins = State()
    price = State()         # faqat 'sell' rejimida
    trade_wanted = State()  # faqat 'trade' rejimida
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
    """Sotuvchiga narx taklif qilish va javob yozish."""

    waiting_amount = State()
    waiting_reply = State()


class PriceDropFSM(StatesGroup):
    """E'lon narxini tushirish (chegirma)."""

    waiting_new_price = State()


class EditFSM(StatesGroup):
    """E'lonni tahrirlash (narx, izoh, aloqa)."""

    waiting_price = State()
    waiting_description = State()
    waiting_contact = State()


class ReviewFSM(StatesGroup):
    """Sotuvchi haqida sharh qoldirish."""

    rating = State()
    comment = State()


class SavedSearchFSM(StatesGroup):
    """Saqlangan qidiruv (obuna) yaratish."""

    waiting_keyword = State()


class SettingsFSM(StatesGroup):
    """Bot sozlamalarini bot ichidan tahrirlash."""

    waiting_value = State()


class AppraisalFSM(StatesGroup):
    """Akkaunt skrinshotlarini yig'ib admin baholashga yuborish."""

    photos = State()


class ScamCheckFSM(StatesGroup):
    """Firibgarni tekshirish."""

    waiting_query = State()


class AdminFSM(StatesGroup):
    """Administrator amallari."""

    broadcast_content = State()
    set_channel_input = State()   # e'lon kanali yoki majburiy kanal (data orqali)
    add_admin_id = State()
    remove_admin_id = State()
    lookup_user_id = State()
    send_direct_msg_text = State()
    ban_identifier = State()
    ban_reason = State()
    restore_waiting_document = State()
    restore_waiting_confirm = State()
    waiting_eval_price = State()  # target_user_id admin bahosi uchun
