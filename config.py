# config.py
import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

# Railway Postgres дає DATABASE_URL у змінних середовища
DATABASE_URL = os.getenv("DATABASE_URL", "")

# ключ для збереження стану магазину в kv_store (JSONB)
SHOP_STATE_KEY = os.getenv("SHOP_STATE_KEY", "shop_state")

# передплата (наложка)
PREPAY_AMOUNT = int(os.getenv("PREPAY_AMOUNT", "200"))