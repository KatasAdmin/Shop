import json
import os
import time
from typing import Dict, Any, List, Optional
from contextlib import contextmanager

from config import DATA_FILE, LOCK_FILE

# ✅ GitHub sync
# файл має бути github_sync.py у корені
from github_sync import pull_data_if_possible, push_data_throttled


def default_data() -> Dict[str, Any]:
    return {
        "categories": {},
        "carts": {},
        "orders": [],
        "managers": [],
        "favorites": {},  # ⭐ обране по юзерам (str(user_id) -> [pid])
        "hits": []        # 🔥 список pid "Хіти/Акції"
    }


@contextmanager
def file_lock(lock_path: str, timeout: float = 5.0):
    """
    Простой межпроцессный lock через файл (на Linux работает отлично).
    """
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


def _write_local(data: Dict[str, Any]) -> None:
    ensure_data_dir()
    with file_lock(LOCK_FILE):
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


def _read_local() -> Optional[Dict[str, Any]]:
    ensure_data_dir()
    with file_lock(LOCK_FILE):
        if not os.path.exists(DATA_FILE):
            return None
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None


def _migrate(d: Dict[str, Any]) -> Dict[str, Any]:
    # миграция ключей
    for k, v in default_data().items():
        d.setdefault(k, v)

    # если раньше было history — убираем (на будущее)
    if "history" in d:
        del d["history"]

    return d


def load_data() -> Dict[str, Any]:
    """
    ✅ Логіка:
    1) пробуємо прочитати локальний data.json
    2) якщо локально нема/битий — пробуємо підтягнути з GitHub
    3) якщо і GitHub пустий — створюємо дефолтний і зберігаємо локально (+ пуш)
    """
    local = _read_local()
    if local is not None:
        local = _migrate(local)
        # підстрахуємось: якщо локально є, але GitHub був чистий — все одно пушимо інколи
        # (не кожен раз, бо throttled)
        push_data_throttled(local)
        return local

    # локально нема/битий → пробуємо GitHub
    gh = pull_data_if_possible()
    if gh is not None:
        gh = _migrate(gh)
        _write_local(gh)
        return gh

    # ні локально, ні в GitHub → створюємо новий
    d = default_data()
    _write_local(d)
    push_data_throttled(d)
    return d


def save_data(data: Dict[str, Any]) -> None:
    """
    ✅ Зберігаємо локально + пушимо в GitHub (throttled)
    """
    data = _migrate(data)
    _write_local(data)
    push_data_throttled(data)


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
            total += float(p.get("price", 0))
    return total