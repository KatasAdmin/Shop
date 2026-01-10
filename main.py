import asyncio
import json
import os
import signal
import sys

from aiogram import Bot, Dispatcher, types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.storage.memory import MemoryStorage

# ------------------- FSM STATES -------------------
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

# ------------------- Токен бота та адміністратор -------------------
TELEGRAM_TOKEN = "8525972479:AAGyRAVgDD8AJ5LJ9yUzCqvTPZ2nej6OBdY"
ADMIN_ID = 8385663990  # твій ID

# ------------------- LOCK (щоб бот не запускати двічі) -------------------
LOCK_FILE = "/tmp/bot.lock"
if os.path.exists(LOCK_FILE):
    print("❌ Бот уже запущено")
    sys.exit(1)
with open(LOCK_FILE, "w") as f:
    f.write("lock")

def shutdown():
    if os.path.exists(LOCK_FILE):
        os.remove(LOCK_FILE)
    sys.exit(0)

signal.signal(signal.SIGTERM, lambda *_: shutdown())
signal.signal(signal.SIGINT, lambda *_: shutdown())

# ------------------- Бот та диспетчер -------------------
bot = Bot(token=TELEGRAM_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# ------------------- Зберігання даних -------------------
DATA_FILE = "data.json"
user_carts = {}
user_history = {}
CATEGORIES = {}  # {"Категорія": {"Підкатегорія": [товари]}}
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
        # ------------------- Клавіатури -------------------
def main_menu():
    return types.ReplyKeyboardMarkup(
        keyboard=[
            [types.KeyboardButton(text="🛍 Каталог"), types.KeyboardButton(text="🧺 Кошик")],
            [types.KeyboardButton(text="📦 Історія замовлень"), types.KeyboardButton(text="📞 Підтримка")],
            [types.KeyboardButton(text="❤️ Обране"), types.KeyboardButton(text="🔍 Пошук")]
        ],
        resize_keyboard=True
    )

def back_to_main():
    return types.ReplyKeyboardMarkup(
        keyboard=[[types.KeyboardButton(text="⬅️ Головне меню")]],
        resize_keyboard=True
    )

def admin_menu():
    return types.ReplyKeyboardMarkup(
        keyboard=[
            [types.KeyboardButton(text="➕ Додати категорію"), types.KeyboardButton(text="➖ Видалити категорію")],
            [types.KeyboardButton(text="➕ Додати підкатегорію"), types.KeyboardButton(text="➖ Видалити підкатегорію")],
            [types.KeyboardButton(text="➕ Додати товар"), types.KeyboardButton(text="➕ Призначити менеджера")],
            [types.KeyboardButton(text="⬅️ Головне меню")]
        ],
        resize_keyboard=True
    )

def admin_cancel_menu():
    return types.ReplyKeyboardMarkup(
        keyboard=[[types.KeyboardButton(text="❌ Відмінити")]],
        resize_keyboard=True
    )

# ------------------- Обробка повідомлень -------------------
@dp.message()
async def handle_message(message: types.Message, state: FSMContext):
    text = (message.text or "").strip()
    user_id = str(message.from_user.id)
    load_data()

    # ---------------- /start ----------------
    if text == "/start":
        if int(user_id) == ADMIN_ID:
            await message.answer("Привіт, адмін! Оберіть дію 👇", reply_markup=admin_menu())
        else:
            await message.answer("Привіт! Ласкаво просимо 👇", reply_markup=main_menu())
        return

    # ---------------- Скасування дії ----------------
    if text.lower() in ["❌ відмінити", "відмінити"]:
        await state.clear()
        await message.answer("Дія скасована ✅", reply_markup=admin_menu() if int(user_id) == ADMIN_ID else main_menu())
        return
        # ------------------- FSM STATES -------------------
# (повторно, на випадок якщо імпортовані раніше)
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


# ------------------- Обробка FSM адміна -------------------
@dp.message()
async def handle_admin(message: types.Message, state: FSMContext):
    user_id = str(message.from_user.id)
    text = (message.text or "").strip()
    if int(user_id) != ADMIN_ID:
        return  # тільки адмін

    current_state = await state.get_state()
    load_data()

    # ---------------- ДОДАТИ КАТЕГОРІЮ ----------------
    if current_state == AdminStates.add_category:
        if text == "❌ Відмінити":
            await state.clear()
            await message.answer("Дія скасована ✅", reply_markup=admin_menu())
            return
        if text in CATEGORIES:
            await message.answer("Категорія вже існує.")
        else:
            CATEGORIES[text] = {}
            save_data()
            await message.answer(f"Категорія '{text}' додана ✅", reply_markup=admin_menu())
        await state.clear()
        return

    # ---------------- ДОДАТИ ПІДКАТЕГОРІЮ ----------------
    if current_state == AdminStates.add_subcategory_name:
        data_state = await state.get_data()
        cat = data_state.get("category")
        if text == "❌ Відмінити":
            await state.clear()
            await message.answer("Дія скасована ✅", reply_markup=admin_menu())
            return
        if cat:
            CATEGORIES[cat][text] = []
            save_data()
            await message.answer(f"Підкатегорія '{text}' додана в '{cat}' ✅", reply_markup=admin_menu())
        await state.clear()
        return

    # ---------------- ДОДАТИ ТОВАР ----------------
    if current_state == AdminStates.add_product_name:
        if text == "❌ Відмінити":
            await state.clear()
            await message.answer("Дія скасована ✅", reply_markup=admin_menu())
            return
        await state.update_data(product_name=text)
        await message.answer("Введіть ціну товару (число) або ❌ Відмінити:")
        await state.set_state(AdminStates.add_product_price)
        return

    if current_state == AdminStates.add_product_price:
        if text == "❌ Відмінити":
            await state.clear()
            await message.answer("Дія скасована ✅", reply_markup=admin_menu())
            return
        try:
            price = float(text)
        except ValueError:
            await message.answer("Невірна ціна. Введіть число або ❌ Відмінити:")
            return
        await state.update_data(product_price=price)
        await message.answer("Введіть опис товару або ❌ Відмінити:")
        await state.set_state(AdminStates.add_product_description)
        return

    if current_state == AdminStates.add_product_description:
        if text == "❌ Відмінити":
            await state.clear()
            await message.answer("Дія скасована ✅", reply_markup=admin_menu())
            return
        await state.update_data(product_description=text)
        await message.answer("Надішліть фото товару (максимум 10) або ⬅️ Пропустити / ❌ Відмінити:")
        await state.set_state(AdminStates.add_product_photos)
        await state.update_data(product_photos=[])
        return

    # ---------------- ДОДАТИ ФОТО ----------------
    if current_state == AdminStates.add_product_photos:
        data_state = await state.get_data()
        photos = data_state.get("product_photos", [])
        cat = data_state.get("category")
        sub = data_state.get("subcategory")  # може бути None
        name = data_state.get("product_name")
        price = data_state.get("product_price")
        description = data_state.get("product_description")

        if text == "❌ Відмінити":
            await state.clear()
            await message.answer("Дія скасована ✅", reply_markup=admin_menu())
            return
        elif text == "⬅️ Пропустити":
            await finish_product_creation(message, state)
            return
        elif message.photo:
            if len(photos) < 10:
                photos.append(message.photo[-1].file_id)  # найвища якість
                await state.update_data(product_photos=photos)
                await message.answer(f"Фото додано ✅ ({len(photos)}/10)")
            else:
                await message.answer("Максимум 10 фото для одного товару.")
        else:
            await message.answer("Надішліть фото або натисніть ⬅️ Пропустити / ❌ Відмінити")
        return

# ---------------- Завершення додавання товару ----------------
async def finish_product_creation(message: types.Message, state: FSMContext):
    data_state = await state.get_data()
    cat = data_state.get("category")
    sub = data_state.get("subcategory")  # може бути None
    name = data_state.get("product_name")
    price = data_state.get("product_price")
    description = data_state.get("product_description")
    photos = data_state.get("product_photos", [])

    product = {"name": name, "price": price, "description": description, "photos": photos}

    if sub:
        CATEGORIES[cat][sub].append(product)
    else:
        CATEGORIES[cat].setdefault("_no_subcategory", []).append(product)

    save_data()
    await message.answer(f"Товар '{name}' додано ✅", reply_markup=admin_menu())
    await state.clear()
    # ------------------- ADMIN CALLBACKS -------------------
@dp.callback_query(F.data == "add_category")
async def cb_add_category(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return
    await callback.message.answer("Введіть назву нової категорії:")
    await state.set_state(AdminStates.add_category)
    await callback.answer()


@dp.callback_query(F.data == "add_subcategory")
async def cb_add_subcategory(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return
    kb = InlineKeyboardBuilder()
    for cat in CATEGORIES.keys():
        kb.button(text=cat, callback_data=f"subcat:{cat}")
    kb.adjust(2)
    await callback.message.answer("Оберіть категорію:", reply_markup=kb.as_markup())
    await callback.answer()


@dp.callback_query(F.data.startswith("subcat:"))
async def cb_choose_category(callback: types.CallbackQuery, state: FSMContext):
    cat = callback.data.split(":", 1)[1]
    await state.update_data(category=cat)
    await callback.message.answer(f"Введіть назву підкатегорії для «{cat}»:")
    await state.set_state(AdminStates.add_subcategory_name)
    await callback.answer()
    @dp.callback_query(F.data == "add_product")
async def cb_add_product(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return
    kb = InlineKeyboardBuilder()
    for cat in CATEGORIES.keys():
        kb.button(text=cat, callback_data=f"prod_cat:{cat}")
    kb.adjust(2)
    await callback.message.answer("Оберіть категорію товару:", reply_markup=kb.as_markup())
    await callback.answer()


@dp.callback_query(F.data.startswith("prod_cat:"))
async def cb_product_category(callback: types.CallbackQuery, state: FSMContext):
    cat = callback.data.split(":", 1)[1]
    await state.update_data(category=cat)

    kb = InlineKeyboardBuilder()
    for sub in CATEGORIES[cat].keys():
        kb.button(text=sub, callback_data=f"prod_sub:{sub}")
    kb.button(text="Без підкатегорії", callback_data="prod_sub:none")
    kb.adjust(2)

    await callback.message.answer("Оберіть підкатегорію:", reply_markup=kb.as_markup())
    await callback.answer()


@dp.callback_query(F.data.startswith("prod_sub:"))
async def cb_product_subcategory(callback: types.CallbackQuery, state: FSMContext):
    sub = callback.data.split(":", 1)[1]
    await state.update_data(subcategory=None if sub == "none" else sub)
    await callback.message.answer("Введіть назву товару:")
    await state.set_state(AdminStates.add_product_name)
    await callback.answer()
    # ------------------- USER CATALOG -------------------
@dp.callback_query(F.data == "catalog")
async def cb_catalog(callback: types.CallbackQuery):
    kb = InlineKeyboardBuilder()
    for cat in CATEGORIES.keys():
        kb.button(text=cat, callback_data=f"user_cat:{cat}")
    kb.adjust(2)
    await callback.message.answer("Оберіть категорію:", reply_markup=kb.as_markup())
    await callback.answer()


@dp.callback_query(F.data.startswith("user_cat:"))
async def cb_user_category(callback: types.CallbackQuery):
    cat = callback.data.split(":", 1)[1]
    kb = InlineKeyboardBuilder()

    for sub in CATEGORIES[cat].keys():
        kb.button(text=sub, callback_data=f"user_sub:{cat}:{sub}")

    kb.adjust(2)
    await callback.message.answer("Оберіть підкатегорію:", reply_markup=kb.as_markup())
    await callback.answer()


@dp.callback_query(F.data.startswith("user_sub:"))
async def cb_user_subcategory(callback: types.CallbackQuery):
    _, cat, sub = callback.data.split(":")
    products = CATEGORIES[cat][sub]

    if not products:
        await callback.message.answer("Товарів поки немає.")
        await callback.answer()
        return

    for p in products:
        text = f"📦 <b>{p['name']}</b>\n💰 {p['price']} грн\n\n{p['description']}"
        if p["photos"]:
            await callback.message.answer_photo(
                p["photos"][0],
                caption=text,
                parse_mode="HTML",
                reply_markup=buy_button(p["name"])
            )
        else:
            await callback.message.answer(
                text,
                parse_mode="HTML",
                reply_markup=buy_button(p["name"])
            )
    await callback.answer()
    # ------------------- BUY FLOW -------------------
@dp.callback_query(F.data.startswith("buy:"))
async def cb_buy(callback: types.CallbackQuery):
    product_name = callback.data.split(":", 1)[1]
    user = callback.from_user

    text = (
        "🛒 <b>НОВЕ ЗАМОВЛЕННЯ</b>\n\n"
        f"👤 Клієнт: @{user.username}\n"
        f"🆔 ID: {user.id}\n"
        f"📦 Товар: {product_name}"
    )

    if MANAGER_ID:
        await bot.send_message(MANAGER_ID, text, parse_mode="HTML")

    await callback.message.answer("✅ Замовлення передано менеджеру. Очікуйте звʼязку.")
    await callback.answer()
    @dp.callback_query(F.data == "add_manager")
async def cb_add_manager(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return
    await callback.message.answer("Надішліть ID менеджера:")
    await state.set_state(AdminStates.add_manager)
    await callback.answer()


@dp.message(AdminStates.add_manager)
async def set_manager(message: types.Message, state: FSMContext):
    global MANAGER_ID
    MANAGER_ID = int(message.text)
    save_data()
    await message.answer("Менеджер призначений ✅", reply_markup=admin_menu())
    await state.clear()
    # ------------------- KEYBOARDS -------------------

def main_menu():
    keyboard = types.ReplyKeyboardMarkup(
        keyboard=[
            [types.KeyboardButton(text="🛍 Каталог")],
            [types.KeyboardButton(text="🔍 Пошук")],
            [types.KeyboardButton(text="📦 Мої замовлення")]
        ],
        resize_keyboard=True
    )
    return keyboard


def admin_menu():
    keyboard = types.ReplyKeyboardMarkup(
        keyboard=[
            [types.KeyboardButton(text="➕ Додати категорію")],
            [types.KeyboardButton(text="➕ Додати підкатегорію")],
            [types.KeyboardButton(text="➕ Додати товар")],
            [types.KeyboardButton(text="👤 Назначити менеджера")],
            [types.KeyboardButton(text="⬅️ Головне меню")]
        ],
        resize_keyboard=True
    )
    return keyboard


def cancel_keyboard():
    return types.ReplyKeyboardMarkup(
        keyboard=[
            [types.KeyboardButton(text="❌ Відмінити")]
        ],
        resize_keyboard=True
    )
    # ------------------- START & MAIN HANDLERS -------------------

@dp.message(CommandStart())
async def start_cmd(message: types.Message, state: FSMContext):
    await state.clear()

    if message.from_user.id == ADMIN_ID:
        await message.answer(
            "👋 Вітаю, адміністратор!\nОберіть дію 👇",
            reply_markup=admin_menu()
        )
    else:
        await message.answer(
            "👋 Вітаємо у магазині!",
            reply_markup=main_menu()
        )


@dp.message(F.text == "⬅️ Головне меню")
async def back_to_main(message: types.Message, state: FSMContext):
    await state.clear()

    if message.from_user.id == ADMIN_ID:
        await message.answer(
            "🔧 Адмін панель",
            reply_markup=admin_menu()
        )
    else:
        await message.answer(
            "🏠 Головне меню",
            reply_markup=main_menu()
        )


@dp.message(F.text == "🛍 Каталог")
async def open_catalog(message: types.Message):
    await message.answer("📂 Каталог товарів (у розробці)")


@dp.message(F.text == "🔍 Пошук")
async def search(message: types.Message):
    await message.answer("🔍 Введіть назву товару для пошуку")


@dp.message(F.text == "📦 Мої замовлення")
async def my_orders(message: types.Message):
    await message.answer("📦 Ваші замовлення (поки порожньо)")
    # ------------------- ADD CATEGORY -------------------

@dp.message(F.text == "➕ Додати категорію")
async def add_category_start(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return

    await state.set_state(AdminStates.add_category)
    await message.answer(
        "✍️ Введіть назву нової категорії\n\n"
        "Або натисніть ❌ Відмінити",
        reply_markup=cancel_kb()
    )


@dp.message(AdminStates.add_category, F.text == "❌ Відмінити")
async def cancel_add_category(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "❌ Дію скасовано",
        reply_markup=admin_menu()
    )


@dp.message(AdminStates.add_category)
async def save_category(message: types.Message, state: FSMContext):
    category_name = message.text.strip()

    if len(category_name) < 2:
        await message.answer("⚠️ Назва занадто коротка, спробуйте ще раз")
        return

    # 🔹 ПОКИ ЩО БЕЗ БД (тимчасово)
    # Далі підключимо SQLite / PostgreSQL

    await state.clear()
    await message.answer(
        f"✅ Категорію «{category_name}» додано",
        reply_markup=admin_menu()
    )
    # ------------------- ADD SUBCATEGORY -------------------

# ⚠️ Тимчасове сховище (поки без БД)
CATEGORIES = []           # ["Жіноче", "Чоловіче"]
SUBCATEGORIES = {}        # {"Жіноче": ["Кросівки", "Ботинки"]}


@dp.message(F.text == "➕ Додати підкатегорію")
async def add_subcategory_start(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return

    if not CATEGORIES:
        await message.answer(
            "⚠️ Спочатку створіть хоча б одну категорію",
            reply_markup=admin_menu()
        )
        return

    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=cat)] for cat in CATEGORIES
        ] + [[KeyboardButton(text="❌ Відмінити")]],
        resize_keyboard=True
    )

    await state.set_state(AdminStates.add_subcategory_category)
    await message.answer(
        "📂 Оберіть категорію для підкатегорії:",
        reply_markup=kb
    )


@dp.message(AdminStates.add_subcategory_category, F.text == "❌ Відмінити")
async def cancel_subcategory_step1(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Дію скасовано", reply_markup=admin_menu())


@dp.message(AdminStates.add_subcategory_category)
async def choose_subcategory_category(message: types.Message, state: FSMContext):
    category = message.text

    if category not in CATEGORIES:
        await message.answer("⚠️ Оберіть категорію з кнопок")
        return

    await state.update_data(category=category)
    await state.set_state(AdminStates.add_subcategory_name)

    await message.answer(
        "✍️ Введіть назву підкатегорії\n\n"
        "Або ❌ Відмінити",
        reply_markup=cancel_kb()
    )


@dp.message(AdminStates.add_subcategory_name, F.text == "❌ Відмінити")
async def cancel_subcategory_step2(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Дію скасовано", reply_markup=admin_menu())


@dp.message(AdminStates.add_subcategory_name)
async def save_subcategory(message: types.Message, state: FSMContext):
    data = await state.get_data()
    category = data["category"]
    subcategory = message.text.strip()

    if len(subcategory) < 2:
        await message.answer("⚠️ Назва занадто коротка")
        return

    SUBCATEGORIES.setdefault(category, []).append(subcategory)

    await state.clear()
    await message.answer(
        f"✅ Підкатегорію «{subcategory}» додано до «{category}»",
        reply_markup=admin_menu()
    )
    @dp.message(F.text == "➕ Додати товар")
async def add_product_start(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return

    if not CATEGORIES:
        await message.answer(
            "⚠️ Спочатку створіть категорію",
            reply_markup=admin_menu()
        )
        return

    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=cat)] for cat in CATEGORIES] +
                 [[KeyboardButton(text="❌ Відмінити")]],
        resize_keyboard=True
    )

    await state.set_state(AdminStates.add_product_category)
    await message.answer(
        "📂 Оберіть категорію товару:",
        reply_markup=kb
    )
    @dp.message(F.text == "❌ Відмінити")
async def cancel_any(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Дію скасовано", reply_markup=admin_menu())
    @dp.message(AdminStates.add_product_category)
async def choose_product_category(message: types.Message, state: FSMContext):
    category = message.text
    if category not in CATEGORIES:
        await message.answer("⚠️ Оберіть категорію з кнопок")
        return

    await state.update_data(category=category)

    subs = SUBCATEGORIES.get(category)

    if subs:
        kb = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text=sub)] for sub in subs] +
                     [[KeyboardButton(text="➡️ Без підкатегорії")],
                      [KeyboardButton(text="❌ Відмінити")]],
            resize_keyboard=True
        )
        await state.set_state(AdminStates.add_product_subcategory)
        await message.answer("📁 Оберіть підкатегорію:", reply_markup=kb)
    else:
        await state.update_data(subcategory=None)
        await state.set_state(AdminStates.add_product_name)
        await message.answer("✍️ Введіть назву товару:", reply_markup=cancel_kb())
        @dp.message(AdminStates.add_product_subcategory)
