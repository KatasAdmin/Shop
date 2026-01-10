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

def admin_cancel_menu():
    return types.ReplyKeyboardMarkup(
        keyboard=[[types.KeyboardButton(text="❌ Відмінити")]],
        resize_keyboard=True
    )
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

        # --- Додавання товару: назва ---
        elif current_state == AdminStates.add_product_name:
            await state.update_data(product_name=text)
            await message.answer("Введіть ціну товару (число, грн):", reply_markup=admin_cancel_menu())
            await state.set_state(AdminStates.add_product_price)
            return

        # --- Додавання товару: ціна ---
        elif current_state == AdminStates.add_product_price:
            try:
                price = float(text.replace("грн", "").replace("₴", "").strip())
            except ValueError:
                await message.answer("Невірна ціна. Введіть число:", reply_markup=admin_cancel_menu())
                return
            await state.update_data(product_price=price)
            await message.answer("Введіть опис товару:", reply_markup=admin_cancel_menu())
            await state.set_state(AdminStates.add_product_description)
            return

        # --- Додавання товару: опис ---
        elif current_state == AdminStates.add_product_description:
            await state.update_data(product_description=text)
            await message.answer(
                "Надішліть фото товару (максимум 10 шт). Можна додавати по одному фото. "
                "Коли закінчите, напишіть 'Готово'.", reply_markup=admin_cancel_menu()
            )
            await state.update_data(product_photos=[])
            await state.set_state(AdminStates.add_product_photos)
            return

        # --- Додавання товару: фото ---
        elif current_state == AdminStates.add_product_photos:
            data_state = await state.get_data()
            photos = data_state.get("product_photos", [])

            if message.photo:
                if len(photos) < 10:
                    photos.append(message.photo[-1].file_id)  # беремо найкращу якість
                    await state.update_data(product_photos=photos)
                    await message.answer(f"Фото додано ✅ ({len(photos)}/10)", reply_markup=admin_cancel_menu())
                else:
                    await message.answer("Максимум 10 фото для одного товару.", reply_markup=admin_cancel_menu())
                return
            elif text.lower() == "готово":
                await finish_product_creation(message, state)
                return
            else:
                await message.answer("Будь ласка, надішліть фото або напишіть 'Готово' для завершення.", reply_markup=admin_cancel_menu())
                return
                # ------------------- CALLBACK QUERY -------------------
@dp.callback_query()
async def handle_callbacks(cb: types.CallbackQuery, state: FSMContext):
    data_cb = cb.data
    user_id = str(cb.from_user.id)
    load_data()

    # ---------------- АДМІН: Видалення категорії ----------------
    if data_cb.startswith("delcat_") and int(user_id) == ADMIN_ID:
        cat = data_cb[7:]
        if cat in CATEGORIES:
            del CATEGORIES[cat]
            save_data()
            await cb.message.answer(f"Категорія '{cat}' видалена ✅", reply_markup=admin_menu())
        await cb.answer()
        return

    # ---------------- АДМІН: Додавання підкатегорії ----------------
    if data_cb.startswith("addsub_") and int(user_id) == ADMIN_ID:
        cat = data_cb[7:]
        await state.update_data(category=cat)
        await cb.message.answer(f"Введіть назву підкатегорії для '{cat}' або ❌ Відмінити:", reply_markup=admin_cancel_menu())
        await state.set_state(AdminStates.add_subcategory_name)
        await cb.answer()
        return

    # ---------------- АДМІН: Видалення підкатегорії ----------------
    if data_cb.startswith("delsubcat_") and int(user_id) == ADMIN_ID:
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

    if data_cb.startswith("delsub_") and int(user_id) == ADMIN_ID:
        _, cat, sub = data_cb.split("_", 2)
        if sub in CATEGORIES.get(cat, {}):
            del CATEGORIES[cat][sub]
            save_data()
            await cb.message.answer(f"Підкатегорія '{sub}' видалена з '{cat}' ✅", reply_markup=admin_menu())
        await cb.answer()
        return

    # ---------------- АДМІН: Додавання товару ----------------
    if data_cb.startswith("addprod_") and int(user_id) == ADMIN_ID:
        _, cat, sub = data_cb.split("_", 2)
        await state.update_data(category=cat)
        await state.update_data(subcategory=sub if sub != "_no_subcategory" else None)
        await cb.message.answer("Введіть назву товару або ❌ Відмінити:", reply_markup=admin_cancel_menu())
        await state.set_state(AdminStates.add_product_name)
        await cb.answer()
        return

    # ---------------- Користувацький каталог ----------------
    if data_cb.startswith("cat_"):
        cat = data_cb[4:]
        subs = CATEGORIES.get(cat, {})
        if not subs:
            await cb.message.answer("У цій категорії поки немає підкатегорій.", reply_markup=main_menu())
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
                await cb.message.answer(f"{p['name']}\nЦіна: {p['price']}₴\n{p['description']}", reply_markup=kb)
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
        # ------------------- ПРИЗНАЧЕННЯ МЕНЕДЖЕРА -------------------
