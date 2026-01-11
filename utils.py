from typing import Dict, Any, List
from aiogram import Bot
from aiogram.types import InputMediaPhoto

from config import ADMIN_ID
from data import load_data, find_product


def is_admin(uid: int) -> bool:
    return uid == ADMIN_ID


def is_manager(data: Dict[str, Any], uid: int) -> bool:
    return uid in data.get("managers", []) or is_admin(uid)


def is_staff(data: Dict[str, Any], uid: int) -> bool:
    return is_admin(uid) or uid in data.get("managers", [])


async def safe_send(bot: Bot, chat_id: int, text: str, **kwargs):
    try:
        await bot.send_message(chat_id, text, **kwargs)
    except Exception:
        pass


async def notify_managers_order(bot: Bot, data: Dict[str, Any], order: Dict[str, Any]):
    recipients = set(data.get("managers", []))
    recipients.add(ADMIN_ID)

    text = format_order_text(data, order)

    for uid in recipients:
        await safe_send(bot, uid, "💰 ОПЛАЧЕНО\n\n" + text)

        media = []
        for pid in order.get("items", []):
            p = find_product(data, pid)
            if p and p.get("photos"):
                media.append(InputMediaPhoto(media=p["photos"][0], caption=p["name"]))

        if media:
            try:
                await bot.send_media_group(uid, media[:10])
            except Exception:
                pass


def format_order_text(data: Dict[str, Any], order: Dict[str, Any]) -> str:
    lines = []
    for pid in order.get("items", []):
        p = find_product(data, pid)
        if p:
            lines.append(f"• {p['name']} — {p['price']} ₴")
        else:
            lines.append(f"• Товар #{pid}")

    return (
        f"🧾 Замовлення #{order['id']}\n"
        f"👤 {order.get('customer_name')}\n"
        f"📞 {order.get('phone')}\n"
        f"🏙 {order.get('city')}\n"
        f"🚚 {order.get('delivery_method')} — {order.get('delivery_point')}\n\n"
        f"🛒 Товари:\n" + "\n".join(lines) +
        f"\n\n💰 Разом: {order.get('total')} ₴"
    )