async def choose_product_subcategory(message: types.Message, state: FSMContext):
    if message.text == "➡️ Без підкатегорії":
        await state.update_data(subcategory=None)
    else:
        await state.update_data(subcategory=message.text)

    await state.set_state(AdminStates.add_product_name)
    await message.answer("✍️ Введіть назву товару:", reply_markup=cancel_kb())
    @dp.message(AdminStates.add_product_name)
async def product_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text)
    await state.set_state(AdminStates.add_product_price)
    await message.answer("💰 Введіть ціну (грн):", reply_markup=cancel_kb())


@dp.message(AdminStates.add_product_price)
async def product_price(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("⚠️ Введіть число")
        return

    await state.update_data(price=int(message.text))
    await state.set_state(AdminStates.add_product_description)
    await message.answer("📝 Введіть опис товару:", reply_markup=cancel_kb())
    @dp.message(AdminStates.add_product_description)
async def product_description(message: types.Message, state: FSMContext):
    await state.update_data(description=message.text, photos=[])
    await state.set_state(AdminStates.add_product_photos)
    await message.answer(
        "🖼 Надішліть фото товару (до 10)\n"
        "Коли готово — напишіть ✅ Готово",
        reply_markup=cancel_kb()
    )


@dp.message(AdminStates.add_product_photos, F.photo)
async def product_photos(message: types.Message, state: FSMContext):
    data = await state.get_data()
    photos = data["photos"]

    if len(photos) >= 10:
        await message.answer("⚠️ Максимум 10 фото")
        return

    photos.append(message.photo[-1].file_id)
    await state.update_data(photos=photos)

    await message.answer(f"📸 Фото додано ({len(photos)}/10)")


@dp.message(AdminStates.add_product_photos, F.text == "✅ Готово")
async def save_product(message: types.Message, state: FSMContext):
    data = await state.get_data()
    PRODUCTS.append(data)

    await state.clear()
    await message.answer(
        f"✅ Товар «{data['name']}» додано\n"
        f"💰 {data['price']} ₴",
        reply_markup=admin_menu()
    )
    @dp.message(F.text == "🛍 Каталог")
async def open_catalog(message: types.Message):
    if not PRODUCTS:
        await message.answer("📭 Каталог поки порожній")
        return

    categories = sorted(set(p["category"] for p in PRODUCTS))

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=cat, callback_data=f"cat_{cat}")]
            for cat in categories
        ]
    )

    await message.answer("🛍 Оберіть категорію:", reply_markup=kb)
    @dp.callback_query(F.data.startswith("cat_"))
