from __future__ import annotations

from typing import Dict, Any, Optional

from sqlalchemy.dialects.postgresql import insert

from text import is_promo_active
from config import SHOP_STATE_KEY
from db import session_scope
from models import KVStore


# =========================================================
# BASE STRUCTURE (єдина правда)
# =========================================================

def default_data() -> Dict[str, Any]:
    return {
        "categories": {},
        "carts": {},
        "orders": [],
        "managers": [],
        "favorites": {},
        "hits": [],
        "users": {},
        "user_tags": {},
        "roles": {},     # якщо ще нема
        "audit": [],     # ✅ ОЦЕ ДОДАЙ
    }


# =========================================================
# MIGRATION (старі формати → новий)
# =========================================================

def _migrate(d: Dict[str, Any]) -> Dict[str, Any]:
    base = default_data()

    if not isinstance(d, dict):
        d = {}

    # 1️⃣ гарантуємо всі ключі
    for k, v in base.items():
        d.setdefault(k, v)

    # 2️⃣ перенос товарів зі старих categories (якщо там dict)
    products_map: Dict[int, dict] = {}

    cats = d.get("categories", {}) or {}
    for cat, subs in list(cats.items()):
        if not isinstance(subs, dict):
            cats[cat] = {}
            continue

        for sub, arr in list(subs.items()):
            if not isinstance(arr, list):
                subs[sub] = []
                continue

            new_pids = []
            for item in arr:
                # старий формат: item = dict (товар)
                if isinstance(item, dict):
                    try:
                        pid = int(item.get("id"))
                    except Exception:
                        continue

                    products_map[pid] = item
                    new_pids.append(pid)

                # новий формат: item = pid
                elif isinstance(item, (int, str)):
                    try:
                        new_pids.append(int(item))
                    except Exception:
                        pass

            subs[sub] = new_pids

    # 3️⃣ зливаємо products
    if products_map:
        existing = {int(p.get("id")): p for p in d.get("products", []) if isinstance(p, dict)}
        for pid, p in products_map.items():
            if pid not in existing:
                existing[pid] = p
        d["products"] = list(existing.values())

    # 4️⃣ чистимо legacy
    d.pop("history", None)

    # 5️⃣ нормалізація списків
    d["hits"] = [int(x) for x in d.get("hits", []) if str(x).isdigit()]

    return d


# =========================================================
# LOAD / SAVE
# =========================================================

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


# =========================================================
# IDS
# =========================================================

def next_product_id(data: Dict[str, Any]) -> int:
    return max((int(p.get("id", 0)) for p in data.get("products", [])), default=0) + 1


def next_order_id(data: Dict[str, Any]) -> int:
    return max((int(o.get("id", 0)) for o in data.get("orders", [])), default=0) + 1


# =========================================================
# PRODUCTS
# =========================================================

def find_product(data: Dict[str, Any], pid: int) -> Optional[Dict[str, Any]]:
    for p in data.get("products", []):
        try:
            if int(p.get("id")) == int(pid):
                return p
        except Exception:
            continue
    return None


# =========================================================
# PRICING
# =========================================================

def _unit_price(p: dict) -> float:
    try:
        if is_promo_active(p):
            return float(p.get("promo_price") or 0)
        return float(p.get("base_price", p.get("price", 0)) or 0)
    except Exception:
        return 0.0


def cart_total(d: dict, cart) -> float:
    total = 0.0

    # старий формат
    if isinstance(cart, list):
        for pid in cart:
            p = find_product(d, int(pid))
            if p:
                total += _unit_price(p)
        return float(total)

    # новий формат
    if isinstance(cart, dict):
        for pid_str, qty in cart.items():
            try:
                pid = int(pid_str)
                qty = int(qty)
            except Exception:
                continue

            if qty <= 0:
                continue

            p = find_product(d, pid)
            if p:
                total += _unit_price(p) * qty

    return float(total)