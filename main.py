import asyncio
import json
import os
import signal
import sys
from typing import Dict, Any, List

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder


# ===================== CONFIG =====================
TELEGRAM_TOKEN = "8525972479:AAGyRAVgDD8AJ5LJ9yUzCqvTPZ2nej6OBdY"
ADMIN_ID = 8385663990

DATA_FILE = "data.json"
LOCK_FILE = "/tmp/bot.lock"


# ===================== LOCK =====================
def create_lock():
    if os.path.exists(LOCK_FILE):
        print("❌ Бот уже запущено")
        sys.exit(1)
    with open(LOCK_FILE, "w") as f:
        f.write("lock")


def remove_lock():
    if os.path.exists(LOCK_FILE):
        os.remove(LOCK_FILE)


def setup_signals():
    def shutdown(*_):
        remove_lock()
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)


# ===================== DATA =====================
def default_data():
    return {
        "categories": {},
        "carts": {},
        "orders": [],
        "managers": []
    }


def load_data():
    if not os.path.exists(DATA_FILE):
        save_data(default_data())
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError:
        data = default_data()
        save_data(data)
        return data


def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def next_product_id(data):
    max_id = 0
    for cat in data["categories"].values():
        for sub in cat.values():
            for p in sub:
                max_id = max(max_id, int(p["id"]))
    return max_id + 1


def next_order_id(data):
    return max([o["id"] for o in data["orders"]], default=0) + 1


def find_product(data, pid):
    for cat in data["categories"].values():
        for sub in cat.values():
            for p in sub:
                if int(p["id"]) == pid:
                    return p
    return None


def cart_total(data, cart):
    total = 0
    for pid in cart:
        p = find_product(data, pid)
        if p:
            total += float(p["price"])
    return total


# ===================== FSM =====================
class AdminStates(StatesGroup):
    add_category = State()
    add_subcategory_category = State()
    add_subcategory_name = State()
    add_product_category = State()
    add_product_subcategory = State()
    add_product_name = State()
    add_product_price = State()
    add_product_description = State()
    add_product_photos = State()
    add_manager = State()


class PaymentStates(StatesGroup):
    waiting_payment = State()


# ===================== KEYBOARDS =====================
def main_menu():
    return types.ReplyKeyboardMarkup(
        keyboard=[
            [types.KeyboardButton(text="🛍 Каталог"), types.KeyboardButton(text="🧺 Кошик")],
            [types.KeyboardButton(text="📦 Історія замовлень")]
        ],
        resize_keyboard=True
    )


def admin_menu():
    return types.ReplyKeyboardMarkup(
        keyboard=[
            [types.KeyboardButton(text="➕ Додати категорію"), types.KeyboardButton(text="➕ Додати підкатегорію")],
            [types.KeyboardButton(text="➕ Додати товар"), types.KeyboardButton(text="👤 Додати менеджера")],
            [types.KeyboardButton(text="🛍 Каталог"), types.KeyboardButton(text="🧺 Кошик")]
        ],
        resize_keyboard=True
    )


def cancel_kb():
    return types.ReplyKeyboardMarkup(
        keyboard=[[types.KeyboardButton(text="❌ Відмінити")]],
        resize_keyboard=True
    )


def catalog_kb(cats):
    kb = InlineKeyboardBuilder()
    for c in cats:
        kb.button(text=c, callback_data=f"cat:{c}")
    kb.adjust(2)
    return kb.as_markup()


def subcat_kb(cat, subs):
    kb = InlineKeyboardBuilder()
    for s in subs:
        kb.button(text=s, callback_data=f"sub:{cat}:{s}")
    kb.adjust(2)
    return kb.as_markup()


def buy_kb(pid):
    kb = InlineKeyboardBuilder()
    kb.button(text="🛒 Додати в кошик", callback_data=f"buy:{pid}")
    return kb.as_markup()


def cart_kb(total):
    kb = InlineKeyboardBuilder()
    kb.button(text=f"💳 Оформити ({total} ₴)", callback_data="checkout")
    kb.button(text="🗑 Очистити", callback_data="clear_cart")
    kb.adjust(1)
    return kb.as_markup()


# ===================== BOT =====================
bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher(storage=MemoryStorage())


# ===================== START =====================
@dp.message(CommandStart())
async def start(message: types.Message, state: FSMContext):
    await state.clear()
    if message.from_user.id == ADMIN_ID:
        await message.answer("👋 Адмін-панель", reply_markup=admin_menu())
    else:
        await message.answer("👋 Ласкаво просимо", reply_markup=main_menu())


# ===================== RUN =====================
async def main():
    create_lock()
    setup_signals()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())