async def catalog_category(cb: types.CallbackQuery):
    category = cb.data.replace("cat_", "")

    subs = sorted(set(
        p["subcategory"] for p in PRODUCTS
        if p["category"] == category and p["subcategory"]
    ))

    kb = InlineKeyboardMarkup(inline_keyboard=[])

    if subs:
        for sub in subs:
            kb.inline_keyboard.append([
                InlineKeyboardButton(
                    text=sub,
                    callback_data=f"sub_{category}_{sub}"
                )
            ])

    kb.inline_keyboard.append([
        InlineKeyboardButton(
            text="📦 Усі товари",
            callback_data=f"all_{category}"
        )
    ])

    await cb.message.answer(
        f"📂 Категорія: {category}\nОберіть підкатегорію:",
        reply_markup=kb
    )
    await cb.answer()
    @dp.callback_query(F.data.startswith("sub_"))
async def show_subcategory(cb: types.CallbackQuery):
    _, category, sub = cb.data.split("_", 2)

    products = [
        p for p in PRODUCTS
        if p["category"] == category and p["subcategory"] == sub
    ]

    await send_products(cb.message, products)
    await cb.answer()


@dp.callback_query(F.data.startswith("all_"))
async def show_all(cb: types.CallbackQuery):
    category = cb.data.replace("all_", "")
    products = [p for p in PRODUCTS if p["category"] == category]

    await send_products(cb.message, products)
    await cb.answer()
    async def send_products(message: types.Message, products: list):
    if not products:
        await message.answer("📭 Тут поки немає товарів")
        return

    for p in products:
        caption = (
            f"🛒 <b>{p['name']}</b>\n"
            f"💰 {p['price']} ₴\n\n"
            f"{p['description']}"
        )

        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(
                    text="🛒 Купити",
                    callback_data=f"buy_{PRODUCTS.index(p)}"
                )]
            ]
        )

        if p["photos"]:
            media = [
                InputMediaPhoto(
                    media=photo,
                    caption=caption if i == 0 else None,
                    parse_mode="HTML"
                )
                for i, photo in enumerate(p["photos"])
            ]
            await message.answer_media_group(media)
            await message.answer("⬇️ Оберіть дію:", reply_markup=kb)
        else:
            await message.answer(caption, reply_markup=kb, parse_mode="HTML")
            USER_CARTS = {}  # user_id -> list of product indexes
            @dp.callback_query(F.data.startswith("buy_"))
