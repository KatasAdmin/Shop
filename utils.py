# utils.py
from typing import Dict, Any, List, Optional

from aiogram import Bot

from config import ADMIN_ID
from data import load_data, find_product

from text import order_premium_text


# ===================== ROLES =====================

def is_admin(uid: int) -> bool:
    return uid == ADMIN_ID


def is_staff(data: Dict[str, Any], uid: int) -> bool:
    # staff = admin + managers
    return uid in data.get("managers", []) or is_admin(uid)


# ===================== SAFE SEND =====================

async def safe_send(bot: Bot, chat_id: int, text: str, **kwargs):
    """
    Безпечна відправка повідомлення (не падає, якщо чат недоступний)
    """
    try:
        await bot.send_message(chat_id, text, **kwargs)
    except Exception:
        pass


# ===================== NOTIFY STAFF =====================

async def notify_staff(bot: Bot, text: str, **kwargs):
    """
    Відправка повідомлення всім менеджерам і адміну.
    Підтримує parse_mode та інші kwargs.
    """
    data = load_data()
    recipients = set(int(x) for x in data.get("managers", []) if str(x).isdigit())
    recipients.add(int(ADMIN_ID))

    for uid in recipients:
        await safe_send(bot, uid, text, **kwargs)


# ===================== ORDER FORMATTING =====================

def format_order_text(data: Dict[str, Any], order: Dict[str, Any]) -> str:
    """
    Преміум-текст замовлення для менеджера/адміна (HTML).
    """
    items: List[Dict[str, Any]] = []
    for pid in order.get("items", []):
        try:
            pid_int = int(pid)
        except Exception:
            continue
        p = find_product(data, pid_int)
        if p:
            items.append(p)

    # ✅ Правильна сигнатура з text.py: (data, order, products)
    return order_premium_text(data, order, items)