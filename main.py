import asyncio
import json
import os
import signal
import sys
from typing import Dict, Any, List, Optional

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder

# ===================== CONFIG =====================
TELEGRAM_TOKEN = "PASTE_YOUR_TOKEN_HERE"   # ← ВСТАВЬ СВОЙ ТОКЕН
ADMIN_ID = 8385663990

DATA_FILE = "data.json"
LOCK_FILE = "/tmp/bot.lock"

PAYMENT_SIMULATION = True  # ❌ без реальной оплаты

# ===================== LOCK =====================
def create_lock():
    if os.path.exists(LOCK_FILE):
        print("❌ Бот уже запущен. Удали /tmp/bot.lock")
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
    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

# ===================== DATA =====================
def default_data():
    return {
        "categories": {},
        "carts": {},
        "orders": [],
        "managers": []
    }

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_data():
    if not os.path.exists(DATA_FILE):
        d = default_data()
        save_data(d)
        return d
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        d = json.load(f)
    for k, v in default_data().items():
        d.setdefault(k, v)
    return d

def next_product_id(data):
    return max(
        (p["id"] for cat in data["categories"].values() for sub in cat.values() for p in sub),
        default=0
    ) + 1

def next_order_id(data):
    return max((o["id"] for o in data["orders"]), default=0) + 1

def find_product(data, pid):
    for cat in data["categories"].values():
        for sub in cat.values():
            for p in sub:
                if p["id"] == pid:
                    return p
    return None

def cart_total(data, cart):
    return sum(find_product(data, pid)["price"] for pid in cart if find_product(data, pid))

# ===================== ROLES =====================
def is_admin(uid): return uid == ADMIN_ID
def is_manager(data, uid): return uid in data["managers"] or is_admin(uid)

# ===================== FSM =====================
class AdminFSM(StatesGroup):
    add_cat = State()
    add_sub_cat = State()
    add_sub_name = State()
    prod_cat = State()
    prod_sub = State()
    prod_name = State()
    prod_price = State()
    prod_desc = State()
    prod_photos = State()
    add_manager = State()

class EditProductFSM(StatesGroup):
    name = State()
    price = State()
    desc = State()

# ===================== KEYBOARDS =====================
def main_menu():
    return types.ReplyKeyboardMarkup(
        keyboard=[["🛍 Каталог", "🧺 Кошик"], ["📦 Історія замовлень"]],
        resize_keyboard=True
    )

def admin_menu():
    return types.ReplyKeyboardMarkup(
        keyboard=[
            ["➕ Додати категорію", "➕ Додати підкатегорію"],
            ["➕ Додати товар", "🛠 Товари"],
            ["👤 Додати менеджера"]
        ],
        resize_keyboard=True
    )