async def add_to_cart(cb: types.CallbackQuery):
    index = int(cb.data.replace("buy_", ""))
    user_id = cb.from_user.id

    USER_CARTS.setdefault(user_id, []).append(index)

    await cb.message.answer("✅ Товар додано до кошика")
    await cb.answer()
    @dp.message(F.text == "🧺 Кошик")
async def open_cart(message: types.Message):
    user_id = message.from_user.id
    cart = USER_CARTS.get(user_id, [])

    if not cart:
        await message.answer("🧺 Ваш кошик порожній")
        return

    total = 0
    kb = InlineKeyboardMarkup(inline_keyboard=[])

    for i, idx in enumerate(cart):
        product = PRODUCTS[idx]
        total += product["price"]

        kb.inline_keyboard.append([
            InlineKeyboardButton(
                text=f"❌ {product['name']}",
                callback_data=f"remove_{i}"
            )
        ])

    kb.inline_keyboard.append([
        InlineKeyboardButton(
            text=f"💳 Оформити замовлення ({total} ₴)",
            callback_data="checkout"
        )
    ])

    await message.answer(
        f"🧺 <b>Ваш кошик</b>\n💰 Разом: {total} ₴",
        reply_markup=kb,
        parse_mode="HTML"
    )
    @dp.callback_query(F.data.startswith("remove_"))