@dp.message()
async def handle_assign_manager(message: types.Message, state: FSMContext):
    user_id = str(message.from_user.id)
    text = (message.text or "").strip()
    load_data()

    if int(user_id) != ADMIN_ID:
        return

    current_state = await state.get_state()

    # Призначення менеджера
    if text.startswith("➕ Призначити менеджера"):
        await message.answer("Введіть Telegram ID менеджера або ❌ Відмінити:", reply_markup=admin_cancel_menu())
        await state.set_state(AdminStates.add_manager)
        return

    if current_state == AdminStates.add_manager:
        if text == "❌ Відмінити":
            await state.clear()
            await message.answer("Дія скасована ✅", reply_markup=admin_menu())
            return
        try:
            manager_id = int(text)
        except ValueError:
            await message.answer("Невірний ID. Введіть число:")
            return
        if manager_id not in managers:
            managers.append(manager_id)
            save_data()
        await message.answer(f"Менеджер з ID {manager_id} призначений ✅", reply_markup=admin_menu())
        await state.clear()
        return

# ------------------- СПОВІЩЕННЯ ПРО ЗАМОВЛЕННЯ -------------------
async def notify_managers_order(user_id: str, cart_items: list):
    # повідомлення для менеджерів
    for manager_id in managers:
        msg = f"🛒 Нове замовлення від користувача {user_id}:\n"
        for item in cart_items:
            msg += f"- {item['name']} ({item['price']}₴)\n"
        await bot.send_message(manager_id, msg)

# ------------------- ОФОРМЛЕННЯ ЗАМОВЛЕННЯ -------------------
@dp.message()
async def handle_checkout(message: types.Message, state: FSMContext):
    user_id = str(message.from_user.id)
    load_data()

    if text := (message.text or "").strip():
        if text == "🧺 Кошик":
            cart = user_carts.get(user_id, [])
            if not cart:
                await message.answer("Ваш кошик порожній 🛒", reply_markup=main_menu())
                return
            msg = "Ваш кошик:\n"
            for item in cart:
                msg += f"- {item['name']} ({item['price']}₴)\n"
            msg += "\nНатисніть ✅ Оплатити"
            kb = types.ReplyKeyboardMarkup(
                keyboard=[[types.KeyboardButton(text="✅ Оплатити")], [types.KeyboardButton(text="⬅️ Головне меню")]],
                resize_keyboard=True
            )
            await message.answer(msg, reply_markup=kb)
            return

        if text == "✅ Оплатити":
            cart = user_carts.get(user_id, [])
            if not cart:
                await message.answer("Ваш кошик порожній 🛒", reply_markup=main_menu())
                return

            # Тут можна інтегрувати платіжну систему
            await message.answer("Оплата пройшла успішно ✅", reply_markup=main_menu())
            
            # Сповіщення менеджерам
            await notify_managers_order(user_id, cart)

            # Очищення кошика користувача
            user_carts[user_id] = []
            save_data()
            return

        if text == "⬅️ Головне меню":
            await message.answer("Головне меню:", reply_markup=main_menu())
            return
            # ------------------- ЗАПУСК БОТА -------------------
async def main():
    try:
        print("🚀 Бот запущено...")
        await dp.start_polling(bot)
    finally:
        # Очистка lock при завершенні
        if os.path.exists(LOCK_FILE):
            os.remove(LOCK_FILE)
        await bot.session.close()
        print("❌ Бот зупинено, lock очищено.")

# ------------------- ENTRY POINT -------------------
if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        if os.path.exists(LOCK_FILE):
            os.remove(LOCK_FILE)
        print("❌ Бот вимкнено вручну")