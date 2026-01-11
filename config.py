# config.py
import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
PAYMENT_SIMULATION = os.getenv("PAYMENT_SIMULATION", "true").lower() == "true"

DATA_FILE = "data.json"
LOCK_FILE = "/tmp/bot.lock"