async def remove_from_cart(cb: types.CallbackQuery):
    index = int(cb.data.replace("remove_", ""))
    user_id = cb.from_user.id

    cart = USER_CARTS.get(user_id, [])

    if index < len(cart):
        cart.pop(index)

    await cb.message.answer("❌ Товар видалено з кошика")
    await cb.answer()
    @dp.callback_query(F.data == "checkout")
async def checkout(cb: types.CallbackQuery):
    user_id = cb.from_user.id
    cart = USER_CARTS.get(user_id, [])

    if not cart:
        await cb.message.answer("🧺 Кошик порожній")
        await cb.answer()
        return

    total = 0
    text = "🧾 <b>Ваше замовлення:</b>\n\n"

    for idx in cart:
        p = PRODUCTS[idx]
        total += p["price"]
        text += f"• {p['name']} — {p['price']} ₴\n"

    text += f"\n💰 <b>Разом:</b> {total} ₴"
    text += "\n\n📞 Менеджер скоро з вами зв’яжеться"

    await cb.message.answer(text, parse_mode="HTML")

    # тут пізніше буде оплата
    USER_CARTS[user_id] = []

    await cb.answer()
    MANAGERS = []  # список user_id менеджерів
ORDERS = []    # список всіх замовлень
@dp.message(F.text == "➕ Призначити менеджера")
async def assign_manager(message: types.Message):
    await message.answer("Введіть ID користувача, якого призначити менеджером:")
    await state.set_state(AdminStates.add_manager)
    @dp.message()
