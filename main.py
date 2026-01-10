import asyncio
import json
import os
import signal
import sys

from aiogram import Bot, Dispatcher, types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.storage.memory import MemoryStorage

# ------------------- Токен бота та адміністратор -------------------
TELEGRAM_TOKEN = "8525972479:AAGyRAVgDD8AJ5LJ9yUzCqvTPZ2nej6OBdY"
ADMIN_ID = 8385663990  # твій ID

# ------------------- LOCK -------------------
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
    # ------------------- FSM СТАНИ -------------------
class AdminStates(StatesGroup):
    add_category = State()
    add_subcategory_category = State()
    add_subcategory_name = State()
    add_product_category = State()
    add_product_subcategory = State()
    add_product_name = State()
    add_product_price = State()
    add_product_description = State()
    add_product_manager = State()

# ------------------- ХЕНДЛЕР ПОВІДОМЛЕНЬ -------------------
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

    # ---------------- FSM АДМІН ----------------
    if int(user_id) == ADMIN_ID:
        current_state = await state.get_state()

        # --- Додавання категорії ---
        if current_state == AdminStates.add_category:
            if text in CATEGORIES:
                await message.answer("Категорія вже існує.")
            else:
                CATEGORIES[text] = {}
                save_data()
                await message.answer(f"Категорія '{text}' додана ✅", reply_markup=admin_menu())
            await state.clear()
            return

        # --- Додавання підкатегорії ---
        elif current_state == AdminStates.add_subcategory_name:
            data_state = await state.get_data()
            cat = data_state.get("category")
            if cat:
                CATEGORIES[cat][text] = []
                save_data()
                await message.answer(f"Підкатегорія '{text}' додана у '{cat}' ✅", reply_markup=admin_menu())
            await state.clear()
            return

        # --- Додавання товару ---
        elif current_state == AdminStates.add_product_name:
            await state.update_data(product_name=text)
            await message.answer("Введіть ціну товару (число, грн):")
            await state.set_state(AdminStates.add_product_price)
            return

        elif current_state == AdminStates.add_product_price:
            try:
                price = float(text.replace("грн", "").replace("₴", "").strip())
            except ValueError:
                await message.answer("Невірна ціна. Введіть число:")
                return
            await state.update_data(product_price=price)
            await message.answer("Введіть опис товару:")
            await state.set_state(AdminStates.add_product_description)
            return

        elif current_state == AdminStates.add_product_description:
            data_state = await state.get_data()
            cat = data_state.get("category")
            sub = data_state.get("subcategory")
            name = data_state.get("product_name")
            price = data_state.get("product_price")
            description = text
            product = {"name": name, "price": price, "description": description, "photos": []}
            if sub:
                CATEGORIES[cat][sub].append(product)
            else:
                CATEGORIES[cat].setdefault("Без підкатегорії", []).append(product)
            save_data()
            await message.answer(f"Товар '{name}' доданий у '{cat}' ✅", reply_markup=admin_menu())
            await state.clear()
            return
            # ------------------- CALLBACKS -------------------