def manager_menu():
    return types.ReplyKeyboardMarkup(
        keyboard=[["📋 Нові замовлення"], ["📦 Усі замовлення"]],
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

def add_cart_kb(pid):
    kb = InlineKeyboardBuilder()
    kb.button(text="🛒 В кошик", callback_data=f"add:{pid}")
    return kb.as_markup()

def cart_kb(total):
    kb = InlineKeyboardBuilder()
    kb.button(text=f"💳 Оформити ({total:.2f} ₴)", callback_data="checkout")
    kb.button(text="🗑 Очистити", callback_data="clear")
    return kb.as_markup()

def pay_kb(oid):
    kb = InlineKeyboardBuilder()
    kb.button(text="💳 Оплатити", callback_data=f"pay:{oid}")
    return kb.as_markup()

def done_kb(oid):
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Виконано", callback_data=f"done:{oid}")
    return kb.as_markup()

# ===================== BOT =====================
bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ===================== START =====================
@dp.message(CommandStart())
async def start(m: types.Message):
    await m.answer("🏠 Меню", reply_markup=main_menu())

@dp.message(Command("admin"))
async def admin_cmd(m: types.Message):
    if not is_admin(m.from_user.id):
        return await m.answer("⛔️ Немає доступу")
    await m.answer("🔧 Адмін-панель", reply_markup=admin_menu())

@dp.message(Command("manager"))
async def manager_cmd(m: types.Message):
    if not is_manager(load_data(), m.from_user.id):
        return await m.answer("⛔️ Немає доступу")
    await m.answer("👔 Менеджер", reply_markup=manager_menu())

# ===================== CATALOG =====================
@dp.message(F.text == "🛍 Каталог")
async def catalog(m: types.Message):
    d = load_data()
    if not d["categories"]:
        return await m.answer("Каталог порожній")
    await m.answer("Оберіть категорію:", reply_markup=catalog_kb(d["categories"].keys()))

@dp.callback_query(F.data.startswith("cat:"))
async def choose_cat(cb: types.CallbackQuery):
    d = load_data()
    cat = cb.data.split(":")[1]
    await cb.message.answer(
        f"<b>{cat}</b>",
        parse_mode="HTML",
        reply_markup=subcat_kb(cat, d["categories"][cat].keys())
    )
    await cb.answer()

@dp.callback_query(F.data.startswith("sub:"))
async def choose_sub(cb: types.CallbackQuery):
    d = load_data()
    _, cat, sub = cb.data.split(":")
    for p in d["categories"][cat][sub]:
        text = f"<b>{p['name']}</b>\n💰 {p['price']} ₴\n\n{p['description']}"
        if p["photos"]:
            await cb.message.answer_photo(p["photos"][0], caption=text, parse_mode="HTML", reply_markup=add_cart_kb(p["id"]))
        else:
            await cb.message.answer(text, parse_mode="HTML", reply_markup=add_cart_kb(p["id"]))
    await cb.answer()

# ===================== CART =====================
@dp.callback_query(F.data.startswith("add:"))
async def add_cart(cb: types.CallbackQuery):
    d = load_data()
    uid = str(cb.from_user.id)
    d["carts"].setdefault(uid, []).append(int(cb.data.split(":")[1]))
    save_data(d)
    await cb.answer("Додано")

@dp.message(F.text == "🧺 Кошик")
async def show_cart(m: types.Message):
    d = load_data()
    uid = str(m.from_user.id)
    cart = d["carts"].get(uid, [])
    if not cart:
        return await m.answer("Кошик порожній")
    total = cart_total(d, cart)
    names = [find_product(d, pid)["name"] for pid in cart]
    await m.answer("🧺 Кошик:\n" + "\n".join(names) + f"\n\nРазом: {total:.2f} ₴", reply_markup=cart_kb(total))

@dp.callback_query(F.data == "clear")
async def clear_cart(cb: types.CallbackQuery):
    d = load_data()
    d["carts"][str(cb.from_user.id)] = []
    save_data(d)
    await cb.answer("Очищено")

# ===================== ORDER =====================
@dp.callback_query(F.data == "checkout")
async def checkout(cb: types.CallbackQuery):
    d = load_data()
    uid = str(cb.from_user.id)
    cart = d["carts"].get(uid, [])
    total = cart_total(d, cart)
    oid = next_order_id(d)
    d["orders"].append({"id": oid, "user_id": cb.from_user.id, "items": cart, "total": total, "status": "new"})
    d["carts"][uid] = []
    save_data(d)
    await cb.message.answer(f"Замовлення #{oid}\nСума: {total:.2f} ₴", reply_markup=pay_kb(oid))
    await cb.answer()

@dp.callback_query(F.data.startswith("pay:"))
async def pay(cb: types.CallbackQuery):
    d = load_data()
    oid = int(cb.data.split(":")[1])
    for o in d["orders"]:
        if o["id"] == oid:
            o["status"] = "paid"
    save_data(d)
    await cb.message.answer("✅ Оплачено (симуляція)")
    await cb.answer()

# ===================== RUN =====================
async def main():
    create_lock()
    setup_signals()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())