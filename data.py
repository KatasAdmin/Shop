import json
import os
from typing import Dict, Any, List, Optional

from config import DATA_FILE

def default_data() -> Dict[str, Any]:
    return {
        "categories": {},
        "carts": {},
        "orders": [],
        "managers": []
    }

def save_data(data: Dict[str, Any]) -> None:
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_data() -> Dict[str, Any]:
    if not os.path.exists(DATA_FILE):
        d = default_data()
        save_data(d)
        return d

    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
    except Exception:
        d = default_data()
        save_data(d)
        return d

    # миграция ключей
    for k, v in default_data().items():
        d.setdefault(k, v)

    # если раньше было history — убираем (на будущее)
    if "history" in d:
        del d["history"]
        save_data(d)

    return d

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