async def handle_add_manager(message: types.Message, state: FSMContext):
    current_state = await state.get_state()
    text = (message.text or "").strip()

    if current_state == AdminStates.add_manager:
        try:
            manager_id = int(text)
            if manager_id not in MANAGERS:
                MANAGERS.append(manager_id)
                await message.answer(f"✅ Користувач {manager_id} призначений менеджером")
            else:
                await message.answer("Цей користувач вже є менеджером")
            save_data()
        except ValueError:
            await message.answer("❌ Некоректний ID. Спробуйте ще раз")
        await state.clear()
        async def create_order(user_id: int, products: list):
    order = {
        "user_id": user_id,
        "products": products,
        "status": "new"
    }
    ORDERS.append(order)
    save_data()

    # повідомляємо всіх менеджерів
    for m_id in MANAGERS:
        text = f"🛒 <b>Нове замовлення</b>\n\n"
        total = 0
        for p in products:
            text += f"• {p['name']} — {p['price']} ₴\n"
            total += p['price']
        text += f"\n💰 <b>Разом:</b> {total} ₴"
        await bot.send_message(m_id, text, parse_mode="HTML")
        @dp.callback_query(F.data == "checkout")
async def checkout(cb: types.CallbackQuery):
    user_id = cb.from_user.id
    cart = USER_CARTS.get(user_id, [])

    if not cart:
        await cb.message.answer("🧺 Кошик порожній")
        await cb.answer()
        return

    total = 0
    text = "🧾 <b>Ваше замовлення:</b>\n\n"

    for idx in cart:
        p = PRODUCTS[idx]
        total += p["price"]
        text += f"• {p['name']} — {p['price']} ₴\n"

    text += f"\n💰 <b>Разом:</b> {total} ₴"
    text += "\n\n📞 Менеджер скоро з вами зв’яжеться"

    await cb.message.answer(text, parse_mode="HTML")

    # Створюємо замовлення для менеджера
    await create_order(user_id, [PRODUCTS[i] for i in cart])

    USER_CARTS[user_id] = []

    await cb.answer()
    @dp.message(F.text == "📦 Історія замовлень")
