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
            [types.KeyboardButton(text="🛍 Каталог"), types.KeyboardButton(text="🧺 Корзина")],
            [types.KeyboardButton(text="📦 История заказов"), types.KeyboardButton(text="📞 Поддержка")],
            [types.KeyboardButton(text="❤️ Избранное"), types.KeyboardButton(text="🔍 Поиск")]
        ],
        resize_keyboard=True
    )

def back_to_main(admin=False):
    if admin:
        return types.ReplyKeyboardMarkup(
            keyboard=[[types.KeyboardButton(text="⬅️ Главное меню")]],
            resize_keyboard=True
        )
    else:
        return types.ReplyKeyboardMarkup(
            keyboard=[[types.KeyboardButton(text="⬅️ Главное меню")]],
            resize_keyboard=True
        )

def admin_menu():
    return types.ReplyKeyboardMarkup(
        keyboard=[
            [types.KeyboardButton(text="➕ Добавить категорию"), types.KeyboardButton(text="➖ Удалить категорию")],
            [types.KeyboardButton(text="➕ Добавить подкатегорию"), types.KeyboardButton(text="➖ Удалить подкатегорию")],
            [types.KeyboardButton(text="➕ Добавить товар"), types.KeyboardButton(text="➕ Назначить менеджера")],
            [types.KeyboardButton(text="⬅️ Главное меню")]
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

# ---------------- MESSAGE HANDLER ----------------
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

    # ---------------- ADMIN MENU ----------------
    if int(user_id) == ADMIN_ID:
        current_state = await state.get_state()

        # Если состояние None, реагируем на кнопки админа
        if not current_state:
            if text == "➕ Добавить категорию":
                await state.set_state(AdminStates.add_category)
                await message.answer("Введите название новой категории:")
                return

            elif text == "➕ Добавить подкатегорию":
                if not CATEGORIES:
                    await message.answer("Сначала добавьте категорию.", reply_markup=back_to_main(admin=True))
                    return
                kb = types.InlineKeyboardMarkup(
                    inline_keyboard=[[types.InlineKeyboardButton(text=cat, callback_data=f"addsub_{cat}")] for cat in CATEGORIES.keys()]
                )
                await message.answer("Выберите категорию для новой подкатегории:", reply_markup=kb)
                return

            elif text == "➕ Добавить товар":
                if not CATEGORIES:
                    await message.answer("Сначала добавьте категорию.", reply_markup=back_to_main(admin=True))
                    return
                kb = types.InlineKeyboardMarkup(
                    inline_keyboard=[[types.InlineKeyboardButton(text=f"{cat} -> {sub}", callback_data=f"addprod_{cat}_{sub}")]
                                     for cat, subs in CATEGORIES.items() for sub in subs]
                )
                await message.answer("Выберите категорию и подкатегорию для нового товара:", reply_markup=kb)
                return

            elif text == "➕ Назначить менеджера":
                await state.set_state(AdminStates.add_manager)
                await message.answer("Введите Telegram ID нового менеджера:")
                return

            elif text.startswith("➖"):
                await message.answer("Удаление категорий/подкатегорий через Inline-кнопки каталога.", reply_markup=back_to_main(admin=True))
                return

        # ---------------- FSM STATES ----------------
        if current_state == AdminStates.add_category:
            if text in CATEGORIES:
                await message.answer("Категория уже существует.")
            else:
                CATEGORIES[text] = {}
                save_data()
                await message.answer(f"Категория '{text}' добавлена ✅", reply_markup=admin_menu())
            await state.clear()
            return

        elif current_state == AdminStates.add_subcategory_name:
            data_state = await state.get_data()
            cat = data_state.get("category")
            if cat:
                CATEGORIES[cat][text] = []
                save_data()
                await message.answer(f"Подкатегория '{text}' добавлена в '{cat}' ✅", reply_markup=admin_menu())
            await state.clear()
            return

        elif current_state == AdminStates.add_product_name:
            await state.update_data(product_name=text)
            await message.answer("Введите цену товара (число):")
            await state.set_state(AdminStates.add_product_price)
            return

        elif current_state == AdminStates.add_product_price:
            try:
                price = float(text)
            except ValueError:
                await message.answer("Неверная цена. Введите число:")
                return
            await state.update_data(product_price=price)
            await message.answer("Введите описание товара:")
            await state.set_state(AdminStates.add_product_description)
            return

        elif current_state == AdminStates.add_product_description:
            data_state = await state.get_data()
            cat = data_state.get("category")
            sub = data_state.get("subcategory")
            name = data_state.get("product_name")
            price = data_state.get("product_price")
            description = text
            product = {"name": name, "price": price, "description": description}
            CATEGORIES[cat][sub].append(product)
            save_data()
            await message.answer(f"Товар '{name}' добавлен в '{cat} -> {sub}' ✅", reply_markup=admin_menu())
            await state.clear()
            return

        elif current_state == AdminStates.add_manager:
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

    # ---------------- USER MENU ----------------
    if text == "🛍 Каталог" or text == "⬅️ Главное меню":
        if not CATEGORIES:
            await message.answer("Каталог пуст.", reply_markup=main_menu())
            return
        kb = types.InlineKeyboardMarkup(
            inline_keyboard=[[types.InlineKeyboardButton(text=cat, callback_data=f"cat_{cat}")] for cat in CATEGORIES.keys()]
        )
        await message.answer("Выберите категорию:", reply_markup=kb)
        return

    if text == "🧺 Корзина":
        cart = user_carts.get(user_id, [])
        if not cart:
            await message.answer("Корзина пуста.", reply_markup=main_menu())
            return
        total = sum(item["price"] for item in cart)
        items_text = "\n".join(f"{i+1}. {p['name']} — ${p['price']}" for i, p in enumerate(cart))
        await message.answer(f"{items_text}\n\n💰 Итого: ${total}", reply_markup=back_to_main())
        return

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

    if text == "❤️ Избранное":
        await message.answer("Здесь будут ваши любимые товары.", reply_markup=main_menu())
        return

# ---------------- CALLBACKS ----------------
@dp.callback_query()
async def handle_callbacks(cb: types.CallbackQuery, state: FSMContext):
    data_cb = cb.data
    user_id = str(cb.from_user.id)
    load_data()

    # ---------------- ADMIN CALLBACKS ----------------
    if data_cb.startswith("addsub_"):
        cat = data_cb[7:]
        await state.update_data(category=cat)
        await cb.message.answer(f"Введите название подкатегории для '{cat}':")
        await state.set_state(AdminStates.add_subcategory_name)
        await cb.answer()
        return

    if data_cb.startswith("addprod_"):
        _, cat, sub = data_cb.split("_", 2)
        await state.update_data(category=cat, subcategory=sub)
        await cb.message.answer("Введите название товара:")
        await state.set_state(AdminStates.add_product_name)
        await cb.answer()
        return

    if data_cb.startswith("delcat_"):
        cat = data_cb[7:]
        if cat in CATEGORIES:
            del CATEGORIES[cat]
            save_data()
            await cb.message.answer(f"Категория '{cat}' удалена ✅", reply_markup=admin_menu())
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

    # ---------------- USER CALLBACKS ----------------
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
            await cb.message.answer(f"{p['name']}\nЦена: ${p['price']}\n{p['description']}", reply_markup=kb)
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
        if int(user_id) == ADMIN_ID:
            await cb.message.answer("Главное меню:", reply_markup=admin_menu())
        else:
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