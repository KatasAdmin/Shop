# services/order_events.py

import time
from typing import Dict, Any, List, Optional

from services.status_map import (
    status_exists,
    status_title,
    status_emoji,
    requires_ttn,
)


def ensure_events(order: Dict[str, Any]) -> None:
    """
    Гарантує що order["events"] існує і має правильний тип.
    """
    if "events" not in order or not isinstance(order.get("events"), list):
        order["events"] = []


def add_event(
    order: Dict[str, Any],
    code: str,
    title: str,
    *,
    details: str = "",
    by_role: str = "system",
    by_uid: Optional[int] = None,
) -> None:
    """
    Додає подію в історію замовлення.
    Формат:
      {ts, code, title, details, by_role, by_uid}
    """
    ensure_events(order)
    order["events"].append(
        {
            "ts": int(time.time()),
            "code": str(code),
            "title": str(title),
            "details": str(details or ""),
            "by_role": str(by_role or "system"),
            "by_uid": int(by_uid) if by_uid is not None else None,
        }
    )


def add_status_event(
    order: Dict[str, Any],
    new_status: str,
    *,
    details: str = "",
    by_role: str = "system",
    by_uid: Optional[int] = None,
) -> None:
    """
    Записує подію зміни статусу.
    """
    st = (new_status or "").strip().lower()
    if not status_exists(st):
        # невідомий — все одно логнемо, але як "status_unknown"
        add_event(
            order,
            "status_unknown",
            f"Статус: {st}",
            details=details,
            by_role=by_role,
            by_uid=by_uid,
        )
        return

    title = f"{status_emoji(st)} {status_title(st)}"
    add_event(order, f"status:{st}", title, details=details, by_role=by_role, by_uid=by_uid)


def set_status_safe(
    order: Dict[str, Any],
    new_status: str,
    *,
    ttn: Optional[str] = None,
    details: str = "",
    by_role: str = "system",
    by_uid: Optional[int] = None,
) -> bool:
    """
    ✅ ЄДИНИЙ правильний спосіб міняти статус:
    - перевіряє формат
    - враховує requires_ttn
    - пише event
    - ставить order["status"]
    - (опційно) ставить ТТН

    Повертає True якщо статус реально застосовано.
    """
    st = (new_status or "").strip().lower()
    if not st:
        return False

    # якщо статус вимагає ТТН — без ТТН не дамо "Відправлено"
    if requires_ttn(st):
        ttn_val = (ttn or order.get("ttn") or order.get("np_ttn") or "").strip()
        if not ttn_val:
            # НЕ ставимо shipped, але логнемо причину
            add_event(
                order,
                "status_blocked",
                "🚫 Відправлено заблоковано (немає ТТН)",
                details="Спроба поставити shipped/sent без ТТН.",
                by_role=by_role,
                by_uid=by_uid,
            )
            return False

        # якщо дали ttn в аргументі — збережемо
        if ttn:
            order["ttn"] = str(ttn).strip()

    old = (order.get("status") or "").strip().lower()
    order["status"] = st

    # лог події
    if st != old:
        add_status_event(order, st, details=details, by_role=by_role, by_uid=by_uid)
    else:
        # той самий статус — просто нотатка
        add_event(
            order,
            "status_repeat",
            f"{status_emoji(st)} {status_title(st)} (повтор)",
            details=details,
            by_role=by_role,
            by_uid=by_uid,
        )

    return True


def fmt_dt(ts: int) -> str:
    try:
        t = time.localtime(int(ts))
        return time.strftime("%d.%m.%Y %H:%M", t)
    except Exception:
        return "-"


def render_timeline(order: Dict[str, Any], *, limit: int = 30) -> str:
    """
    Повертає красивий текст “Хронологія”.
    """
    ensure_events(order)
    evs: List[Dict[str, Any]] = list(order.get("events") or [])
    if not evs:
        return "📜 <b>Хронологія</b>\n\n— поки що порожньо —"

    # нові зверху
    evs = sorted(evs, key=lambda x: int(x.get("ts", 0) or 0), reverse=True)[: max(1, int(limit))]

    lines = ["📜 <b>Хронологія</b>"]
    for e in evs:
        ts = fmt_dt(int(e.get("ts", 0) or 0))
        title = str(e.get("title", "") or "")
        details = str(e.get("details", "") or "").strip()

        if details:
            lines.append(f"• <b>{title}</b>\n  <i>{ts}</i>\n  {details}")
        else:
            lines.append(f"• <b>{title}</b>\n  <i>{ts}</i>")

    return "\n\n".join(lines)


def ensure_base_events_for_order(order: Dict[str, Any]) -> None:
    """
    Викликай при створенні замовлення.
    Додає базові події, якщо їх ще нема.
    """
    ensure_events(order)

    if not any((e.get("code") == "order_created") for e in order["events"]):
        add_event(order, "order_created", "🧾 Замовлення створено")

    # якщо вже є оплата/передплата — можемо теж відмітити (опційно)
    st = (order.get("status") or "").strip().lower()
    if st and st in ("paid", "prepay", "in_work", "shipped", "picked", "returned", "done"):
        # щоб не дублювати — перевіримо чи є status:* вже
        has_status = any(str(e.get("code", "")).startswith("status:") for e in order["events"])
        if not has_status:
            add_status_event(order, st, details="(ініціалізація зі збережених даних)")