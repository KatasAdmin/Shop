# data.py
import json
import os
import time
from typing import Dict, Any, List, Optional
from contextlib import contextmanager

from config import DATA_FILE, LOCK_FILE
from sync_github import push_data_throttled


def default_data() -> Dict[str, Any]:
    return {
        "categories": {},
        "carts": {},
        "orders": [],
        "managers": [],
        "favorites": {},  # ⭐ обране
        "hits": []        # 🔥 хіти/акції
    }


@contextmanager
def file_lock(lock_path: str, timeout: float = 5.0):
    start = time.time()
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o666)
    try:
        import fcntl
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.time() - start > timeout:
                    raise TimeoutError("Could not acquire lock in time")
                time.sleep(0.05)
        yield
    finally:
        try:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_UN)
        except Exception:
            pass
        os.close(fd)


def ensure_data_dir():
    d = os.path.dirname(DATA_FILE)
    if d and d != ".":
        os.makedirs(d, exist_ok=True)


def _migrate(d: Dict[str, Any]) -> Dict[str, Any]:
    # гарантуємо наявність ключів
    for k, v in default_data().items():
        d.setdefault(k, v)

    # прибираємо старе/непотрібне
    if "history" in d:
        del d["history"]

    # додатковий захист: типи
    d.setdefault("orders", [])
    d.setdefault("carts", {})
    d.setdefault("favorites", {})
    d.setdefault("hits", [])
    d.setdefault("managers", [])
    d.setdefault("categories", {})

    return d


def save_data(data: Dict[str, Any]) -> None:
    ensure_data_dir()
    data = _migrate(data)

    with file_lock(LOCK_FILE):
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    # ✅ Пушимо в GitHub (якщо налаштовано), але з throttling
    push_data_throttled(data)


def load_data() -> Dict[str, Any]:
    """
    ✅ ТІЛЬКИ локальне читання.
    GitHub pull робимо один раз на старті у main.py
    """
    ensure_data_dir()

    with file_lock(LOCK_FILE):
        if not os.path.exists(DATA_FILE):
            d = default_data()
            with open(DATA_FILE, "w", encoding="utf-8") as f:
                json.dump(d, f, ensure_ascii=False, indent=2)
            return d

        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                d = json.load(f)
        except Exception:
            d = default_data()
            with open(DATA_FILE, "w", encoding="utf-8") as f:
                json.dump(d, f, ensure_ascii=False, indent=2)
            return d

        return _migrate(d)


def next_product_id(data: Dict[str, Any]) -> int:
    return max(
        (int(p.get("id", 0)) for cat in data["categories"].values() for sub in cat.values() for p in sub),
        default=0
    ) + 1


def next_order_id(data: Dict[str, Any]) -> int:
    return max((int(o.get("id", 0)) for o in data.get("orders", [])), default=0) + 1


def find_product(data: Dict[str, Any], pid: int) -> Optional[Dict[str, Any]]:
    pid = int(pid)
    for cat in data.get("categories", {}).values():
        for sub in cat.values():
            for p in sub:
                if int(p.get("id", -1)) == pid:
                    return p
    return None


def cart_total(data: Dict[str, Any], cart: List[int]) -> float:
    """
    ✅ Рахує правильно, з урахуванням акцій (promo_price/promo_until_ts),
    і підтримує старі товари де base_price може бути відсутній.
    """
    from text import is_promo_active  # логіка акцій вже там

    total = 0.0
    for pid in cart:
        p = find_product(data, int(pid))
        if not p:
            continue

        base = float(p.get("base_price", p.get("price", 0)) or 0)

        if is_promo_active(p):
            promo = float(p.get("promo_price") or 0)
            total += promo if promo > 0 else base
        else:
            total += base

    return total