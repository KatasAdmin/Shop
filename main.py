import asyncio
import json
import os
import signal
import sys

from aiogram import Bot, Dispatcher, types

# ---------------- BOT TOKEN & ADMIN ----------------
TELEGRAM_TOKEN = "8525972479:AAGyRAVgDD8AJ5LJ9yUzCqvTPZ2nej6OBdY"
ADMIN_ID = 8385663990

# ---------------- LOCK ----------------
LOCK_FILE = "/tmp/bot.lock"
if os.path.exists(LOCK_FILE):
    print("❌ Бот уже запущен")
    sys.exit(1)

with open(LOCK_FILE, "w") as f:
    f.write("lock")

def shutdown():
    if os.path.exists(LOCK_FILE):
        os.remove(LOCK_FILE)
    sys.exit(0)

signal.signal(signal.SIGTERM, lambda *_: shutdown())
signal.signal(signal.SIGINT, lambda *_: shutdown())

# ---------------- BOT & DISPATCHER ----------------
bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()

# ---------------- STORAGE ----------------
DATA_FILE = "data.json"
user_carts = {}
user_history = {}
CATEGORIES = {}  # {"Категория": {"Подкатегория": [товары]}}
managers = []

def save_data():
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump({
            "carts": user_carts,
            "history": user_history,
            "categories": CATEGORIES,
            "managers": managers
        }, f, ensure_ascii=False, indent=4)

def load_data():
    global user_carts, user_history, CATEGORIES, managers
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            user_carts = data.get("carts", {})
            user_history = data.get("history", {})
            CATEGORIES = data.get("categories", {})
            managers = data.get("managers", [])
        except json.JSONDecodeError:
            user_carts, user_history, CATEGORIES, managers = {}, {}, {}, []
            save_data()
    else:
        user_carts, user_history, CATEGORIES, managers = {}, {}, {}, []
        save_data()

# ---------------- KEYBOARDS ----------------
def main_menu():
    return types.ReplyKeyboardMarkup(
        keyboard=[
            [types.KeyboardButton(text="🛍 Каталог"), types.KeyboardButton(text="🧺 Корзина")],
            [types.KeyboardButton(text="📦 История заказов"), types.KeyboardButton(text="📞 Поддержка")],
            [types.KeyboardButton(text="❤️ Избранное"), types.KeyboardButton(text="🔍 Поиск")]
        ],
        resize_keyboard=True
    )

def back_to_main():
    return types.ReplyKeyboardMarkup(
        keyboard=[[types.KeyboardButton(text="⬅️ Главное меню")]],
        resize_keyboard=True
    )

def admin_menu():
    return types.ReplyKeyboardMarkup(
        keyboard=[
            [types.KeyboardButton(text="➕ Добавить категорию"), types.KeyboardButton(text="➖ Удалить категорию")],
            [types.KeyboardButton(text="➕ Добавить подкатегорию"), types.KeyboardButton(text="➖ Удалить подкатегорию")],
            [types.KeyboardButton(text="➕ Добавить товар")],
            [types.KeyboardButton(text="⬅️ Главное меню")]
        ],
        resize_keyboard=True
    )

# ---------------- HANDLERS ----------------
@dp.message()
async def handle_message(message: types.Message):
    text = (message.text or "").strip()
    user_id = str(message.from_user.id)
    load_data()

    # ---------------- /start ----------------
    if text == "/start":
        if int(user_id) == ADMIN_ID:
            await message.answer("Привет, админ! Выберите действие 👇", reply_markup=admin_menu())
        else:
            await message.answer("Привет! Добро пожаловать 👇", reply_markup=main_menu())
        return

    # ---------------- КАТАЛОГ ----------------
    if text == "🛍 Каталог" or text == "⬅️ Главное меню":
        if not CATEGORIES:
            await message.answer("Каталог пуст.", reply_markup=main_menu())
            return
        kb = types.InlineKeyboardMarkup(
            inline_keyboard=[[types.InlineKeyboardButton(text=cat, callback_data=f"cat_{cat}")] for cat in CATEGORIES.keys()]
        )
        await message.answer("Выберите категорию:", reply_markup=kb)
        return

    # ---------------- КОРЗИНА ----------------
    if text == "🧺 Корзина":
        cart = user_carts.get(user_id, [])
        if not cart:
            await message.answer("Корзина пуста.", reply_markup=main_menu())
            return
        total = sum(item["price"] for item in cart)
        items_text = "\n".join(f"{i+1}. {p['name']} — ${p['price']}" for i, p in enumerate(cart))
        await message.answer(f"{items_text}\n\n💰 Итого: ${total}", reply_markup=back_to_main())
        return

    # ---------------- ИСТОРИЯ ----------------
    if text == "📦 История заказов":
        history = user_history.get(user_id, [])
        if not history:
            await message.answer("История пуста.", reply_markup=main_menu())
            return
        lines = [f"{i+1}. {', '.join(p['name'] for p in order['items'])} — ${order['total']}" for i, order in enumerate(history)]
        await message.answer("\n".join(lines), reply_markup=main_menu())
        return

    # ---------------- ПОДДЕРЖКА ----------------
    if text == "📞 Поддержка":
        if not managers:
            await message.answer("Нет доступных менеджеров.", reply_markup=main_menu())
            return
        for m in managers:
            try:
                await bot.send_message(m, f"Пользователь {user_id} просит поддержку")
            except:
                pass
        await message.answer("Менеджер уведомлен.", reply_markup=main_menu())
        return

    # ---------------- ИЗБРАННОЕ ----------------
    if text == "❤️ Избранное":
        await message.answer("Здесь будут ваши любимые товары.", reply_markup=main_menu())
        return

    # ---------------- АДМИН-ПАНЕЛЬ ----------------
    if int(user_id) == ADMIN_ID:
        if text == "➕ Добавить категорию":
            await message.answer("Введите название новой категории:")
            return
        if text == "➖ Удалить категорию":
            if not CATEGORIES:
                await message.answer("Нет категорий для удаления.")
                return
            kb = types.InlineKeyboardMarkup(
                inline_keyboard=[[types.InlineKeyboardButton(text=cat, callback_data=f"delcat_{cat}")] for cat in CATEGORIES.keys()]
            )
            await message.answer("Выберите категорию для удаления:", reply_markup=kb)
            return
        if text == "➕ Добавить подкатегорию":
            if not CATEGORIES:
                await message.answer("Сначала добавьте категорию.")
                return
            kb = types.InlineKeyboardMarkup(
                inline_keyboard=[[types.InlineKeyboardButton(text=cat, callback_data=f"addsub_{cat}")] for cat in CATEGORIES.keys()]
            )
            await message.answer("Выберите категорию для новой подкатегории:", reply_markup=kb)
            return
        if text == "➖ Удалить подкатегорию":
            if not CATEGORIES:
                await message.answer("Категории отсутствуют.")
                return
            kb = types.InlineKeyboardMarkup(
                inline_keyboard=[[types.InlineKeyboardButton(text=cat, callback_data=f"delsubcat_{cat}")] for cat in CATEGORIES.keys()]
            )
            await message.answer("Выберите категорию, из которой удалять подкатегорию:", reply_markup=kb)
            return
        if text == "➕ Добавить товар":
            if not CATEGORIES:
                await message.answer("Сначала добавьте категорию и подкатегорию.")
                return
            kb = types.InlineKeyboardMarkup(
                inline_keyboard=[
                    [types.InlineKeyboardButton(text=f"{cat} -> {sub}", callback_data=f"addprod_{cat}_{sub}")]
                    for cat, subs in CATEGORIES.items() for sub in subs.keys()
                ]
            )
            await message.answer("Выберите подкатегорию для нового товара:", reply_markup=kb)
            return

    # ---------------- НЕПРЕДУСМОТРЕННОЕ ----------------
    await message.answer("Выберите действие из меню 👇", reply_markup=main_menu())

