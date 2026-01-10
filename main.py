import asyncio
import json
import os
import signal
import sys

from aiogram import Bot, Dispatcher, types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.storage.memory import MemoryStorage

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
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

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
            [types.KeyboardButton("🛍 Каталог"), types.KeyboardButton("🧺 Корзина")],
            [types.KeyboardButton("📦 История заказов"), types.KeyboardButton("📞 Поддержка")],
            [types.KeyboardButton("❤️ Избранное"), types.KeyboardButton("🔍 Поиск")]
        ],
        resize_keyboard=True
    )

def back_to_main():
    return types.ReplyKeyboardMarkup(
        keyboard=[[types.KeyboardButton("⬅️ Главное меню")]],
        resize_keyboard=True
    )

def admin_menu():
    return types.ReplyKeyboardMarkup(
        keyboard=[
            [types.KeyboardButton("➕ Добавить категорию"), types.KeyboardButton("➖ Удалить категорию")],
            [types.KeyboardButton("➕ Добавить подкатегорию"), types.KeyboardButton("➖ Удалить подкатегорию")],
            [types.KeyboardButton("➕ Добавить товар"), types.KeyboardButton("➕ Назначить менеджера")],
            [types.KeyboardButton("⬅️ Главное меню")]
        ],
        resize_keyboard=True
    )

# ---------------- FSM STATES ----------------
class AdminStates(StatesGroup):
    add_category = State()
    add_subcategory_name = State()
    add_product_name = State()
    add_product_price = State()
    add_product_description = State()
    add_manager = State()
    set_subcategory_for_product = State()

# ---------------- MESSAGE HANDLERS ----------------
@dp.message()
async def handle_message(message: types.Message, state: FSMContext):
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

    # ---------------- АДМИН FSM ----------------
    if int(user_id) == ADMIN_ID:
        current_state = await state.get_state()
        # Добавление категории
        if current_state == AdminStates.add_category.state:
            if text in CATEGORIES:
                await message.answer("Категория уже существует.")
            else:
                CATEGORIES[text] = {}
                save_data()
                await message.answer(f"Категория '{text}' добавлена ✅", reply_markup=admin_menu())
            await state.clear()
            return
        # Добавление подкатегории
        if current_state == AdminStates.add_subcategory_name.state:
            data = await state.get_data()
            cat = data.get("category")
            if cat:
                CATEGORIES[cat][text] = []
                save_data()
                await message.answer(f"Подкатегория '{text}' добавлена в '{cat}' ✅", reply_markup=admin_menu())
            await state.clear()
            return
        # Добавление товара
        if current_state == AdminStates.add_product_name.state:
            await state.update_data(product_name=text)
            await message.answer("Введите цену товара (число):")
            await state.set_state(AdminStates.add_product_price)
            return
        if current_state == AdminStates.add_product_price.state:
            try:
                price = float(text)
            except ValueError:
                await message.answer("Неверная цена. Введите число:")
                return
            await state.update_data(product_price=price)
            await message.answer("Введите описание товара:")
            await state.set_state(AdminStates.add_product_description)
            return
        if current_state == AdminStates.add_product_description.state:
            data = await state.get_data()
            cat = data.get("category")
            sub = data.get("subcategory")
            name = data.get("product_name")
            price = data.get("product_price")
            description = text
            product = {"name": name, "price": price, "description": description}
            CATEGORIES[cat][sub].append(product)
            save_data()
            await message.answer(f"Товар '{name}' добавлен в '{cat} -> {sub}' ✅", reply_markup=admin_menu())
            await state.clear()
            return
        # Добавление менеджера
        if current_state == AdminStates.add_manager.state:
            try:
                new_id = int(text)
                if new_id not in managers:
                    managers.append(new_id)
                    save_data()
                    await message.answer(f"Менеджер {new_id} добавлен ✅", reply_markup=admin_menu())
                else:
                    await message.answer("Менеджер уже существует.")
            except ValueError:
                await message.answer("Введите корректный числовой ID Telegram.")
            await state.clear()
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
        lines = []
        for i, order in enumerate(history, 1):
            items = ", ".join(p["name"] for p in order["items"])
            lines.append(f"{i}. {items} — ${order['total']}")
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

