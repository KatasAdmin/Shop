import base64
import json
import time
import requests
from typing import Optional, Tuple, Dict, Any

from config import GITHUB_TOKEN, GITHUB_REPO, GITHUB_BRANCH, GITHUB_DATA_PATH, GITHUB_SYNC_INTERVAL

API = "https://api.github.com"

_last_push_ts = 0.0
_cached_sha: Optional[str] = None


def _enabled() -> bool:
    return bool(GITHUB_TOKEN and GITHUB_REPO and GITHUB_BRANCH)


def github_get_file(path: str) -> Optional[Tuple[Dict[str, Any], str]]:
    """
    Повертає (data, sha) або None.
    """
    if not _enabled():
        return None

    url = f"{API}/repos/{GITHUB_REPO}/contents/{path}"
    r = requests.get(url, params={"ref": GITHUB_BRANCH}, headers={
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json"
    }, timeout=15)

    if r.status_code != 200:
        return None

    j = r.json()
    content = j.get("content", "")
    sha = j.get("sha", "")
    if not content or not sha:
        return None

    raw = base64.b64decode(content)
    data = json.loads(raw.decode("utf-8"))
    return data, sha


def github_put_file(path: str, data: Dict[str, Any], sha: Optional[str] = None) -> bool:
    """
    Створює/оновлює файл у GitHub. Повертає True/False.
    """
    if not _enabled():
        return False

    url = f"{API}/repos/{GITHUB_REPO}/contents/{path}"
    body = {
        "message": "sync data.json",
        "content": base64.b64encode(
            json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        ).decode("ascii"),
        "branch": GITHUB_BRANCH,
    }
    if sha:
        body["sha"] = sha

    r = requests.put(url, headers={
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json"
    }, json=body, timeout=20)

    # 200/201 = ok
    if r.status_code in (200, 201):
        j = r.json()
        new_sha = (j.get("content") or {}).get("sha")
        global _cached_sha
        if new_sha:
            _cached_sha = new_sha
        return True

    return False


def pull_data_if_possible() -> Optional[Dict[str, Any]]:
    """
    Підтягує data.json з GitHub (якщо є і налаштовано).
    """
    global _cached_sha
    got = github_get_file(GITHUB_DATA_PATH)
    if not got:
        return None
    data, sha = got
    _cached_sha = sha
    return data


def push_data_throttled(data: Dict[str, Any]) -> None:
    """
    Пушить дані в GitHub не частіше ніж раз на GITHUB_SYNC_INTERVAL секунд.
    """
    global _last_push_ts, _cached_sha

    if not _enabled():
        return

    now = time.time()
    if now - _last_push_ts < GITHUB_SYNC_INTERVAL:
        return

    # якщо sha ще не знаємо — спробуємо отримати
    if _cached_sha is None:
        got = github_get_file(GITHUB_DATA_PATH)
        if got:
            _, sha = got
            _cached_sha = sha

    ok = github_put_file(GITHUB_DATA_PATH, data, sha=_cached_sha)
    if ok:
        _last_push_ts = now