import asyncio
import json
import os
import signal
import sys
from typing import Dict, Any, List, Optional

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
        print("❌ Бот уже запущено (є lock). Видали /tmp/bot.lock або перезапусти середовище.")
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
def default_data() -> Dict[str, Any]:
    return {
        "categories": {},  # {cat: {sub: [product,...]}}
        "carts": {},       # {user_id(str): [product_id(int), ...]}
        "orders": [],      # [{id, user_id, items, total, status}]
        "managers": []     # [user_id(int), ...]
    }


def load_data() -> Dict[str, Any]:
    if not os.path.exists(DATA_FILE):
        data = default_data()
        save_data(data)
        return data

    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError:
        data = default_data()
        save_data(data)
        return data

    base = default_data()
    for k, v in base.items():
        data.setdefault(k, v)
    return data


def save_data(data: Dict[str, Any]) -> None:
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def next_product_id(data: Dict[str, Any]) -> int:
    max_id = 0
    for cat in data["categories"].values():
        for products in cat.values():
            for p in products:
                max_id = max(max_id, int(p.get("id", 0)))
    return max_id + 1


def next_order_id(data: Dict[str, Any]) -> int:
    orders = data["orders"]
    return (max([int(o.get("id", 0)) for o in orders]) + 1) if orders else 1


def find_product(data: Dict[str, Any], product_id: int) -> Optional[Dict[str, Any]]:
    for cat in data["categories"].values():
        for products in cat.values():
            for p in products:
                if int(p.get("id", 0)) == product_id:
                    return p
    return None


def cart_total(data: Dict[str, Any], cart: List[int]) -> float:
    total = 0.0
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
    waiting_payment_proof = State()


# ===================== KEYBOARDS =====================
def main_menu_kb() -> types.ReplyKeyboardMarkup:
    return types.ReplyKeyboardMarkup(
        keyboard=[
            [types.KeyboardButton(text="🛍 Каталог"), types.KeyboardButton(text="🧺 Кошик")],
            [types.KeyboardButton(text="📦 Історія замовлень"), types.KeyboardButton(text="📞 Підтримка")],
        ],
        resize_keyboard=True
    )


def admin_menu_kb() -> types.ReplyKeyboardMarkup:
    return types.ReplyKeyboardMarkup(
        keyboard=[
            [types.KeyboardButton(text="➕ Додати категорію"), types.KeyboardButton(text="➕ Додати підкатегорію")],
            [types.KeyboardButton(text="➕ Додати товар"), types.KeyboardButton(text="👤 Додати менеджера")],
            [types.KeyboardButton(text="🛍 Каталог"), types.KeyboardButton(text="🧺 Кошик")],
            [types.KeyboardButton(text="📦 Історія замовлень")]
        ],
        resize_keyboard=True
    )


def cancel_kb() -> types.ReplyKeyboardMarkup:
    return types.ReplyKeyboardMarkup(
        keyboard=[[types.KeyboardButton(text="❌ Відмінити")]],
        resize_keyboard=True
    )


def catalog_kb(categories: List[str]) -> types.InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for cat in categories:
        kb.button(text=cat, callback_data=f"user_cat:{cat}")
    kb.adjust(2)
    return kb.as_markup()


def subcats_kb(cat: str, subcats: List[str]) -> types.InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for sub in subcats:
        kb.button(text=sub, callback_data=f"user_sub:{cat}:{sub}")
    kb.adjust(2)
    return kb.as_markup()


def add_to_cart_kb(product_id: int) -> types.InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🛒 Додати в кошик", callback_data=f"addcart:{product_id}")
    kb.adjust(1)
    return kb.as_markup()


def cart_kb(total: float) -> types.InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=f"💳 Оформити ({total:.2f} ₴)", callback_data="checkout")
    kb.button(text="🗑 Очистити кошик", callback_data="cart_clear")
    kb.adjust(1)
    return kb.as_markup()


def pay_kb(order_id: int) -> types.InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="💳 Оплатити", callback_data=f"pay:{order_id}")
    kb.adjust(1)
    return kb.as_markup()


def done_kb(order_id: int) -> types.InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Оброблено", callback_data=f"done:{order_id}")
    kb.adjust(1)
    return kb.as_markup()


# ===================== HELPERS =====================
def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_ID


def is_manager(data: Dict[str, Any], user_id: int) -> bool:
    return user_id in data["managers"] or is_admin(user_id)


async def notify_managers(bot: Bot, data: Dict[str, Any], text: str, reply_markup=None):
    for mid in data["managers"]:
        try:
            await bot.send_message(mid, text, parse_mode="HTML", reply_markup=reply_markup)
        except Exception:
            pass


