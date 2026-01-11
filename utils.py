# utils.py
from typing import Dict, Any, List

from aiogram import Bot

from config import ADMIN_ID
from data import load_data, find_product


# ===================== ROLES =====================

def is_admin(uid: int) -> bool:
    return uid == ADMIN_ID


def is_manager(data: Dict[str, Any], uid: int) -> bool:
    return uid in data.get("managers", []) or is_admin(uid)


# ===================== SAFE SEND =====================

async def safe_send(bot: Bot, chat_id: int, text: str, **kwargs):
    """
    Безопасная отправка сообщения (не падает, если пользователь недоступен)
    """
    try:
        await bot.send_message(chat_id, text, **kwargs)
    except Exception:
        pass


# ===================== NOTIFY MANAGERS =====================

async def notify_managers(bot: Bot, text: str):
    """
    Отправка сообщения всем менеджерам и админу
    """
    data = load_data()
    recipients = set(data.get("managers", []))
    recipients.add(ADMIN_ID)

    for uid in recipients:
        await safe_send(bot, uid, text)


# ===================== FORMAT ORDER =====================

def format_order_text(data: Dict[str, Any], order: Dict[str, Any]) -> str:
    """
    Красивое текстовое представление заказа
    """
    lines: List[str] = []

    for pid in order.get("items", []):
        product = find_product(data, pid)
        if product:
            lines.append(f"• {product['name']} — {product['price']} ₴")
        else:
            lines.append(f"• Товар #{pid} (не знайдено)")

    status = order.get("status", "new")
    total = order.get("total", 0)

    return (
        f"🧾 Замовлення #{order['id']}\n"
        f"👤 User ID: {order.get('user_id')}\n"
        f"📌 Статус: {status}\n\n"
        f"🛒 Склад:\n" + "\n".join(lines) +
        f"\n\n💰 Разом: {total:.2f} ₴"
    )