# ---------------- CALLBACK HANDLERS ----------------
@dp.callback_query()
async def handle_callbacks(cb: types.CallbackQuery, state: FSMContext):
    user_id = str(cb.from_user.id)
    data_cb = cb.data
    load_data()

    # ---- АДМИН CALLBACKS ----
    if int(user_id) == ADMIN_ID:
        if data_cb.startswith("delcat_"):
            cat = data_cb[7:]
            if cat in CATEGORIES:
                del CATEGORIES[cat]
                save_data()
                await cb.message.answer(f"Категория '{cat}' удалена ✅", reply_markup=admin_menu())
            await cb.answer()
            return

        if data_cb.startswith("addsub_"):
            cat = data_cb[7:]
            await state.update_data(category=cat)
            await cb.message.answer(f"Введите название подкатегории для '{cat}':")
            await state.set_state(AdminStates.add_subcategory_name)
            await cb.answer()
            return

        if data_cb.startswith("delsubcat_"):
            cat = data_cb[10:]
            subs = CATEGORIES.get(cat, {})
            if not subs:
                await cb.message.answer("В данной категории нет подкатегорий.")
                await cb.answer()
                return
            kb = types.InlineKeyboardMarkup(
                inline_keyboard=[[types.InlineKeyboardButton(text=sub, callback_data=f"delsub_{cat}_{sub}")] for sub in subs]
            )
            await cb.message.answer("Выберите подкатегорию для удаления:", reply_markup=kb)
            await cb.answer()
            return

        if data_cb.startswith("delsub_"):
            _, cat, sub = data_cb.split("_", 2)
            if sub in CATEGORIES.get(cat, {}):
                del CATEGORIES[cat][sub]
                save_data()
                await cb.message.answer(f"Подкатегория '{sub}' удалена из '{cat}' ✅", reply_markup=admin_menu())
            await cb.answer()
            return

        if data_cb.startswith("addprod_"):
            _, cat, sub = data_cb.split("_", 2)
            await state.update_data(category=cat, subcategory=sub)
            await cb.message.answer("Введите название товара:")
            await state.set_state(AdminStates.add_product_name)
            await cb.answer()
            return

    # ---- ПОЛЬЗОВАТЕЛЬ CALLBACKS ----
    if data_cb.startswith("cat_"):
        cat = data_cb[4:]
        subs = CATEGORIES.get(cat, {})
        if not subs:
            await cb.message.answer("В этой категории нет подкатегорий.", reply_markup=main_menu())
            await cb.answer()
            return
        kb = types.InlineKeyboardMarkup(
            inline_keyboard=[[types.InlineKeyboardButton(text=sub, callback_data=f"sub_{cat}_{sub}")] for sub in subs]
        )
        kb.add(types.InlineKeyboardButton(text="⬅️ Назад", callback_data="back_main"))
        await cb.message.answer("Выберите подкатегорию:", reply_markup=kb)
        await cb.answer()
        return

    if data_cb.startswith("sub_"):
        _, cat, sub = data_cb.split("_", 2)
        products = CATEGORIES.get(cat, {}).get(sub, [])
        if not products:
            await cb.message.answer("В подкатегории пока нет товаров.", reply_markup=main_menu())
            await cb.answer()
            return
        for p in products:
            kb = types.InlineKeyboardMarkup(
                inline_keyboard=[[types.InlineKeyboardButton(text="🛒 В корзину", callback_data=f"buy_{cat}_{sub}_{p['name']}")]]
            )
            await cb.message.answer(
                f"{p['name']}\nЦена: ${p['price']}\n{p['description']}",
                reply_markup=kb
            )
        await cb.answer()
        return

    if data_cb.startswith("buy_"):
        _, cat, sub, name = data_cb.split("_", 3)
        product = next((p for p in CATEGORIES[cat][sub] if p["name"] == name), None)
        if product:
            user_carts.setdefault(user_id, []).append(product)
            save_data()
            await cb.message.answer(f"Товар '{name}' добавлен в корзину ✅", reply_markup=main_menu())
        await cb.answer()
        return

    if data_cb == "back_main":
        await cb.message.answer("Главное меню:", reply_markup=main_menu())
        await cb.answer()
        return

# ---------------- START BOT ----------------
async def main():
    load_data()
    print("🚀 Бот запущен")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())