@dp.callback_query()
async def handle_callbacks(cb: types.CallbackQuery, state: FSMContext):
    data_cb = cb.data
    user_id = str(cb.from_user.id)
    load_data()

    # ---------------- АДМІН: Видалення категорії ----------------
    if data_cb.startswith("delcat_"):
        cat = data_cb[7:]
        if cat in CATEGORIES:
            del CATEGORIES[cat]
            save_data()
            await cb.message.answer(f"Категорія '{cat}' видалена ✅", reply_markup=admin_menu())
        await cb.answer()
        return

    # ---------------- АДМІН: Додавання підкатегорії ----------------
    if data_cb.startswith("addsub_"):
        cat = data_cb[7:]
        await state.update_data(category=cat)
        await cb.message.answer(f"Введіть назву підкатегорії для '{cat}' або ❌ Відмінити для скасування:")
        await state.set_state(AdminStates.add_subcategory_name)
        await cb.answer()
        return

    # ---------------- АДМІН: Видалення підкатегорії ----------------
    if data_cb.startswith("delsubcat_"):
        cat = data_cb[10:]
        subs = CATEGORIES.get(cat, {})
        if not subs:
            await cb.message.answer("У цій категорії немає підкатегорій.")
            await cb.answer()
            return
        kb = types.InlineKeyboardMarkup(
            inline_keyboard=[[types.InlineKeyboardButton(text=sub, callback_data=f"delsub_{cat}_{sub}")] for sub in subs]
        )
        await cb.message.answer("Оберіть підкатегорію для видалення:", reply_markup=kb)
        await cb.answer()
        return

    if data_cb.startswith("delsub_"):
        _, cat, sub = data_cb.split("_", 2)
        if sub in CATEGORIES.get(cat, {}):
            del CATEGORIES[cat][sub]
            save_data()
            await cb.message.answer(f"Підкатегорія '{sub}' видалена з '{cat}' ✅", reply_markup=admin_menu())
        await cb.answer()
        return

    # ---------------- АДМІН: Додавання товару ----------------
    if data_cb.startswith("addprod_"):
        _, cat, sub = data_cb.split("_", 2)
        await state.update_data(category=cat, subcategory=sub)
        await cb.message.answer("Введіть назву товару або ❌ Відмінити для скасування:")
        await state.set_state(AdminStates.add_product_name)
        await cb.answer()
        return

    # ---------------- Користувацький каталог ----------------
    if data_cb.startswith("cat_"):
        cat = data_cb[4:]
        subs = CATEGORIES.get(cat, {})
        if not subs:
            await cb.message.answer("У цій категорії немає підкатегорій.", reply_markup=main_menu())
            await cb.answer()
            return
        kb = types.InlineKeyboardMarkup(
            inline_keyboard=[[types.InlineKeyboardButton(text=sub, callback_data=f"sub_{cat}_{sub}")] for sub in subs]
        )
        kb.add(types.InlineKeyboardButton(text="⬅️ Назад", callback_data="back_main"))
        await cb.message.answer("Оберіть підкатегорію:", reply_markup=kb)
        await cb.answer()
        return

    if data_cb.startswith("sub_"):
        _, cat, sub = data_cb.split("_", 2)
        products = CATEGORIES.get(cat, {}).get(sub, [])
        if not products:
            await cb.message.answer("У підкатегорії поки немає товарів.", reply_markup=main_menu())
            await cb.answer()
            return
        for p in products:
            kb = types.InlineKeyboardMarkup(
                inline_keyboard=[[types.InlineKeyboardButton(text="🛒 В корзину", callback_data=f"buy_{cat}_{sub}_{p['name']}")]]
            )
            photos = p.get("photos", [])
            if photos:
                media = [types.InputMediaPhoto(media=ph, caption=f"{p['name']}\nЦіна: {p['price']}₴\n{p['description']}") for ph in photos]
                await cb.message.answer_media_group(media)
            else:
                await cb.message.answer(f"{p['name']}\nЦіна: {p['price']}₴\n{p['description']}", reply_markup=kb)
        await cb.answer()
        return

    if data_cb.startswith("buy_"):
        _, cat, sub, name = data_cb.split("_", 3)
        product = next((p for p in CATEGORIES[cat][sub] if p["name"] == name), None)
        if product:
            user_carts.setdefault(user_id, []).append(product)
            save_data()
            await cb.message.answer(f"Товар '{name}' доданий до корзини ✅", reply_markup=main_menu())
        await cb.answer()
        return

    if data_cb == "back_main":
        await cb.message.answer("Головне меню:", reply_markup=main_menu())
        await cb.answer()
        return
        # ---------------- ADMIN FSM: Додавання фото товару ----------------
class AdminStates(StatesGroup):
    add_category = State()
    add_subcategory_category = State()
    add_subcategory_name = State()
    add_product_category = State()
    add_product_subcategory = State()
    add_product_name = State()
    add_product_price = State()
    add_product_description = State()
    add_product_photos = State()  # новий стан для фото
    add_manager = State()

