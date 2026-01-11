# utils.py
from typing import Dict, Any, List

from aiogram import Bot

from config import ADMIN_ID
from data import load_data, find_product


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
    Гарний текст замовлення для менеджера/адміна
    (з товарами + доставкою)
    """
    lines: List[str] = []

    for pid in order.get("items", []):
        product = find_product(data, pid)
        if product:
            lines.append(f"• {product['name']} — {product['price']} ₴")
        else:
            lines.append(f"• Товар #{pid} (не знайдено)")

    status = order.get("status", "new")
    total = float(order.get("total", 0))

    delivery = order.get("delivery", {}) or {}
    cname = delivery.get("name", "")
    phone = delivery.get("phone", "")
    city = delivery.get("city", "")
    np_branch = delivery.get("np_branch", "")
    comment = delivery.get("comment", "")

    delivery_block = []
    if cname:
        delivery_block.append(f"👤 Імʼя: {cname}")
    if phone:
        delivery_block.append(f"📞 Телефон: {phone}")
    if city:
        delivery_block.append(f"🏙 Місто: {city}")
    if np_branch:
        delivery_block.append(f"📦 НП: {np_branch}")
    if comment:
        delivery_block.append(f"📝 Коментар: {comment}")

    if not delivery_block:
        delivery_text = "—"
    else:
        delivery_text = "\n".join(delivery_block)

    return (
        f"🧾 Замовлення #{order.get('id')}\n"
        f"👤 User ID: {order.get('user_id')}\n"
        f"📌 Статус: {status}\n\n"
        f"🛒 Склад:\n" + "\n".join(lines) +
        f"\n\n💰 Разом: {total:.2f} ₴\n\n"
        f"🚚 Доставка:\n{delivery_text}"
    )