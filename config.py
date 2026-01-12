import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

# Postgres (Railway додає DATABASE_URL у Postgres service)
DATABASE_URL = os.getenv("DATABASE_URL", "")

# Ключ для збереження всього стану магазину в одній JSONB-стрічці
SHOP_STATE_KEY = os.getenv("SHOP_STATE_KEY", "shop_state")

# передплата (якщо використовуєш)
PREPAY_AMOUNT = int(os.getenv("PREPAY_AMOUNT", "200"))