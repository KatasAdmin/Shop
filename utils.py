from __future__ import annotations

from typing import Dict, Any, List

from aiogram import Bot

from config import ADMIN_ID
from data import load_data, find_product
from text import order_premium_text


def is_admin(uid: int) -> bool:
    return uid == int(ADMIN_ID)


def is_staff(data: Dict[str, Any], uid: int) -> bool:
    return uid in (data.get("managers", []) or []) or is_admin(uid)


async def safe_send(bot: Bot, chat_id: int, text: str, **kwargs):
    try:
        await bot.send_message(chat_id, text, **kwargs)
    except Exception:
        pass


async def notify_staff(bot: Bot, text: str, **kwargs):
    data = await load_data()
    recipients = set(int(x) for x in (data.get("managers", []) or []))
    recipients.add(int(ADMIN_ID))

    for uid in recipients:
        await safe_send(bot, uid, text, **kwargs)


async def notify_user(bot: Bot, user_id: int, text: str, **kwargs):
    await safe_send(bot, int(user_id), text, **kwargs)


def format_order_text(data: Dict[str, Any], order: Dict[str, Any]) -> str:
    """
    Підтримує items у форматі:
    - [pid, pid, ...] (старий)
    - [{"pid": 12, "qty": 2}, ...] (новий)
    """
    products: List[Dict[str, Any]] = []

    for it in (order.get("items", []) or []):
        pid_int = None
        qty = 1

        if isinstance(it, dict):
            try:
                pid_int = int(it.get("pid"))
                qty = int(it.get("qty", 1) or 1)
            except Exception:
                continue
        else:
            try:
                pid_int = int(it)
                qty = 1
            except Exception:
                continue

        p = find_product(data, pid_int)
        if p:
            pp = dict(p)
            pp["_qty"] = max(1, qty)
            products.append(pp)

    return order_premium_text(data, order, products)