@dp.message()
async def handle_admin_photos(message: types.Message, state: FSMContext):
    user_id = str(message.from_user.id)
    current_state = await state.get_state()
    text = (message.text or "").strip()

    # Скасування будь-якої дії
    if text == "❌ Відмінити":
        await state.clear()
        await message.answer("Дія скасована ✅", reply_markup=admin_menu())
        return

    # ---------------- Додавання фото товару ----------------
    if current_state == AdminStates.add_product_photos:
        if message.photo:
            data_state = await state.get_data()
            photos = data_state.get("photos", [])
            photos.append(message.photo[-1].file_id)  # беремо найбільшу якість
            if len(photos) > 10:
                await message.answer("Максимум 10 фото на товар. Останнє фото не додано.")
                photos = photos[:10]
            await state.update_data(photos=photos)
            await message.answer(f"Фото додано ✅ ({len(photos)}/10). Надішліть ще фото або напишіть 'Готово' для завершення.")
            return

        elif text.lower() == "готово":
            data_state = await state.get_data()
            cat = data_state.get("category")
            sub = data_state.get("subcategory")
            name = data_state.get("product_name")
            price = data_state.get("product_price")
            description = data_state.get("product_description")
            photos = data_state.get("photos", [])

            product = {"name": name, "price": price, "description": description, "photos": photos}

            if sub:  # якщо підкатегорія є
                CATEGORIES[cat][sub].append(product)
            else:  # якщо підкатегорії немає
                CATEGORIES[cat].setdefault("Без підкатегорії", []).append(product)

            save_data()
            await message.answer(f"Товар '{name}' доданий ✅", reply_markup=admin_menu())
            await state.clear()
            return

        else:
            await message.answer("Будь ласка, надішліть фото або напишіть 'Готово', щоб завершити.")
            return
            # ---------------- ADMIN FSM: інтеграція фото при додаванні товару ----------------
@dp.message()
async def handle_admin_message(message: types.Message, state: FSMContext):
    text = (message.text or "").strip()
    user_id = str(message.from_user.id)

    if int(user_id) != ADMIN_ID:
        return  # тільки адмін

    current_state = await state.get_state()
    load_data()

    # Скасування будь-якої дії
    if text == "❌ Відмінити":
        await state.clear()
        await message.answer("Дія скасована ✅", reply_markup=admin_menu())
        return

    # ---------------- Додавання категорії ----------------
    if current_state == AdminStates.add_category:
        if text in CATEGORIES:
            await message.answer("Категорія вже існує.")
        else:
            CATEGORIES[text] = {}
            save_data()
            await message.answer(f"Категорія '{text}' додана ✅", reply_markup=admin_menu())
        await state.clear()
        return

    # ---------------- Додавання підкатегорії ----------------
    if current_state == AdminStates.add_subcategory_name:
        data_state = await state.get_data()
        cat = data_state.get("category")
        if cat:
            CATEGORIES[cat][text] = []
            save_data()
            await message.answer(f"Підкатегорія '{text}' додана до '{cat}' ✅", reply_markup=admin_menu())
        await state.clear()
        return

    # ---------------- Додавання товару ----------------
    if current_state == AdminStates.add_product_name:
        await state.update_data(product_name=text)
        await message.answer("Введіть ціну товару (грн):")
        await state.set_state(AdminStates.add_product_price)
        return

    if current_state == AdminStates.add_product_price:
        try:
            price = float(text)
        except ValueError:
            await message.answer("Невірна ціна. Введіть число:")
            return
        await state.update_data(product_price=price)
        await message.answer("Введіть опис товару:")
        await state.set_state(AdminStates.add_product_description)
        return

    if current_state == AdminStates.add_product_description:
        await state.update_data(product_description=text)
        await message.answer(
            "Надішліть фото товару (максимум 10 шт). Можна додавати по одному фото. "
            "Коли закінчите, напишіть 'Готово'."
        )
        await state.update_data(photos=[])
        await state.set_state(AdminStates.add_product_photos)
        return

    # ---------------- Додавання фото ----------------
    if current_state == AdminStates.add_product_photos:
        if message.photo:
            data_state = await state.get_data()
            photos = data_state.get("photos", [])
            photos.append(message.photo[-1].file_id)
            if len(photos) > 10:
                photos = photos[:10]
                await message.answer("Максимум 10 фото. Останнє фото не додано.")
            await state.update_data(photos=photos)
            await message.answer(f"Фото додано ✅ ({len(photos)}/10). Надішліть ще фото або напишіть 'Готово'.")
            return
        elif text.lower() == "готово":
            data_state = await state.get_data()
            cat = data_state.get("category")
            sub = data_state.get("subcategory")
            name = data_state.get("product_name")
            price = data_state.get("product_price")
            description = data_state.get("product_description")
            photos = data_state.get("photos", [])

            product = {"name": name, "price": price, "description": description, "photos": photos}

            if sub:  # якщо підкатегорія є
                CATEGORIES[cat][sub].append(product)
            else:  # якщо підкатегорії немає
                CATEGORIES[cat].setdefault("Без підкатегорії", []).append(product)

            save_data()
            await message.answer(f"Товар '{name}' доданий ✅", reply_markup=admin_menu())
            await state.clear()
            return
        else:
            await message.answer("Будь ласка, надішліть фото або напишіть 'Готово', щоб завершити.")
            return
            # ---------------- KEYBOARDS: кнопка "Відмінити" для адміна ----------------
