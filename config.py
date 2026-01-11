import os
from dotenv import load_dotenv

load_dotenv()

# -------------------- BOT --------------------

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

# -------------------- DATA STORAGE --------------------
# Локально в Railway без Volume файли можуть пропадати.
# Тому: або Volume (/app/storage/...), або тимчасовий GitHub sync.

DATA_FILE = os.getenv("DATA_FILE", "data.json")
LOCK_FILE = os.getenv("LOCK_FILE", "/tmp/bot.lock")

# -------------------- PAYMENT --------------------

PAYMENT_SIMULATION = os.getenv("PAYMENT_SIMULATION", "1") == "1"

# -------------------- GITHUB BACKUP (TEMP) --------------------
# Щоб дані НЕ пропадали між деплоями (поки ти без Volume).

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO = os.getenv("GITHUB_REPO", "")          # формат: "username/repo"
GITHUB_BRANCH = os.getenv("GITHUB_BRANCH", "main")  # main або master
GITHUB_DATA_PATH = os.getenv("GITHUB_DATA_PATH", "data.json")

# пушимо не частіше ніж раз у N секунд (щоб GitHub не лімітив)
GITHUB_SYNC_INTERVAL = int(os.getenv("GITHUB_SYNC_INTERVAL", "15"))