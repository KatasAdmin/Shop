import os
import signal
import sys
from typing import Dict, Any

from aiogram import Bot

from config import LOCK_FILE, ADMIN_ID
from data import load_data

def is_admin(uid: int) -> bool:
    return uid == ADMIN_ID

def is_manager(data: Dict[str, Any], uid: int) -> bool:
    return uid in data.get("managers", []) or is_admin(uid)

def create_lock() -> None:
    if os.path.exists(LOCK_FILE):
        print("❌ Бот уже запущен. Удали /tmp/bot.lock")
        sys.exit(1)
    with open(LOCK_FILE, "w") as f:
        f.write("lock")

def remove_lock() -> None:
    if os.path.exists(LOCK_FILE):
        os.remove(LOCK_FILE)

def setup_signals() -> None:
    def shutdown(*_):
        remove_lock()
        sys.exit(0)
    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

async def safe_send(bot: Bot, chat_id: int, text: str, **kwargs):
    try:
        await bot.send_message(chat_id, text, **kwargs)
    except Exception:
        pass

async def notify_managers(bot: Bot, text: str):
    data = load_data()
    for mid in data.get("managers", []):
        await safe_send(bot, mid, text)