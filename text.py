# text.py
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional, List


# ---------- base helpers ----------

def b(s: str) -> str:
    return f"<b>{s}</b>"


def i(s: str) -> str:
    return f"<i>{s}</i>"


def strike(s_: str) -> str:
    return f"<s>{s_}</s>"


def code(s_: str) -> str:
    return f"<code>{s_}</code>"


def esc(text: str) -> str:
    # мінімальне екранування HTML
    return (
        (text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def spacer() -> str:
    return "━━━━━━━━━━━━━━━━━━━━"


# ---------- time / promo ----------

def _now_ts() -> int:
    return int(datetime.now(tz=timezone.utc).timestamp())


def is_promo_active(p: Dict[str, Any], now_ts: Optional[int] = None) -> bool:
    """
    Promo logic:
    - promo_price > 0
    - promo_until_ts is None OR now <= promo_until_ts
    """
    now = now_ts if now_ts is not None else _now_ts()

    promo_price = float(p.get("promo_price") or 0)
    if promo_price <= 0:
        return False

    until = p.get("promo_until_ts")
    if until is None:
        return True

    try:
        until_i = int(until)
    except Exception:
        # якщо крива дата — не ламаємо, вважаємо активною
        return True

    return now <= until_i


# ---------- prices ----------

def money_uah(x: Any) -> str:
    try:
        v = float(x)
    except Exception:
        v = 0.0

    if v.is_integer():
        return f"{int(v)} ₴"
    return f"{v:.2f} ₴"


def effective_price(p: Dict[str, Any], now_ts: Optional[int] = None) -> float:
    """
    Ціна, яку треба брати для підсумку/оплати:
    - якщо акція активна -> promo_price
    - інакше -> base_price (або price якщо base_price нема)
    """
    if is_promo_active(p, now_ts=now_ts):
        return float(p.get("promo_price") or 0)
    return float(p.get("base_price", p.get("price", 0)) or 0)


def price_line(p: Dict[str, Any]) -> str:
    """
    Преміум-рядок ціни:
    - якщо є акція:  💰 ~~2499 ₴~~  <b>1999 ₴</b>  🔥 <b>-20%</b>
    - інакше:         💰 <b>2499 ₴</b>
    """
    base = float(p.get("base_price", p.get("price", 0)) or 0)

    if is_promo_active(p):
        promo = float(p.get("promo_price") or 0)

        perc = ""
        if base > 0 and 0 < promo < base:
            off = int(round((1 - promo / base) * 100))
            if off > 0:
                perc = f"  🔥 {b(f'-{off}%')}"

        return f"💰 {strike(money_uah(base))}  {b(money_uah(promo))}{perc}"

    return f"💰 {b(money_uah(base))}"


# ---------- product / cart / order formatting ----------

def product_card(p: Dict[str, Any]) -> str:
    """
    Преміум-картка товару (для показу товару)
    """
    name = esc(str(p.get("name", "Товар")))
    pid = p.get("id", "")
    desc = esc(str(p.get("description", "")).strip())

    lines: List[str] = []
    lines.append(f"✨ {b(name)}")
    lines.append(code(f"ID: {pid}"))
    lines.append("")
    lines.append(price_line(p))

    if desc:
        lines.append("")
        lines.append(f"📝 {b('Опис')}")
        lines.append(i(desc))

    lines.append("")
    lines.append(spacer())
    return "\n".join(lines)


def product_short(p: Dict[str, Any]) -> str:
    """
    Для списків/кошика: назва + ціна
    """
    name = esc(str(p.get("name", "Товар")))
    pid = p.get("id", "")
    base = float(p.get("base_price", p.get("price", 0)) or 0)

    if is_promo_active(p):
        promo = float(p.get("promo_price") or 0)
        return f"• {b(name)} ({code(f'#{pid}')}) — {strike(money_uah(base))} → {b(money_uah(promo))}"

    return f"• {b(name)} ({code(f'#{pid}')}) — {b(money_uah(base))}"


def cart_summary(items: List[Dict[str, Any]]) -> str:
    """
    Підсумок кошика (преміум)
    """
    if not items:
        return f"🛒 {b('Кошик порожній')}"

    now = _now_ts()
    total = 0.0
    lines: List[str] = [f"🛒 {b('Ваш кошик')}", spacer()]

    for p in items:
        lines.append(product_short(p))
        total += effective_price(p, now_ts=now)

    lines.append(spacer())
    lines.append(f"💳 {b('Разом')}: {b(money_uah(total))}")
    return "\n".join(lines)


def order_card(order: Dict[str, Any], items: List[Dict[str, Any]]) -> str:
    """
    Преміум-картка замовлення для адміна/менеджера
    order: твій об'єкт замовлення (id, status, created_at, delivery/customer ...)
    items: список товарів (dict) у цьому замовленні
    """
    oid = order.get("id", "")
    status = str(order.get("status", "new"))
    created = order.get("created_at")

    status_map = {
        "paid": "🟢 Оплачено",
        "in_work": "🟡 В роботі",
        "done": "✅ Завершено",
        "new": "🆕 Нове",
    }
    st = status_map.get(status, status)

    # підтримуємо обидва варіанти структури: delivery або customer
    delivery = order.get("delivery") or {}
    customer = order.get("customer") or {}
    info = delivery if delivery else customer

    phone = esc(str(info.get("phone", "")))
    name = esc(str(info.get("name", "")))
    city = esc(str(info.get("city", "")))
    addr = esc(str(info.get("address", info.get("np_branch", ""))))
    comment = esc(str(info.get("comment", "")))

    now = _now_ts()
    total = 0.0
    for p in items:
        total += effective_price(p, now_ts=now)

    lines: List[str] = []
    lines.append(f"📦 {b('Замовлення')} {code(f'#{oid}')}")
    lines.append(f"{b('Статус')}: {b(st)}")
    if created:
        lines.append(f"{b('Час')}: {code(str(created))}")

    lines.append("")
    lines.append(f"👤 {b('Клієнт')}")
    if name:
        lines.append(f"• {b('Імʼя')}: {name}")
    if phone:
        lines.append(f"• {b('Телефон')}: {phone}")
    if city:
        lines.append(f"• {b('Місто')}: {city}")
    if addr:
        lines.append(f"• {b('Адреса/НП')}: {addr}")
    if comment:
        lines.append(f"• {b('Коментар')}: {i(comment)}")

    lines.append("")
    lines.append(f"🛍 {b('Товари')}")
    for p in items:
        lines.append(product_short(p))

    lines.append("")
    lines.append(spacer())
    lines.append(f"💳 {b('Разом')}: {b(money_uah(total))}")
    lines.append(spacer())
    return "\n".join(lines)