async def order_history(message: types.Message):
    user_id = message.from_user.id
    history = [o for o in ORDERS if o["user_id"] == user_id]

    if not history:
        await message.answer("📦 У вас ще немає замовлень")
        return

    for o in history:
        text = "🧾 <b>Замовлення:</b>\n\n"
        total = 0
        for p in o["products"]:
            text += f"• {p['name']} — {p['price']} ₴\n"
            total += p["price"]
        text += f"\n💰 <b>Разом:</b> {total} ₴"
        await message.answer(text, parse_mode="HTML")
        class OrderStates(StatesGroup):
    waiting_payment = State()
    @dp.callback_query(F.data.startswith("pay_"))
async def handle_payment(cb: types.CallbackQuery, state: FSMContext):
    user_id = cb.from_user.id
    order_idx = int(cb.data.split("_")[1])
    
    if order_idx >= len(ORDERS):
        await cb.message.answer("❌ Замовлення не знайдено")
        await cb.answer()
        return
    
    order = ORDERS[order_idx]
    if order["status"] != "new":
        await cb.message.answer("⚠️ Це замовлення вже оплачено або обробляється")
        await cb.answer()
        return
    
    await state.update_data(order_index=order_idx)
    await state.set_state(OrderStates.waiting_payment)
    
    await cb.message.answer(
        "💳 Надішліть підтвердження оплати (скрін або текст), або ❌ Відмінити",
        reply_markup=types.ReplyKeyboardMarkup(
            keyboard=[[types.KeyboardButton("❌ Відмінити")]],
            resize_keyboard=True
        )
    )
    await cb.answer()
    @dp.message()