# ===================== BOT =====================
bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher(storage=MemoryStorage())


# ===================== COMMON =====================
@dp.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    if is_admin(message.from_user.id):
        await message.answer("👋 Привіт, адмін!", reply_markup=admin_menu_kb())
    else:
        await message.answer("👋 Ласкаво просимо!", reply_markup=main_menu_kb())


@dp.message(F.text == "📞 Підтримка")
async def support(message: types.Message):
    await message.answer("📞 Опишіть проблему/питання — менеджер відповість.")


@dp.message(F.text == "❌ Відмінити")
async def cancel(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Дію скасовано ✅", reply_markup=admin_menu_kb() if is_admin(message.from_user.id) else main_menu_kb())


# ===================== USER: CATALOG (reply button) =====================
@dp.message(F.text == "🛍 Каталог")
async def user_catalog(message: types.Message):
    data = load_data()
    if not data["categories"]:
        await message.answer("📭 Каталог порожній.")
        return
    await message.answer("Оберіть категорію:", reply_markup=catalog_kb(list(data["categories"].keys())))


@dp.callback_query(F.data.startswith("user_cat:"))
async def user_choose_cat(cb: types.CallbackQuery):
    data = load_data()
    cat = cb.data.split(":", 1)[1]
    if cat not in data["categories"]:
        await cb.answer("Категорію не знайдено", show_alert=True)
        return

    subs = list(data["categories"][cat].keys())
    if not subs:
        await cb.message.answer("У цій категорії немає підкатегорій.")
        await cb.answer()
        return

    await cb.message.answer(
        f"Категорія: <b>{cat}</b>\nОберіть підкатегорію:",
        parse_mode="HTML",
        reply_markup=subcats_kb(cat, subs)
    )
    await cb.answer()


@dp.callback_query(F.data.startswith("user_sub:"))
async def user_choose_sub(cb: types.CallbackQuery):
    data = load_data()
    _, cat, sub = cb.data.split(":", 2)
    products = data["categories"].get(cat, {}).get(sub, [])

    if not products:
        await cb.message.answer("📭 Товарів поки немає.")
        await cb.answer()
        return

    for p in products:
        text = f"📦 <b>{p['name']}</b>\n💰 {float(p['price']):.2f} ₴\n\n{p['description']}"
        if p.get("photos"):
            await cb.message.answer_photo(
                p["photos"][0],
                caption=text,
                parse_mode="HTML",
                reply_markup=add_to_cart_kb(int(p["id"]))
            )
        else:
            await cb.message.answer(text, parse_mode="HTML", reply_markup=add_to_cart_kb(int(p["id"])))

    await cb.answer()


# ===================== CART =====================
@dp.callback_query(F.data.startswith("addcart:"))
async def add_to_cart(cb: types.CallbackQuery):
    pid = int(cb.data.split(":", 1)[1])
    data = load_data()
    if not find_product(data, pid):
        await cb.answer("Товар не знайдено", show_alert=True)
        return

    uid = str(cb.from_user.id)
    data["carts"].setdefault(uid, [])
    data["carts"][uid].append(pid)
    save_data(data)

    await cb.message.answer("✅ Додано в кошик")
    await cb.answer()


@dp.message(F.text == "🧺 Кошик")
async def open_cart(message: types.Message):
    data = load_data()
    uid = str(message.from_user.id)
    cart = data["carts"].get(uid, [])
    if not cart:
        await message.answer("🧺 Ваш кошик порожній.")
        return

    total = cart_total(data, cart)
    lines = []
    for pid in cart:
        p = find_product(data, pid)
        if p:
            lines.append(f"• {p['name']} — {float(p['price']):.2f} ₴")

    text = "🧺 <b>Ваш кошик</b>\n\n" + "\n".join(lines) + f"\n\n💰 <b>Разом:</b> {total:.2f} ₴"
    await message.answer(text, parse_mode="HTML", reply_markup=cart_kb(total))


@dp.callback_query(F.data == "cart_clear")
async def cart_clear(cb: types.CallbackQuery):
    data = load_data()
    uid = str(cb.from_user.id)
    data["carts"][uid] = []
    save_data(data)
    await cb.message.answer("🗑 Кошик очищено")
    await cb.answer()


# ===================== CHECKOUT =====================
@dp.callback_query(F.data == "checkout")
async def checkout(cb: types.CallbackQuery):
    data = load_data()
    uid_str = str(cb.from_user.id)
    cart = data["carts"].get(uid_str, [])
    if not cart:
        await cb.message.answer("🧺 Кошик порожній.")
        await cb.answer()
        return

    total = cart_total(data, cart)
    oid = next_order_id(data)
    order = {"id": oid, "user_id": cb.from_user.id, "items": cart[:], "total": total, "status": "new"}
    data["orders"].append(order)
    data["carts"][uid_str] = []
    save_data(data)

    await cb.message.answer(
        f"✅ <b>Замовлення створено</b>\n\n🆔 <b>{oid}</b>\n💰 <b>{total:.2f} ₴</b>\n\nНатисніть «Оплатити» і надішліть підтвердження.",
        parse_mode="HTML",
        reply_markup=pay_kb(oid)
    )

    user = cb.from_user
    mgr_text = (
        "🛒 <b>Нове замовлення</b>\n\n"
        f"🆔 Order: <b>{oid}</b>\n"
        f"👤 User: @{user.username or 'без username'}\n"
        f"🧾 ID: <code>{user.id}</code>\n"
        f"💰 <b>Разом:</b> {total:.2f} ₴\n"
        "Статус: <b>new</b>"
    )
    await notify_managers(cb.bot, data, mgr_text, reply_markup=done_kb(oid))

    await cb.answer()


# ===================== HISTORY =====================
@dp.message(F.text == "📦 Історія замовлень")
async def order_history(message: types.Message):
    data = load_data()
    uid = message.from_user.id
    orders = [o for o in data["orders"] if int(o["user_id"]) == uid]
    if not orders:
        await message.answer("📦 У вас ще немає замовлень.")
        return

    for o in orders:
        txt = (
            "🧾 <b>Замовлення</b>\n\n"
            f"🆔 <b>{o['id']}</b>\n"
            f"💰 <b>Разом:</b> {float(o['total']):.2f} ₴\n"
            f"📌 Статус: <b>{o['status']}</b>"
        )
        if o["status"] == "new":
            await message.answer(txt, parse_mode="HTML", reply_markup=pay_kb(int(o["id"])))
        else:
            await message.answer(txt, parse_mode="HTML")


# ===================== PAYMENT =====================
@dp.callback_query(F.data.startswith("pay:"))
async def pay_start(cb: types.CallbackQuery, state: FSMContext):
    order_id = int(cb.data.split(":", 1)[1])
    data = load_data()
    order = next((o for o in data["orders"] if int(o["id"]) == order_id), None)
    if not order or int(order["user_id"]) != cb.from_user.id:
        await cb.answer("Замовлення не знайдено", show_alert=True)
        return
    if order["status"] != "new":
        await cb.answer("Вже оплачено/в обробці", show_alert=True)
        return

    await state.set_state(PaymentStates.waiting_payment_proof)
    await state.update_data(order_id=order_id)
    await cb.message.answer("💳 Надішліть підтвердження оплати (текст або скрін) або ❌ Відмінити:", reply_markup=cancel_kb())
    await cb.answer()


@dp.message(PaymentStates.waiting_payment_proof)
async def pay_confirm(message: types.Message, state: FSMContext):
    st = await state.get_data()
    order_id = int(st["order_id"])
    data = load_data()

    order = next((o for o in data["orders"] if int(o["id"]) == order_id), None)
    if not order:
        await state.clear()
        await message.answer("❌ Замовлення не знайдено.")
        return

    order["status"] = "paid"
    save_data(data)

    await message.answer("✅ Оплату прийнято! Менеджер скоро з вами звʼяжеться.", reply_markup=main_menu_kb())

    user = message.from_user
    mgr_text = (
        "✅ <b>Оплата підтверджена</b>\n\n"
        f"🆔 Order: <b>{order_id}</b>\n"
        f"👤 User: @{user.username or 'без username'}\n"
        f"🧾 ID: <code>{user.id}</code>\n"
        f"💰 <b>{float(order['total']):.2f} ₴</b>\n"
        "Статус: <b>paid</b>"
    )
    await notify_managers(message.bot, data, mgr_text, reply_markup=done_kb(order_id))

    await state.clear()


# ===================== MANAGER DONE =====================
@dp.callback_query(F.data.startswith("done:"))
async def mark_done(cb: types.CallbackQuery):
    data = load_data()
    if not is_manager(data, cb.from_user.id):
        await cb.answer("⛔️ Тільки менеджер/адмін", show_alert=True)
        return

    order_id = int(cb.data.split(":", 1)[1])
    order = next((o for o in data["orders"] if int(o["id"]) == order_id), None)
    if not order:
        await cb.answer("Не знайдено", show_alert=True)
        return

    order["status"] = "completed"
    save_data(data)

    await cb.message.answer(f"✅ Замовлення {order_id} позначено як виконане")
    await cb.answer()


# ===================== ADMIN: ADD PRODUCT (полный сценарий) =====================
@dp.message(F.text == "➕ Додати товар")
async def add_product_start(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    data = load_data()
    if not data["categories"]:
        await message.answer("⚠️ Спочатку додайте категорії/підкатегорії.", reply_markup=admin_menu_kb())
        return

    kb = types.ReplyKeyboardMarkup(
        keyboard=[[types.KeyboardButton(text=c)] for c in data["categories"].keys()] +
                 [[types.KeyboardButton(text="❌ Відмінити")]],
        resize_keyboard=True
    )
    await state.set_state(AdminStates.add_product_category)
    await message.answer("📂 Оберіть категорію товару:", reply_markup=kb)


@dp.message(AdminStates.add_product_category)
async def add_product_choose_cat(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    cat = (message.text or "").strip()
    data = load_data()
    if cat not in data["categories"]:
        await message.answer("⚠️ Оберіть категорію з кнопок.")
        return
    if not data["categories"][cat]:
        await message.answer("⚠️ У цій категорії немає підкатегорій. Додайте підкатегорію.")
        return

    kb = types.ReplyKeyboardMarkup(
        keyboard=[[types.KeyboardButton(text=s)] for s in data["categories"][cat].keys()] +
                 [[types.KeyboardButton(text="❌ Відмінити")]],
        resize_keyboard=True
    )
    await state.update_data(category=cat)
    await state.set_state(AdminStates.add_product_subcategory)
    await message.answer("📁 Оберіть підкатегорію:", reply_markup=kb)


@dp.message(AdminStates.add_product_subcategory)
async def add_product_choose_sub(message: types.Message, state: FSMContext):
    sub = (message.text or "").strip()
    st = await state.get_data()
    cat = st["category"]
    data = load_data()

    if sub not in data["categories"][cat]:
        await message.answer("⚠️ Оберіть підкатегорію з кнопок.")
        return

    await state.update_data(subcategory=sub)
    await state.set_state(AdminStates.add_product_name)
    await message.answer("✍️ Введіть назву товару:", reply_markup=cancel_kb())


@dp.message(AdminStates.add_product_name)
async def add_product_name(message: types.Message, state: FSMContext):
    name = (message.text or "").strip()
    if len(name) < 2:
        await message.answer("⚠️ Назва занадто коротка.")
        return
    await state.update_data(name=name)
    await state.set_state(AdminStates.add_product_price)
    await message.answer("💰 Введіть ціну (число):", reply_markup=cancel_kb())


@dp.message(AdminStates.add_product_price)
async def add_product_price(message: types.Message, state: FSMContext):
    txt = (message.text or "").replace(",", ".").strip()
    try:
        price = float(txt)
    except ValueError:
        await message.answer("⚠️ Невірна ціна. Введіть число.")
        return

    await state.update_data(price=price)
    await state.set_state(AdminStates.add_product_description)
    await message.answer("📝 Введіть опис:", reply_markup=cancel_kb())


@dp.message(AdminStates.add_product_description)
async def add_product_description(message: types.Message, state: FSMContext):
    desc = (message.text or "").strip()
    await state.update_data(description=desc, photos=[])
    await state.set_state(AdminStates.add_product_photos)

    kb = types.ReplyKeyboardMarkup(
        keyboard=[[types.KeyboardButton(text="✅ Готово")], [types.KeyboardButton(text="❌ Відмінити")]],
        resize_keyboard=True
    )
    await message.answer("🖼 Надішліть фото (до 10). Коли завершите — натисніть ✅ Готово", reply_markup=kb)


@dp.message(AdminStates.add_product_photos, F.photo)
async def add_product_photos(message: types.Message, state: FSMContext):
    st = await state.get_data()
    photos = st.get("photos", [])
    if len(photos) >= 10:
        await message.answer("⚠️ Максимум 10 фото.")
        return

    photos.append(message.photo[-1].file_id)
    await state.update_data(photos=photos)
    await message.answer(f"✅ Фото додано ({len(photos)}/10)")


@dp.message(AdminStates.add_product_photos, F.text == "✅ Готово")
async def add_product_finish(message: types.Message, state: FSMContext):
    st = await state.get_data()
    data = load_data()

    pid = next_product_id(data)
    product = {
        "id": pid,
        "name": st["name"],
        "price": float(st["price"]),
        "description": st["description"],
        "photos": st.get("photos", [])
    }

    cat = st["category"]
    sub = st["subcategory"]
    data["categories"][cat][sub].append(product)
    save_data(data)

    await state.clear()
    await message.answer(f"✅ Товар «{product['name']}» додано", reply_markup=admin_menu_kb())


# ===================== RUN =====================
async def main():
    create_lock()
    setup_signals()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())