# ---------------- CALLBACKS ----------------
@dp.callback_query()
async def callbacks(cb: types.CallbackQuery):
    user_id = str(cb.from_user.id)
    data = cb.data

    # ----------- КАТЕГОРИИ / ПОДКАТЕГОРИИ -----------
    if data.startswith("cat_"):
        cat = data[4:]
        subs = CATEGORIES.get(cat, {})
        kb = types.InlineKeyboardMarkup(
            inline_keyboard=[[types.InlineKeyboardButton(text=sub, callback_data=f"sub_{cat}_{sub}")] for sub in subs] +
            [[types.InlineKeyboardButton(text="⬅️ Назад", callback_data="back_main")]]
        )
        await cb.message.answer("Подкатегории:", reply_markup=kb)
        await cb.answer()
        return

    if data.startswith("sub_"):
        _, cat, sub = data.split("_", 2)
        products = CATEGORIES.get(cat, {}).get(sub, [])
        for p in products:
            kb = types.InlineKeyboardMarkup(
                inline_keyboard=[[types.InlineKeyboardButton(text="🛒 В корзину", callback_data=f"buy_{cat}_{sub}_{p['name']}")]]
            )
            await cb.message.answer(f"{p['name']}\n${p['price']}\n{p['description']}", reply_markup=kb)
        await cb.answer()
        return

    if data.startswith("buy_"):
        _, cat, sub, name = data.split("_", 3)
        product = next(p for p in CATEGORIES[cat][sub] if p["name"] == name)
        user_carts.setdefault(user_id, []).append(product)
        save_data()
        await cb.message.answer("Добавлено в корзину ✅", reply_markup=main_menu())
        await cb.answer()
        return

    # ----------- АДМИН ДЕЙСТВИЯ -----------
    if data.startswith("delcat_"):
        cat = data[7:]
        CATEGORIES.pop(cat, None)
        save_data()
        await cb.message.answer(f"Категория '{cat}' удалена ✅", reply_markup=admin_menu())
        await cb.answer()
        return

    if data.startswith("addsub_"):
        cat = data[7:]
        if cat not in CATEGORIES:
            CATEGORIES[cat] = {}
        await cb.message.answer(f"Введите название новой подкатегории для '{cat}':")
        await cb.answer()
        return

    if data.startswith("delsubcat_"):
        cat = data[10:]
        subs = CATEGORIES.get(cat, {})
        if not subs:
            await cb.message.answer("Подкатегорий нет.")
            await cb.answer()
            return
        kb = types.InlineKeyboardMarkup(
            inline_keyboard=[[types.InlineKeyboardButton(text=sub, callback_data=f"del_sub_{cat}_{sub}")] for sub in subs]
        )
        await cb.message.answer("Выберите подкатегорию для удаления:", reply_markup=kb)
        await cb.answer()
        return

    if data.startswith("del_sub_"):
        _, cat, sub = data.split("_", 2)
        CATEGORIES.get(cat, {}).pop(sub, None)
        save_data()
        await cb.message.answer(f"Подкатегория '{sub}' удалена ✅", reply_markup=admin_menu())
        await cb.answer()
        return

# ---------------- START ----------------
async def main():
    load_data()
    print("🚀 Бот запущен")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())