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
    Красивое текстовое представление заказа + данные доставки + товары (с описанием)
    """
    detailed_lines: List[str] = []

    for pid in order.get("items", []):
        product = find_product(data, pid)
        if product:
            name = product.get("name", f"Товар #{pid}")
            price = float(product.get("price", 0))
            desc = (product.get("description") or "").strip()

            if desc:
                detailed_lines.append(f"• {name} — {price:.2f} ₴\n   └ {desc}")
            else:
                detailed_lines.append(f"• {name} — {price:.2f} ₴")
        else:
            detailed_lines.append(f"• Товар #{pid} (не знайдено)")

    status = order.get("status", "new")
    total = float(order.get("total", 0))

    customer_name = order.get("customer_name", "—")
    phone = order.get("phone", "—")
    address = order.get("address", "—")
    comment = (order.get("comment") or "").strip()

    username = (order.get("username") or "").strip()
    user_id = order.get("user_id", "—")

    user_line = f"{user_id}"
    if username:
        user_line = f"@{username} (ID: {user_id})"

    text = (
        f"🧾 Замовлення #{order.get('id', '—')}\n"
        f"👤 Клієнт: {user_line}\n"
        f"📌 Статус: {status}\n\n"
        f"📦 Дані доставки:\n"
        f"• Ім'я: {customer_name}\n"
        f"• Телефон: {phone}\n"
        f"• Адреса: {address}\n"
    )

    if comment:
        text += f"• Коментар: {comment}\n"

    text += (
        f"\n🛒 Товари:\n" + "\n".join(detailed_lines) +
        f"\n\n💰 Разом: {total:.2f} ₴"
    )
    return text