def admin_cancel_menu():
    return types.ReplyKeyboardMarkup(
        keyboard=[[types.KeyboardButton(text="❌ Відмінити")]],
        resize_keyboard=True
    )

# При використанні FSM для додавання категорії/підкатегорії/товару
# замість reply_markup=admin_menu() тимчасово ставимо reply_markup=admin_cancel_menu()
# Наприклад:
# await message.answer("Введіть назву категорії:", reply_markup=admin_cancel_menu())
# await message.answer("Введіть назву підкатегорії:", reply_markup=admin_cancel_menu())
# await message.answer("Введіть назву товару:", reply_markup=admin_cancel_menu())
# await message.answer("Введіть ціну товару (грн):", reply_markup=admin_cancel_menu())
# await message.answer("Введіть опис товару:", reply_markup=admin_cancel_menu())
# await message.answer("Надішліть фото товару (максимум 10 шт)...", reply_markup=admin_cancel_menu())
# ---------------- HANDLER ДЛЯ ВІДМІНИ FSM ----------------
@dp.message()
async def handle_cancel(message: types.Message, state: FSMContext):
    text = (message.text or "").strip()
    user_id = str(message.from_user.id)

    # Дія доступна тільки адміну
    if int(user_id) != ADMIN_ID:
        return

    if text == "❌ Відмінити":
        await state.clear()  # скидаємо всі поточні стани
        await message.answer("Дія скасована ✅", reply_markup=admin_menu())
        return
        # ---------------- FSM ДОБАВЛЕННЯ ТОВАРУ З ФОТО ----------------
class AdminStates(StatesGroup):
    add_category = State()
    add_subcategory_category = State()
    add_subcategory_name = State()
    add_product_category = State()
    add_product_subcategory = State()
    add_product_name = State()
    add_product_price = State()
    add_product_description = State()
    add_product_photos = State()  # новий стан для фото
    add_manager = State()


# ---------------- ДОДАВАННЯ ТОВАРУ ----------------
@dp.message()
async def handle_add_product(message: types.Message, state: FSMContext):
    user_id = str(message.from_user.id)
    text = (message.text or "").strip()

    if int(user_id) != ADMIN_ID:
        return

    data_state = await state.get_data()

    # Якщо ми на стадії введення фото
    current_state = await state.get_state()
    if current_state == AdminStates.add_product_photos:
        photos = data_state.get("product_photos", [])
        # Додаємо фото, якщо це фото
        if message.photo:
            if len(photos) < 10:
                photos.append(message.photo[-1].file_id)  # беремо найкращу якість
                await state.update_data(product_photos=photos)
                await message.answer(f"Фото додано ✅ ({len(photos)}/10)")
            else:
                await message.answer("Максимум 10 фото для одного товару.")
        elif text == "❌ Відмінити":
            await state.clear()
            await message.answer("Дія скасована ✅", reply_markup=admin_menu())
        elif text == "⬅️ Пропустити":
            await state.update_data(product_photos=photos)  # залишаємо без фото
            await finish_product_creation(message, state)
        else:
            await message.answer("Надішліть фото або натисніть ⬅️ Пропустити / ❌ Відмінити")
        return


