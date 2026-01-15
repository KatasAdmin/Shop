from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional, List


# ---------- base helpers ----------

def b(s: str) -> str:
    return f"<b>{s}</b>"


def i(s: str) -> str:
    return f"<i>{s}</i>"


def s_(s: str) -> str:
    return f"<s>{s}</s>"


def code(s: str) -> str:
    return f"<code>{s}</code>"


def esc(text: str) -> str:
    # Telegram HTML safe
    return (
        (text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


# ---------- time / promo ----------

def _now_ts() -> int:
    return int(datetime.now(tz=timezone.utc).timestamp())


def is_promo_active(p: Dict[str, Any], now_ts: Optional[int] = None) -> bool:
    """
    Promo active if:
    - promo_price > 0
    - promo_until_ts is None OR now <= promo_until_ts
    """
    now = now_ts if now_ts is not None else _now_ts()

    try:
        promo_price = float(p.get("promo_price") or 0)
    except Exception:
        promo_price = 0.0

    if promo_price <= 0:
        return False

    until = p.get("promo_until_ts")
    if until is None:
        return True

    try:
        until_i = int(until)
    except Exception:
        # якщо там щось не те — вважаємо що без дати
        return True

    return now <= until_i


# ---------- prices ----------

def money_uah(x: Any) -> str:
    try:
        v = float(x)
    except Exception:
        v = 0.0

    # захист від nan/inf
    if v != v or v in (float("inf"), float("-inf")):
        v = 0.0

    if v.is_integer():
        return f"{int(v)} ₴"
    return f"{v:.2f} ₴"


def _safe_float(x: Any) -> float:
    try:
        v = float(x)
    except Exception:
        return 0.0
    if v != v or v in (float("inf"), float("-inf")):
        return 0.0
    return v


def price_line(p: Dict[str, Any]) -> str:
    """
    Якщо є акція:  💰 ~~2499 ₴~~  <b>1999 ₴</b>  🔥 <b>-20%</b>
    Інакше:         💰 <b>2499 ₴</b>
    """
    base_v = _safe_float(p.get("base_price", p.get("price", 0)))

    if is_promo_active(p):
        promo_v = _safe_float(p.get("promo_price", 0))

        perc = ""
        if base_v > 0 and promo_v > 0 and promo_v < base_v:
            off = int(round((1 - promo_v / base_v) * 100))
            if off > 0:
                perc = f"  🔥 {b(f'-{off}%')}"

        return f"💰 {s_(money_uah(base_v))}  {b(money_uah(promo_v))}{perc}"

    return f"💰 {b(money_uah(base_v))}"


def unit_price_str(p: Dict[str, Any], now_ts: Optional[int] = None) -> str:
    base = float(p.get("base_price", p.get("price", 0)) or 0)
    if is_promo_active(p, now_ts=now_ts):
        promo = float(p.get("promo_price") or 0)
        return f"{s_(money_uah(base))} → {b(money_uah(promo))}"
    return b(money_uah(base))


# ---------- product / cart / order formatting ----------

def product_card(p: Dict[str, Any]) -> str:
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

    return "\n".join(lines)


def product_short(p: Dict[str, Any]) -> str:
    name = esc(str(p.get("name", "Товар")))
    pid = p.get("id", "")
    base = _safe_float(p.get("base_price", p.get("price", 0)))
    qty = int(p.get("_qty", 1) or 1)

    if is_promo_active(p):
        promo = _safe_float(p.get("promo_price", 0))
        line = f"• {b(name)} ({code(f'#{pid}')}) — {s_(money_uah(base))} → {b(money_uah(promo))}"
    else:
        line = f"• {b(name)} ({code(f'#{pid}')}) — {b(money_uah(base))}"

    if qty > 1:
        line += f"  × {b(str(qty))}"

    return line


def cart_summary(data: Dict[str, Any], items: List[Dict[str, Any]], cart: Dict[str, int]) -> str:
    now = _now_ts()
    total = 0.0

    lines: List[str] = []
    lines.append(f"🧺 {b('Кошик')}")

    if not items:
        lines.append("Кошик порожній.")
        return "\n".join(lines)

    lines.append("")
    for p in items:
        pid = str(p.get("id", ""))
        qty = int(cart.get(pid, 0) or 0)
        if qty <= 0:
            continue

base_price = float(p.get("base_price", p.get("price", 0)) or 0)
promo_on = is_promo_active(p, now_ts=now)
promo_price = float(p.get("promo_price") or 0)

if promo_on:
    unit_text = f"{s_(money_uah(base_price))} → {b(money_uah(promo_price))}"
    unit = promo_price
else:
    unit_text = b(money_uah(base_price))
    unit = base_price

line_total = unit * qty
total += line_total

lines.append(
    f"• {b(name)} — {unit_text} × {b(str(qty))} = {b(money_uah(line_total))}"
)


def order_premium_text(data: Dict[str, Any], order: Dict[str, Any], products: List[Dict[str, Any]]) -> str:
    oid = order.get("id", "")
    status = str(order.get("status", "new"))

    status_map = {
        "paid": "🟢 Оплачено",
        "prepay": "🟣 Передплата",
        "in_work": "🟡 В роботі",
        "shipped": "🚚 Відправлено",
        "picked": "✅ Забрав (продано)",
        "not_picked": "❌ Не забрав",
        "returned": "🔁 Повернуто",
        "done": "✅ Завершено",
        "new": "🆕 Нове",
        "pending": "⏳ Очікує оплату",
    }
    st = status_map.get(status, status)

    delivery = order.get("delivery", {}) or {}
    cname = esc(str(delivery.get("name", "")))
    phone = esc(str(delivery.get("phone", "")))
    city = esc(str(delivery.get("city", "")))
    np_branch = esc(str(delivery.get("np_branch", "")))
    comment = esc(str(delivery.get("comment", "")))

    now = _now_ts()
    total = 0.0
    for p in products:
        qty = int(p.get("_qty", 1) or 1)
        unit = _safe_float(p.get("promo_price") if is_promo_active(p, now_ts=now) else p.get("base_price", p.get("price", 0)))
        total += unit * qty

    lines: List[str] = []
    lines.append(f"📦 {b('Замовлення')} {code(f'#{oid}')}")
    lines.append(f"{b('Статус')}: {b(st)}")
    lines.append(f"{b('User ID')}: {code(str(order.get('user_id', '')))}")
    lines.append("")

    lines.append(f"🛍 {b('Товари')}")
    for p in products:
        lines.append(product_short(p))

    lines.append("")
    lines.append(f"💳 {b('Разом')}: {b(money_uah(total))}")
    lines.append("")

    lines.append(f"🚚 {b('Доставка')}")
    if cname:
        lines.append(f"👤 {b('Імʼя')}: {cname}")
    if phone:
        lines.append(f"📞 {b('Телефон')}: {phone}")
    if city:
        lines.append(f"🏙 {b('Місто')}: {city}")
    if np_branch:
        lines.append(f"📦 {b('НП')}: {np_branch}")
    if comment:
        lines.append(f"📝 {b('Коментар')}: {i(comment)}")

    # ✅ ТТН / трек-номер
    ttn = (order.get("ttn") or "").strip()
    if ttn:
        lines.append("")
        lines.append(f"📮 {b('ТТН')}: {code(ttn)}")

    return "\n".join(lines)


# -------- compatibility (old imports) --------

def order_user_text(data: Dict[str, Any], order: Dict[str, Any], products: List[Dict[str, Any]]) -> str:
    """
    Сумісність зі старим кодом: раніше могли імпортувати order_user_text.
    Поки що для юзера можна показувати той самий формат, що і для менеджера.
    """
    return order_premium_text(data, order, products)