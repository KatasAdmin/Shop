# text.py
from __future__ import annotations

from typing import Any, Dict, List


def b(s: str) -> str:
    return f"<b>{s}</b>"


def i(s: str) -> str:
    return f"<i>{s}</i>"


def s_(s: str) -> str:
    return f"<s>{s}</s>"


def code(s: str) -> str:
    return f"<code>{s}</code>"


def esc(text: str) -> str:
    return (
        (text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def money_uah(x: Any) -> str:
    try:
        v = float(x)
    except Exception:
        v = 0.0
    if v.is_integer():
        return f"{int(v)} ₴"
    return f"{v:.2f} ₴"


def product_price_for_order(p: Dict[str, Any]) -> float:
    """
    Поки без промо-логіки: беремо p["price"].
    Коли додамо акції — тут буде вибір promo/base.
    """
    try:
        return float(p.get("price", 0) or 0)
    except Exception:
        return 0.0


def order_premium_text(data: Dict[str, Any], order: Dict[str, Any]) -> str:
    """
    Преміум-текст замовлення для менеджера/адміна.
    Викликається з utils.format_order_text(...)
    """
    oid = order.get("id", "")
    uid = order.get("user_id", "")
    status = str(order.get("status", "new"))

    status_map = {
        "paid": "🟢 Оплачено",
        "in_work": "🟡 В роботі",
        "done": "✅ Завершено",
        "new": "🆕 Нове",
    }
    st = status_map.get(status, status)

    # товари
    lines: List[str] = []
    total = 0.0

    from data import find_product  # щоб не було циклічного імпорту на старті

    for pid in order.get("items", []):
        p = find_product(data, pid)
        if not p:
            lines.append(f"• {b('Товар')} {code('#' + str(pid))} — {i('не знайдено')}")
            continue

        name = esc(str(p.get("name", "Товар")))
        price = product_price_for_order(p)
        total += price
        lines.append(f"• {b(name)} ({code('#' + str(pid))}) — {b(money_uah(price))}")

    if not lines:
        lines.append(i("— порожньо —"))

    # доставка
    delivery = order.get("delivery", {}) or {}
    cname = esc(str(delivery.get("name", "")))
    phone = esc(str(delivery.get("phone", "")))
    city = esc(str(delivery.get("city", "")))
    np_branch = esc(str(delivery.get("np_branch", "")))
    comment = esc(str(delivery.get("comment", "")))

    delivery_lines: List[str] = []
    if cname:
        delivery_lines.append(f"• {b('Імʼя')}: {cname}")
    if phone:
        delivery_lines.append(f"• {b('Телефон')}: {phone}")
    if city:
        delivery_lines.append(f"• {b('Місто')}: {city}")
    if np_branch:
        delivery_lines.append(f"• {b('НП')}: {np_branch}")
    if comment:
        delivery_lines.append(f"• {b('Коментар')}: {i(comment)}")

    if not delivery_lines:
        delivery_lines = [i("—")]

    sep = "━━━━━━━━━━━━━━━━━━━━"

    return "\n".join([
        f"📦 {b('Замовлення')} {code('#' + str(oid))}",
        f"👤 {b('User ID')}: {code(str(uid))}",
        f"📌 {b('Статус')}: {b(st)}",
        "",
        f"🛒 {b('Склад')}:",
        *lines,
        "",
        sep,
        f"💳 {b('Разом')}: {b(money_uah(total))}",
        sep,
        "",
        f"🚚 {b('Доставка')}:",
        *delivery_lines,
    ])