async def confirm_payment(message: types.Message, state: FSMContext):
    current_state = await state.get_state()
    text = (message.text or "").strip()
    
    if current_state != OrderStates.waiting_payment:
        return
    
    if text == "❌ Відмінити":
        await state.clear()
        await message.answer("Дія скасована ✅", reply_markup=main_menu())
        return
    
    data = await state.get_data()
    order_idx = data.get("order_index")
    order = ORDERS[order_idx]
    
    order["status"] = "paid"
    save_data()
    
    await message.answer("✅ Оплата підтверджена! Менеджер отримає повідомлення", reply_markup=main_menu())
    
    # повідомляємо менеджерам
    for m_id in MANAGERS:
        text = f"✅ <b>Замовлення оплачено</b>\n\n"
        total = 0
        for p in order["products"]:
            text += f"• {p['name']} — {p['price']} ₴\n"
            total += p['price']
        text += f"\n💰 <b>Разом:</b> {total} ₴"
        await bot.send_message(m_id, text, parse_mode="HTML")
    
    await state.clear()
    if o["status"] == "new":
    kb = types.InlineKeyboardMarkup(
        inline_keyboard=[[types.InlineKeyboardButton("💳 Оплатити", callback_data=f"pay_{ORDERS.index(o)}")]]
    )
    await message.answer("Натисніть кнопку для оплати:", reply_markup=kb)
else:
    await message.answer(f"Статус замовлення: {o['status']}")
    DATA_FILE = "data.json"

def save_data():
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump({
            "carts": user_carts,
            "history": user_history,
            "categories": CATEGORIES,
            "managers": MANAGERS,
            "orders": ORDERS
        }, f, ensure_ascii=False, indent=4)

def load_data():
    global user_carts, user_history, CATEGORIES, MANAGERS, ORDERS
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            user_carts = data.get("carts", {})
            user_history = data.get("history", {})
            CATEGORIES = data.get("categories", {})
            MANAGERS = data.get("managers", [])
            ORDERS = data.get("orders", [])
        except json.JSONDecodeError:
            user_carts, user_history, CATEGORIES, MANAGERS, ORDERS = {}, {}, {}, [], []
            save_data()
    else:
        user_carts, user_history, CATEGORIES, MANAGERS, ORDERS = {}, {}, {}, [], []
        save_data()
        @dp.callback_query(F.data.startswith("done_"))
async def mark_done(cb: types.CallbackQuery):
    idx = int(cb.data.split("_")[1])
    order = ORDERS[idx]
    order["status"] = "completed"
    save_data()
    
    await cb.message.answer(f"Замовлення {idx} позначено як виконане ✅")
    await cb.answer()
    kb = types.InlineKeyboardMarkup(
    inline_keyboard=[[types.InlineKeyboardButton("✅ Оброблено", callback_data=f"done_{order_idx}")]]
)
