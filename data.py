from __future__ import annotations

import time
from typing import Dict, Any, List, Optional

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from config import SHOP_STATE_KEY
from db import SessionLocal
from models import KVStore


def default_data() -> Dict[str, Any]:
    return {
        "categories": {},
        "carts": {},
        "orders": [],
        "managers": [],
        "favorites": {},
        "hits": [],
    }


def _migrate(d: Dict[str, Any]) -> Dict[str, Any]:
    for k, v in default_data().items():
        d.setdefault(k, v)
    if "history" in d:
        del d["history"]
    return d


# простий кеш (щоб не читати БД кожен раз)
_cache: Optional[Dict[str, Any]] = None
_cache_ts: float = 0.0
CACHE_TTL_SEC = 2.0


async def load_data(force: bool = False) -> Dict[str, Any]:
    global _cache, _cache_ts

    if not force and _cache is not None and (time.time() - _cache_ts) < CACHE_TTL_SEC:
        return _cache

    async with SessionLocal() as session:
        res = await session.execute(select(KVStore).where(KVStore.key == SHOP_STATE_KEY))
        row = res.scalar_one_or_none()

        if row is None:
            d = default_data()
            row = KVStore(key=SHOP_STATE_KEY, value=d)
            session.add(row)
            await session.commit()
            _cache = d
            _cache_ts = time.time()
            return _cache

        d = _migrate(dict(row.value or {}))
        _cache = d
        _cache_ts = time.time()
        return _cache


async def save_data(data: Dict[str, Any]) -> None:
    global _cache, _cache_ts

    data = _migrate(data)

    async with SessionLocal() as session:
        stmt = insert(KVStore).values(key=SHOP_STATE_KEY, value=data)
        stmt = stmt.on_conflict_do_update(
            index_elements=[KVStore.key],
            set_={"value": data},
        )
        await session.execute(stmt)
        await session.commit()

    _cache = data
    _cache_ts = time.time()


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
                if p["id"] == pid:
                    return p
    return None


def cart_total(data: Dict[str, Any], cart: List[int]) -> float:
    total = 0.0
    for pid in cart:
        p = find_product(data, pid)
        if p:
            total += float(p["price"])
    return total