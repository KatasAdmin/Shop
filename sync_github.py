# sync_github.py
import asyncio
import base64
import json
import time
from typing import Any, Dict, Optional, Tuple, Callable

import requests

from config import (
    GITHUB_TOKEN,
    GITHUB_REPO,
    GITHUB_BRANCH,
    GITHUB_DATA_PATH,
    GITHUB_SYNC_INTERVAL,
)

_cached_sha: Optional[str] = None
_last_push_ts: float = 0.0
_task: Optional[asyncio.Task] = None


def _enabled() -> bool:
    return bool(GITHUB_TOKEN and GITHUB_REPO and GITHUB_DATA_PATH)


def _headers() -> Dict[str, str]:
    return {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
    }


def _url() -> str:
    return f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_DATA_PATH}"


def github_get_file() -> Optional[Tuple[Dict[str, Any], str]]:
    if not _enabled():
        return None

    try:
        r = requests.get(
            _url(),
            headers=_headers(),
            params={"ref": GITHUB_BRANCH},
            timeout=15,
        )
        if r.status_code == 404:
            return None
        r.raise_for_status()

        j = r.json()
        content_b64 = (j.get("content") or "").replace("\n", "")
        sha = j.get("sha") or ""

        raw = base64.b64decode(content_b64).decode("utf-8")
        data = json.loads(raw)
        return data, sha

    except Exception as e:
        print("github_get_file error:", e)
        return None


def github_put_file(data: Dict[str, Any], sha: Optional[str]) -> bool:
    if not _enabled():
        return False

    try:
        raw = json.dumps(data, ensure_ascii=False, indent=2)
        b64 = base64.b64encode(raw.encode("utf-8")).decode("utf-8")

        payload: Dict[str, Any] = {
            "message": "bot: update data.json",
            "content": b64,
            "branch": GITHUB_BRANCH,
        }
        if sha:
            payload["sha"] = sha

        r = requests.put(_url(), headers=_headers(), json=payload, timeout=15)

        # Якщо GitHub свариться — покажемо текст (дуже допомагає в дебазі)
        if r.status_code >= 400:
            print("github_put_file status:", r.status_code)
            print("github_put_file response:", r.text[:500])

        r.raise_for_status()

        j = r.json()
        new_sha = (j.get("content") or {}).get("sha")
        if new_sha:
            global _cached_sha
            _cached_sha = new_sha

        return True

    except Exception as e:
        print("github_put_file error:", e)
        return False


def pull_data_if_possible() -> Optional[Dict[str, Any]]:
    global _cached_sha
    got = github_get_file()
    if not got:
        return None
    data, sha = got
    _cached_sha = sha
    return data


def push_data_throttled(data: Dict[str, Any]) -> None:
    """
    Пушимо дані в GitHub не частіше ніж раз у GITHUB_SYNC_INTERVAL секунд.
    """
    global _last_push_ts, _cached_sha
    if not _enabled():
        return

    now = time.time()
    if (now - _last_push_ts) < float(GITHUB_SYNC_INTERVAL):
        return

    ok = github_put_file(data, _cached_sha)
    if ok:
        _last_push_ts = now


async def _periodic_loop(get_data: Callable[[], Dict[str, Any]]) -> None:
    while True:
        try:
            data = get_data()
            push_data_throttled(data)
        except Exception as e:
            print("periodic github sync error:", e)
        await asyncio.sleep(3)  # перевірка, реальний пуш все одно лімітиться GITHUB_SYNC_INTERVAL


def start_periodic_sync(get_data: Callable[[], Dict[str, Any]]) -> None:
    global _task
    if not _enabled():
        print("GitHub sync disabled (missing env vars).")
        return
    if _task and not _task.done():
        return
    _task = asyncio.create_task(_periodic_loop(get_data))