# audit.py
from __future__ import annotations
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Dict, Optional

MAX_AUDIT = 2000  # щоб json не роздувався (можна змінити)

def now_ts() -> int:
    return int(datetime.now(timezone.utc).timestamp())

def audit_add(
    d: dict,
    *,
    actor_id: int,
    actor_role: str,
    action: str,
    entity_type: str,
    entity_id: Any = None,
    entity_name: str = "",
    before: Optional[dict] = None,
    after: Optional[dict] = None,
    note: str = "",
) -> None:
    d.setdefault("audit", [])
    entry = {
        "ts": now_ts(),
        "actor_id": int(actor_id),
        "actor_role": (actor_role or "").strip() or "manager",
        "action": action,
        "entity": {
            "type": entity_type,
            "id": entity_id,
            "name": entity_name or "",
        },
        "before": deepcopy(before) if isinstance(before, dict) else None,
        "after": deepcopy(after) if isinstance(after, dict) else None,
        "note": note or "",
    }
    d["audit"].append(entry)

    # обрізаємо хвіст
    if len(d["audit"]) > MAX_AUDIT:
        d["audit"] = d["audit"][-MAX_AUDIT:]

def pick_fields(src: dict, fields: list[str]) -> dict:
    out = {}
    for f in fields:
        if f in src:
            out[f] = src.get(f)
    return out

def fmt_ts(ts: int) -> str:
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    except Exception:
        return str(ts)