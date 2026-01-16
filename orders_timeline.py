# orders_timeline.py
from __future__ import annotations

import time
from typing import Dict, Any, List


def _evt(order: Dict[str, Any], code: str, title: str, details: str = "") -> None:
    order.setdefault("events", [])
    order["events"].append({
        "ts": int(time.time()),
        "code": str(code),
        "title": str(title),
        "details": str(details or ""),
    })


def order_ensure_events(order: Dict[str, Any]) -> None:
    """
    Для старих замовлень без events — створимо базову подію “створено”.
    """
    order.setdefault("events", [])
    if order["events"]:
        return

    created_ts = int(order.get("created_ts", 0) or 0)
    if created_ts:
        order["events"].append({
            "ts": created_ts,
            "code": "created",
            "title": "Замовлення створено",
            "details": "",
        })


def order_set_status(order: Dict[str, Any], new_status: str, *, who: str = "", details: str = "") -> None:
    """
    ЄДИНИЙ правильний спосіб міняти статус:
    - міняє order["status"]
    - пише подію в events
    """
    old = (order.get("status") or "").strip().lower()
    ns = (new_status or "").strip().lower()
    if not ns or ns == old:
        return

    order["status"] = ns
    order_ensure_events(order)

    who_line = f"Хто: {who}\n" if who else ""
    body = f"{old or '—'} → {ns}"
    if details:
        body += "\n" + details.strip()

    _evt(order, "status", "Статус змінено", (who_line + body).strip())


def order_set_ttn(order: Dict[str, Any], ttn: str, *, who: str = "", details: str = "") -> None:
    """
    Фіксуємо ТТН:
    - пишемо і в order["ttn"], і в order["np_ttn"] (сумісність)
    - пишемо подію в events
    """
    ttn = (ttn or "").strip()
    prev = (order.get("np_ttn") or order.get("ttn") or "").strip()

    order["ttn"] = ttn
    order["np_ttn"] = ttn  # для правила "Відправлено показуємо тільки якщо є ТТН"

    order_ensure_events(order)

    who_line = f"Хто: {who}\n" if who else ""

    if not ttn and prev:
        _evt(order, "ttn", "ТТН очищено", (who_line + prev).strip())
        return

    if ttn and prev and prev != ttn:
        extra = (details or "").strip()
        msg = f"{prev} → {ttn}" + (f"\n{extra}" if extra else "")
        _evt(order, "ttn", "ТТН змінено", (who_line + msg).strip())
        return

    if ttn and not prev:
        extra = (details or "").strip()
        msg = f"{ttn}" + (f"\n{extra}" if extra else "")
        _evt(order, "ttn", "ТТН додано", (who_line + msg).strip())
        return


def _fmt_dt(ts: int) -> str:
    try:
        t = time.localtime(int(ts))
        return time.strftime("%d.%m.%Y %H:%M", t)
    except Exception:
        return "-"


def render_timeline_text(order: Dict[str, Any]) -> str:
    order_ensure_events(order)
    evs: List[Dict[str, Any]] = order.get("events", []) or []

    if not evs:
        return "📜 <b>Хронологія</b>\n\nПодій поки немає."

    evs_sorted = sorted(evs, key=lambda x: int(x.get("ts", 0) or 0))
    lines = ["📜 <b>Хронологія</b>", ""]

    for e in evs_sorted:
        ts = _fmt_dt(int(e.get("ts", 0) or 0))
        title = str(e.get("title", "") or "")
        details = str(e.get("details", "") or "")
        if details:
            lines.append(f"• <b>{title}</b> — <i>{ts}</i>\n  {details}")
        else:
            lines.append(f"• <b>{title}</b> — <i>{ts}</i>")

    ttn = (order.get("np_ttn") or order.get("ttn") or "").strip()
    if ttn:
        lines.append("")
        lines.append(f"📦 ТТН: <code>{ttn}</code>")

    return "\n".join(lines)