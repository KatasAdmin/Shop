# data.py
from __future__ import annotations

from typing import Dict, Any, List, Optional

from text import is_promo_active

from sqlalchemy.dialects.postgresql import insert

from config import SHOP_STATE_KEY
from db import session_scope
from models import KVStore


def default_data() -> Dict[str, Any]:
    return {
        "categories": {},
        "carts": {},
        "orders": [],
        "managers": [],
        "favorites": {},
        "hits": [],
        "users": {},   # ✅ додати
    }


def _migrate(d: Dict[str, Any]) -> Dict[str, Any]:
    base = default_data()
    if not isinstance(d, dict):
        d = {}
    for k, v in base.items():
        d.setdefault(k, v)
    if "history" in d:
        del d["history"]
    return d


async def load_data() -> Dict[str, Any]:
    async with session_scope() as session:
        row = await session.get(KVStore, SHOP_STATE_KEY)
        if not row:
            d = default_data()
            session.add(KVStore(key=SHOP_STATE_KEY, value=d))
            return d
        return _migrate(row.value)


async def save_data(data: Dict[str, Any]) -> None:
    data = _migrate(data)

    async with session_scope() as session:
        stmt = insert(KVStore).values(key=SHOP_STATE_KEY, value=data)
        stmt = stmt.on_conflict_do_update(
            index_elements=[KVStore.key],
            set_={"value": data},
        )
        await session.execute(stmt)


def next_product_id(data: Dict[str, Any]) -> int:
    return max(
        (p["id"] for cat in data["categories"].values() for sub in cat.values() for p in sub),
        default=0
    ) + 1


def next_order_id(data: Dict[str, Any]) -> int:
    return max((o["id"] for o in data["orders"]), default=0) + 1


def find_product(data: Dict[str, Any], pid: int) -> Optional[Dict[str, Any]]:
    for cat in data["categories"].values():
        for sub in cat.values():
            for p in sub:
                if int(p.get("id", -1)) == int(pid):
                    return p
    return None


def cart_total(data: Dict[str, Any], cart: List[int]) -> float:
    total = 0.0
    now_ts = None  # можна не передавати, is_promo_active сам візьме now
    for pid in cart:
        p = find_product(data, pid)
        if not p:
            continue

        # сумісність зі старими товарами
        base = float(p.get("base_price", p.get("price", 0)) or 0)

        if is_promo_active(p, now_ts=now_ts):
            total += float(p.get("promo_price") or 0)
        else:
            total += base

    return float(total)