async def finish_product_creation(message: types.Message, state: FSMContext):
    data_state = await state.get_data()
    cat = data_state.get("category")
    sub = data_state.get("subcategory")  # може бути None
    name = data_state.get("product_name")
    price = data_state.get("product_price")
    description = data_state.get("product_description")
    photos = data_state.get("product_photos", [])

    if sub:
        CATEGORIES[cat][sub].append({
            "name": name,
            "price": price,
            "description": description,
            "photos": photos
        })
    else:
        # якщо підкатегорія не вибрана, кладемо товар прямо в категорію
        CATEGORIES[cat].setdefault("_no_subcategory", []).append({
            "name": name,
            "price": price,
            "description": description,
            "photos": photos
        })

    save_data()
    await message.answer(f"Товар '{name}' додано ✅", reply_markup=admin_menu())
    await state.clear()
    # ---------------- FSM STATES ----------------
class AdminStates(StatesGroup):
    add_category = State()
    add_subcategory_category = State()
    add_subcategory_name = State()
    add_product_category = State()
    add_product_subcategory = State()
    add_product_name = State()
    add_product_price = State()
    add_product_description = State()
    add_product_photos = State()  # новий стан для фото
    add_manager = State()


# ---------------- ADMIN MENU ----------------
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


# ---------------- HANDLE ADMIN FSM ----------------
@dp.message()
async def handle_admin(message: types.Message, state: FSMContext):
    user_id = str(message.from_user.id)
    text = (message.text or "").strip()
    if int(user_id) != ADMIN_ID:
        return

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
                photos.append(message.photo[-1].file_id)
                await state.update_data(product_photos=photos)
                await message.answer(f"Фото додано ✅ ({len(photos)}/10)")
            else:
                await message.answer("Максимум 10 фото для одного товару.")
        else:
            await message.answer("Надішліть фото або натисніть ⬅️ Пропустити / ❌ Відмінити")
        return


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
    # ---------------- CALLBACKS ----------------
@dp.callback_query()
async def handle_admin_callbacks(cb: types.CallbackQuery, state: FSMContext):
    data_cb = cb.data
    user_id = str(cb.from_user.id)
    if int(user_id) != ADMIN_ID:
        await cb.answer()
        return

    load_data()

    # ---- Видалити категорію ----
    if data_cb.startswith("delcat_"):
        cat = data_cb[7:]
        if cat in CATEGORIES:
            del CATEGORIES[cat]
            save_data()
            await cb.message.answer(f"Категорія '{cat}' видалена ✅", reply_markup=admin_menu())
        await cb.answer()
        return

    # ---- Додати підкатегорію ----
    if data_cb.startswith("addsub_"):
        cat = data_cb[7:]
        await state.update_data(category=cat)
        await cb.message.answer(
            f"Введіть назву підкатегорії для '{cat}' або ❌ Відмінити:",
            reply_markup=types.ReplyKeyboardMarkup(
                keyboard=[[types.KeyboardButton("❌ Відмінити")]],
                resize_keyboard=True
            )
        )
        await state.set_state(AdminStates.add_subcategory_name)
        await cb.answer()
        return

    # ---- Видалити підкатегорію ----
    if data_cb.startswith("delsubcat_"):
        cat = data_cb[10:]
        subs = CATEGORIES.get(cat, {})
        if not subs:
            await cb.message.answer("У цій категорії немає підкатегорій.")
            await cb.answer()
            return
        kb = types.InlineKeyboardMarkup(
            inline_keyboard=[[types.InlineKeyboardButton(text=sub, callback_data=f"delsub_{cat}_{sub}")] for sub in subs]
        )
        await cb.message.answer("Оберіть підкатегорію для видалення:", reply_markup=kb)
        await cb.answer()
        return

    # ---- Додати товар ----
    if data_cb.startswith("addprod_"):
        _, cat, sub = data_cb.split("_", 2)
        await state.update_data(category=cat)
        # Якщо підкатегорія порожня, ставимо None
        await state.update_data(subcategory=sub if sub != "_no_subcategory" else None)
        await cb.message.answer(
            "Введіть назву товару або ❌ Відмінити:",
            reply_markup=types.ReplyKeyboardMarkup(
                keyboard=[[types.KeyboardButton("❌ Відмінити")]],
                resize_keyboard=True
            )
        )
        await state.set_state(AdminStates.add_product_name)
        await cb.answer()
        return