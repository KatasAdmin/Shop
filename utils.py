from typing import Dict, Any, List, Optional

from aiogram import Bot
from aiogram.types import InputMediaPhoto

from config import ADMIN_ID
from data import load_data, find_product


# ===================== ROLES =====================

def is_admin(uid: int) -> bool:
    return uid == ADMIN_ID


def is_manager(data: Dict[str, Any], uid: int) -> bool:
    return uid in data.get("managers", []) or is_admin(uid)


# ===================== SAFE SEND =====================

async def safe_send(bot: Bot, chat_id: int, text: str, **kwargs):
    try:
        await bot.send_message(chat_id, text, **kwargs)
    except Exception:
        pass


async def safe_send_photo(bot: Bot, chat_id: int, photo: str, **kwargs):
    try:
        await bot.send_photo(chat_id, photo, **kwargs)
    except Exception:
        pass


async def safe_send_media_group(bot: Bot, chat_id: int, media: List[InputMediaPhoto]):
    try:
        await bot.send_media_group(chat_id, media)
    except Exception:
        # если альбом не отправился — не падаем
        pass


# ===================== NOTIFY MANAGERS =====================

def get_recipients() -> List[int]:
    data = load_data()
    recipients = set(data.get("managers", []))
    recipients.add(ADMIN_ID)
    return list(recipients)


async def notify_managers_text(bot: Bot, text: str):
    for uid in get_recipients():
        await safe_send(bot, uid, text)


async def notify_managers_order(bot: Bot, data: Dict[str, Any], order: Dict[str, Any]):
    """
    Отправляет менеджерам:
    1) полный текст заказа
    2) фото товаров (первые фото каждого товара, если есть)
    """
    text = "💰 ОПЛАЧЕНО!\n\n" + format_order_text(data, order)

    recipients = get_recipients()
    for uid in recipients:
        await safe_send(bot, uid, text)

        # Фото товаров: сначала пробуем альбомом (если несколько)
        photos: List[InputMediaPhoto] = []
        for pid in order.get("items", []):
            p = find_product(data, pid)
            if not p:
                continue
            imgs = p.get("photos", []) or []
            if imgs:
                photos.append(InputMediaPhoto(media=imgs[0], caption=p.get("name", "")))

        # если есть 2+ — шлем альбомом, если 1 — просто фото
        if len(photos) >= 2:
            await safe_send_media_group(bot, uid, photos[:10])  # Telegram лимит 10 в альбоме
        elif len(photos) == 1:
            await safe_send_photo(bot, uid, photos[0].media, caption=photos[0].caption)


# ===================== FORMAT ORDER =====================

def format_order_text(data: Dict[str, Any], order: Dict[str, Any]) -> str:
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
    city = order.get("city", "—")
    delivery_method = order.get("delivery_method", "—")
    delivery_point = order.get("delivery_point", "—")
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
        f"• Місто: {city}\n"
        f"• Спосіб: {delivery_method}\n"
        f"• Куди: {delivery_point}\n"
    )

    if comment:
        text += f"• Коментар: {comment}\n"

    text += (
        f"\n🛒 Товари:\n" + "\n".join(detailed_lines) +
        f"\n\n💰 Разом: {total:.2f} ₴"
    )
    return text