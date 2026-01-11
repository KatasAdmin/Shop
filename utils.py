# utils.py
from typing import Dict, Any, List

from aiogram import Bot

from config import ADMIN_ID
from data import load_data, find_product

# преміум форматування (файл text.py лежить у корені)
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

async def notify_staff(bot: Bot, text: str):
    """
    Відправка повідомлення всім менеджерам і адміну
    """
    data = load_data()
    recipients = set(data.get("managers", []))
    recipients.add(ADMIN_ID)

    for uid in recipients:
        await safe_send(bot, uid, text)


# ===================== ORDER FORMATTING =====================

def format_order_text(data: Dict[str, Any], order: Dict[str, Any]) -> str:
    """
    Преміум-текст замовлення для менеджера/адміна.
    Повертає HTML-рядок -> при відправці став parse_mode="HTML"
    """
    items: List[Dict[str, Any]] = []
    for pid in order.get("items", []):
        p = find_product(data, pid)
        if p:
            items.append(p)

    # order_premium_text(order, items) — якщо твоя функція саме така.
    # Якщо в text.py вона називається order_card(...) — скажи, підлаштую.
    return order_premium_text(order, items)