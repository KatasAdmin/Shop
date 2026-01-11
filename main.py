import asyncio
import json
import os
import signal
import sys
from typing import Dict, Any, List, Optional

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart, Command
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder

# ===================== CONFIG =====================
TELEGRAM_TOKEN = "PASTE_YOUR_TOKEN_HERE"  # ⬅️ ВСТАВЬ СВОЙ ТОКЕН ЛОКАЛЬНО
ADMIN_ID = 8385663990

DATA_FILE = "data.json"
LOCK_FILE = "/tmp/bot.lock"

PAYMENT_SIMULATION = True  # пока оплата считается успешной сразу

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
def default_data() -> Dict[str, Any]:
    return {
        "categories": {},   # {cat: {sub: [product]}}
        "carts": {},        # {user_id: [product_id]}
        "orders": [],       # [{id, user_id, items, total, status}]
        "managers": []      # [user_id]
    }

def save_data(data: Dict[str, Any]):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_data() -> Dict[str, Any]:
    if not os.path.exists(DATA_FILE):
        data = default_data()
        save_data(data)
        return data
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        data = default_data()
        save_data(data)
        return data

    base = default_data()
    for k, v in base.items():
        data.setdefault(k, v)
    if "history" in data:
        del data["history"]
        save_data(data)
    return data

def next_product_id(data: Dict[str, Any]) -> int:
    mx = 0
    for cat in data["categories"].values():
        for sub in cat.values():
            for p in sub:
                mx = max(mx, int(p["id"]))
    return mx + 1

def next_order_id(data: Dict[str, Any]) -> int:
    return max([o["id"] for o in data["orders"]], default=0) + 1

def find_product(data: Dict[str, Any], pid: int) -> Optional[Dict[str, Any]]:
    for cat in data["categories"].values():
        for sub in cat.values():
            for p in sub:
                if p["id"] == pid:
                    return p
    return None

def cart_total(data: Dict[str, Any], cart: List[int]) -> float:
    total = 0.0
    for pid in cart:
        p = find_product(data, pid)
        if p:
            total += float(p["price"])
    return total

# ===================== ROLES =====================
def is_admin(uid: int) -> bool:
    return uid == ADMIN_ID

def is_manager(data: Dict[str, Any], uid: int) -> bool:
    return uid in data["managers"] or is_admin(uid)

# ===================== KEYBOARDS =====================
def main_menu():
    return types.ReplyKeyboardMarkup(
        keyboard=[
            ["🛍 Каталог", "🧺 Кошик"],
            ["📦 Історія замовлень"]
        ],
        resize_keyboard=True
    )

def admin_menu():
    return types.ReplyKeyboardMarkup(
        keyboard=[
            ["➕ Додати категорію", "➕ Додати підкатегорію"],
            ["➕ Додати товар", "👤 Додати менеджера"],
            ["📋 Менеджер-панель"]
        ],
        resize_keyboard=True
    )

def manager_menu():
    return types.ReplyKeyboardMarkup(
        keyboard=[
            ["📋 Нові/оплачені замовлення"],
            ["📦 Усі замовлення"]
        ],
        resize_keyboard=True
    )

def catalog_kb(cats: List[str]):
    kb = InlineKeyboardBuilder()
    for c in cats:
        kb.button(text=c, callback_data=f"cat:{c}")
    kb.adjust(2)
    return kb.as_markup()

def subcat_kb(cat: str, subs: List[str]):
    kb = InlineKeyboardBuilder()
    for s in subs:
        kb.button(text=s, callback_data=f"sub:{cat}:{s}")
    kb.adjust(2)
    return kb.as_markup()

def add_cart_kb(pid: int):
    kb = InlineKeyboardBuilder()
    kb.button(text="🛒 В кошик", callback_data=f"add:{pid}")
    return kb.as_markup()

def cart_kb(total: float):
    kb = InlineKeyboardBuilder()
    kb.button(text=f"💳 Оформити ({total:.2f} ₴)", callback_data="checkout")
    kb.button(text="🗑 Очистити", callback_data="clear")
    return kb.as_markup()

def pay_kb(oid: int):
    kb = InlineKeyboardBuilder()
    kb.button(text="💳 Оплатити", callback_data=f"pay:{oid}")
    return kb.as_markup()

def done_kb(oid: int):
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Виконано", callback_data=f"done:{oid}")
    return kb.as_markup()

# ===================== BOT =====================
bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ===================== START / PANELS =====================
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
    await m.answer("👔 Менеджер-панель", reply_markup=manager_menu())

# ===================== CATALOG =====================
@dp.message(F.text == "🛍 Каталог")
async def catalog(m: types.Message):
    d = load_data()
    if not d["categories"]:
        return await m.answer("Каталог порожній")
    await m.answer("Оберіть категорію:", reply_markup=catalog_kb(list(d["categories"].keys())))

@dp.callback_query(F.data.startswith("cat:"))
async def choose_cat(cb: types.CallbackQuery):
    d = load_data()
    cat = cb.data.split(":", 1)[1]
    await cb.message.answer(
        f"<b>{cat}</b>",
        parse_mode="HTML",
        reply_markup=subcat_kb(cat, list(d["categories"][cat].keys()))
    )
    await cb.answer()

@dp.callback_query(F.data.startswith("sub:"))
async def choose_sub(cb: types.CallbackQuery):
    d = load_data()
    _, cat, sub = cb.data.split(":", 2)
    for p in d["categories"][cat][sub]:
        text = f"<b>{p['name']}</b>\n💰 {p['price']} ₴\n\n{p['description']}"
        if p.get("photos"):
            await cb.message.answer_photo(
                p["photos"][0],
                caption=text,
                parse_mode="HTML",
                reply_markup=add_cart_kb(p["id"])
            )
        else:
            await cb.message.answer(text, parse_mode="HTML")
    await cb.answer()

# ===================== CART =====================
@dp.callback_query(F.data.startswith("add:"))
async def add_cart(cb: types.CallbackQuery):
    d = load_data()
    uid = str(cb.from_user.id)
    pid = int(cb.data.split(":", 1)[1])
    d["carts"].setdefault(uid, []).append(pid)
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
    names = [find_product(d, pid)["name"] for pid in cart if find_product(d, pid)]
    await m.answer(
        "🧺 Кошик:\n" + "\n".join(names) + f"\n\nРазом: {total:.2f} ₴",
        reply_markup=cart_kb(total)
    )

@dp.callback_query(F.data == "clear")
async def clear_cart(cb: types.CallbackQuery):
    d = load_data()
    d["carts"][str(cb.from_user.id)] = []
    save_data(d)
    await cb.answer("Очищено")

# ===================== ORDER / PAYMENT =====================
@dp.callback_query(F.data == "checkout")
async def checkout(cb: types.CallbackQuery):
    d = load_data()
    uid = str(cb.from_user.id)
    cart = d["carts"].get(uid, [])
    if not cart:
        return await cb.answer("Кошик порожній")
    total = cart_total(d, cart)
    oid = next_order_id(d)
    d["orders"].append({
        "id": oid,
        "user_id": cb.from_user.id,
        "items": cart,
        "total": total,
        "status": "new"
    })
    d["carts"][uid] = []
    save_data(d)
    await cb.message.answer(
        f"Замовлення #{oid}\nСума: {total:.2f} ₴",
        reply_markup=pay_kb(oid)
    )
    await cb.answer()

@dp.callback_query(F.data.startswith("pay:"))
async def pay(cb: types.CallbackQuery):
    d = load_data()
    oid = int(cb.data.split(":", 1)[1])
    for o in d["orders"]:
        if o["id"] == oid:
            o["status"] = "paid"
    save_data(d)
    await cb.message.answer("✅ Оплачено (симуляція)")
    await cb.answer()

# ===================== MANAGER =====================
@dp.message(F.text == "📋 Нові/оплачені замовлення")
async def mgr_new(m: types.Message):
    d = load_data()
    for o in d["orders"]:
        if o["status"] in ("new", "paid"):
            await m.answer(
                f"#{o['id']} | {o['status']} | {o['total']} ₴",
                reply_markup=done_kb(o["id"])
            )

@dp.callback_query(F.data.startswith("done:"))
async def done(cb: types.CallbackQuery):
    d = load_data()
    oid = int(cb.data.split(":", 1)[1])
    for o in d["orders"]:
        if o["id"] == oid:
            o["status"] = "completed"
    save_data(d)
    await cb.answer("Готово")

# ===================== RUN =====================
async def main():
    create_lock()
    setup_signals()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
    # ===================== ADMIN FSM =====================
class AdminFSM(StatesGroup):
    add_category = State()

    add_subcat_cat = State()
    add_subcat_name = State()

    add_product_cat = State()
    add_product_sub = State()
    add_product_name = State()
    add_product_price = State()
    add_product_desc = State()
    add_product_photos = State()

    add_manager = State()


def cancel_kb():
    return types.ReplyKeyboardMarkup(
        keyboard=[["❌ Скасувати"]],
        resize_keyboard=True
    )


# ===================== ADMIN: ADD CATEGORY =====================
@dp.message(F.text == "➕ Додати категорію")
async def admin_add_cat_start(m: types.Message, state: FSMContext):
    if not is_admin(m.from_user.id):
        return
    await state.set_state(AdminFSM.add_category)
    await m.answer("✍️ Введи назву категорії:", reply_markup=cancel_kb())


@dp.message(AdminFSM.add_category)
async def admin_add_cat_save(m: types.Message, state: FSMContext):
    name = m.text.strip()
    if len(name) < 2:
        return await m.answer("⚠️ Назва занадто коротка")

    d = load_data()
    if name in d["categories"]:
        return await m.answer("⚠️ Така категорія вже є")

    d["categories"][name] = {}
    save_data(d)

    await state.clear()
    await m.answer(f"✅ Категорію «{name}» додано", reply_markup=admin_menu())


# ===================== ADMIN: ADD SUBCATEGORY =====================
@dp.message(F.text == "➕ Додати підкатегорію")
async def admin_add_subcat_start(m: types.Message, state: FSMContext):
    if not is_admin(m.from_user.id):
        return

    d = load_data()
    if not d["categories"]:
        return await m.answer("⚠️ Спочатку додай категорію")

    kb = types.ReplyKeyboardMarkup(
        keyboard=[[c] for c in d["categories"].keys()],
        resize_keyboard=True
    )
    await state.set_state(AdminFSM.add_subcat_cat)
    await m.answer("📂 Обери категорію:", reply_markup=kb)


@dp.message(AdminFSM.add_subcat_cat)
async def admin_add_subcat_choose(m: types.Message, state: FSMContext):
    cat = m.text.strip()
    d = load_data()
    if cat not in d["categories"]:
        return await m.answer("⚠️ Обери категорію з кнопок")

    await state.update_data(cat=cat)
    await state.set_state(AdminFSM.add_subcat_name)
    await m.answer("✍️ Введи назву підкатегорії:", reply_markup=cancel_kb())


@dp.message(AdminFSM.add_subcat_name)
async def admin_add_subcat_save(m: types.Message, state: FSMContext):
    sub = m.text.strip()
    if len(sub) < 2:
        return await m.answer("⚠️ Назва занадто коротка")

    st = await state.get_data()
    d = load_data()
    d["categories"][st["cat"]][sub] = []
    save_data(d)

    await state.clear()
    await m.answer("✅ Підкатегорію додано", reply_markup=admin_menu())


# ===================== ADMIN: ADD MANAGER =====================
@dp.message(F.text == "👤 Додати менеджера")
async def admin_add_manager_start(m: types.Message, state: FSMContext):
    if not is_admin(m.from_user.id):
        return
    await state.set_state(AdminFSM.add_manager)
    await m.answer("✍️ Введи ID менеджера:", reply_markup=cancel_kb())


@dp.message(AdminFSM.add_manager)
async def admin_add_manager_save(m: types.Message, state: FSMContext):
    if not m.text.isdigit():
        return await m.answer("⚠️ Потрібно число (ID)")

    mid = int(m.text)
    d = load_data()
    if mid not in d["managers"]:
        d["managers"].append(mid)
        save_data(d)

    await state.clear()
    await m.answer(f"✅ Менеджера {mid} додано", reply_markup=admin_menu())


# ===================== ADMIN: ADD PRODUCT =====================
@dp.message(F.text == "➕ Додати товар")
async def admin_add_product_start(m: types.Message, state: FSMContext):
    if not is_admin(m.from_user.id):
        return

    d = load_data()
    kb = types.ReplyKeyboardMarkup(
        keyboard=[[c] for c in d["categories"].keys()],
        resize_keyboard=True
    )
    await state.set_state(AdminFSM.add_product_cat)
    await m.answer("📂 Обери категорію:", reply_markup=kb)


@dp.message(AdminFSM.add_product_cat)
async def admin_add_product_cat(m: types.Message, state: FSMContext):
    await state.update_data(cat=m.text)
    d = load_data()
    kb = types.ReplyKeyboardMarkup(
        keyboard=[[s] for s in d["categories"][m.text].keys()],
        resize_keyboard=True
    )
    await state.set_state(AdminFSM.add_product_sub)
    await m.answer("📁 Обери підкатегорію:", reply_markup=kb)


@dp.message(AdminFSM.add_product_sub)
async def admin_add_product_sub(m: types.Message, state: FSMContext):
    await state.update_data(sub=m.text)
    await state.set_state(AdminFSM.add_product_name)
    await m.answer("✍️ Назва товару:", reply_markup=cancel_kb())


@dp.message(AdminFSM.add_product_name)
async def admin_add_product_name(m: types.Message, state: FSMContext):
    await state.update_data(name=m.text)
    await state.set_state(AdminFSM.add_product_price)
    await m.answer("💰 Ціна:", reply_markup=cancel_kb())


@dp.message(AdminFSM.add_product_price)
async def admin_add_product_price(m: types.Message, state: FSMContext):
    price = float(m.text.replace(",", "."))
    await state.update_data(price=price)
    await state.set_state(AdminFSM.add_product_desc)
    await m.answer("📝 Опис:", reply_markup=cancel_kb())


@dp.message(AdminFSM.add_product_desc)
async def admin_add_product_desc(m: types.Message, state: FSMContext):
    await state.update_data(desc=m.text, photos=[])
    await state.set_state(AdminFSM.add_product_photos)
    await m.answer("📸 Надсилай фото (можна кілька). Напиши ГОТОВО", reply_markup=cancel_kb())


@dp.message(AdminFSM.add_product_photos, F.photo)
async def admin_add_product_photo(m: types.Message, state: FSMContext):
    st = await state.get_data()
    st["photos"].append(m.photo[-1].file_id)
    await state.update_data(photos=st["photos"])
    await m.answer(f"📸 Фото додано ({len(st['photos'])})")


@dp.message(AdminFSM.add_product_photos, F.text == "ГОТОВО")
async def admin_add_product_finish(m: types.Message, state: FSMContext):
    st = await state.get_data()
    d = load_data()

    pid = next_product_id(d)
    product = {
        "id": pid,
        "name": st["name"],
        "price": st["price"],
        "description": st["desc"],
        "photos": st["photos"]
    }

    d["categories"][st["cat"]][st["sub"]].append(product)
    save_data(d)

    await state.clear()
    await m.answer("✅ Товар додано", reply_markup=admin_menu())
    # ===================== HELPERS =====================
async def notify_managers(bot: Bot, text: str, reply_markup=None):
    data = load_data()
    for mid in data["managers"]:
        try:
            await bot.send_message(mid, text, parse_mode="HTML", reply_markup=reply_markup)
        except Exception:
            pass


async def safe_send(bot: Bot, chat_id: int, text: str):
    try:
        await bot.send_message(chat_id, text, parse_mode="HTML")
    except Exception:
        pass


def format_order(order: Dict[str, Any]) -> str:
    return (
        "🧾 <b>Замовлення</b>\n\n"
        f"🆔 <b>{order['id']}</b>\n"
        f"👤 User ID: <code>{order['user_id']}</code>\n"
        f"💰 <b>{order['total']:.2f} ₴</b>\n"
        f"📌 Статус: <b>{order['status']}</b>"
    )


# ===================== OVERRIDE ORDER / PAYMENT =====================
@dp.callback_query(F.data == "checkout")
async def checkout(cb: types.CallbackQuery):
    d = load_data()
    uid = str(cb.from_user.id)
    cart = d["carts"].get(uid, [])
    if not cart:
        return await cb.answer("Кошик порожній")

    total = cart_total(d, cart)
    oid = next_order_id(d)

    order = {
        "id": oid,
        "user_id": cb.from_user.id,
        "items": cart[:],
        "total": total,
        "status": "new"
    }

    d["orders"].append(order)
    d["carts"][uid] = []
    save_data(d)

    await cb.message.answer(
        f"✅ Замовлення <b>#{oid}</b> створено\n"
        f"💰 Сума: <b>{total:.2f} ₴</b>",
        parse_mode="HTML",
        reply_markup=pay_kb(oid)
    )

    await notify_managers(
        cb.bot,
        "🛒 <b>Нове замовлення</b>\n\n" + format_order(order),
        reply_markup=done_kb(oid)
    )
    await cb.answer()


@dp.callback_query(F.data.startswith("pay:"))
async def pay(cb: types.CallbackQuery):
    d = load_data()
    oid = int(cb.data.split(":", 1)[1])

    order = next((o for o in d["orders"] if o["id"] == oid), None)
    if not order:
        return await cb.answer("Замовлення не знайдено", show_alert=True)

    if order["status"] != "new":
        return await cb.answer("Вже оброблено", show_alert=True)

    order["status"] = "paid"
    save_data(d)

    await cb.message.answer("✅ <b>Оплата прийнята</b>", parse_mode="HTML")

    await notify_managers(
        cb.bot,
        "💳 <b>Оплачено</b>\n\n" + format_order(order),
        reply_markup=done_kb(oid)
    )
    await cb.answer()


# ===================== MANAGER: COMPLETE ORDER =====================
@dp.callback_query(F.data.startswith("done:"))
async def mark_done(cb: types.CallbackQuery):
    d = load_data()
    oid = int(cb.data.split(":", 1)[1])

    order = next((o for o in d["orders"] if o["id"] == oid), None)
    if not order:
        return await cb.answer("Не знайдено", show_alert=True)

    order["status"] = "completed"
    save_data(d)

    await cb.message.answer(f"✅ Замовлення <b>#{oid}</b> виконано", parse_mode="HTML")

    await safe_send(
        cb.bot,
        order["user_id"],
        f"🎉 <b>Ваше замовлення #{oid} виконано!</b>\nДякуємо за покупку 💙"
    )
    await cb.answer()


# ===================== USER: ORDER HISTORY =====================
@dp.message(F.text == "📦 Історія замовлень")
async def order_history(m: types.Message):
    d = load_data()
    orders = [o for o in d["orders"] if o["user_id"] == m.from_user.id]

    if not orders:
        return await m.answer("📦 У вас ще немає замовлень")

    for o in orders[-10:]:
        await m.answer(format_order(o), parse_mode="HTML")


# ===================== FSM CANCEL (GLOBAL) =====================
@dp.message(F.text == "❌ Скасувати")
async def cancel_any(m: types.Message, state: FSMContext):
    await state.clear()
    if is_admin(m.from_user.id):
        await m.answer("❌ Скасовано", reply_markup=admin_menu())
    else:
        await m.answer("❌ Скасовано", reply_markup=main_menu())
        # ===================== ADMIN: PRODUCT LIST =====================
def admin_products_kb(products: List[Dict[str, Any]]):
    kb = InlineKeyboardBuilder()
    for p in products:
        kb.button(
            text=f"✏️ {p['name']}",
            callback_data=f"edit_product:{p['id']}"
        )
        kb.button(
            text="🗑",
            callback_data=f"delete_product:{p['id']}"
        )
    kb.adjust(1, 1)
    return kb.as_markup()


@dp.message(F.text == "📦 Усі замовлення")
async def admin_products_list(m: types.Message):
    if not is_admin(m.from_user.id):
        return

    d = load_data()
    products = []
    for cat in d["categories"].values():
        for sub in cat.values():
            products.extend(sub)

    if not products:
        return await m.answer("📭 Товарів немає")

    await m.answer(
        "🛠 <b>Усі товари</b>\n\n"
        "✏️ — редагувати\n"
        "🗑 — видалити",
        parse_mode="HTML",
        reply_markup=admin_products_kb(products)
    )


# ===================== DELETE PRODUCT =====================
@dp.callback_query(F.data.startswith("delete_product:"))
async def delete_product(cb: types.CallbackQuery):
    if not is_admin(cb.from_user.id):
        return await cb.answer("⛔️", show_alert=True)

    pid = int(cb.data.split(":", 1)[1])
    d = load_data()

    for cat_name, cat in d["categories"].items():
        for sub_name, sub in cat.items():
            for p in sub:
                if p["id"] == pid:
                    sub.remove(p)
                    save_data(d)
                    await cb.message.answer(f"🗑 Товар «{p['name']}» видалено")
                    await cb.answer()
                    return

    await cb.answer("Товар не знайдено", show_alert=True)


# ===================== EDIT PRODUCT (FSM) =====================
class EditProductFSM(StatesGroup):
    name = State()
    price = State()
    description = State()


@dp.callback_query(F.data.startswith("edit_product:"))
async def edit_product_start(cb: types.CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return await cb.answer("⛔️", show_alert=True)

    pid = int(cb.data.split(":", 1)[1])
    d = load_data()
    p = find_product(d, pid)
    if not p:
        return await cb.answer("Не знайдено", show_alert=True)

    await state.set_state(EditProductFSM.name)
    await state.update_data(pid=pid)

    await cb.message.answer(
        f"✏️ <b>Редагування товару</b>\n\n"
        f"Поточна назва:\n<b>{p['name']}</b>\n\n"
        "Введи нову назву або ❌ Скасувати",
        parse_mode="HTML"
    )
    await cb.answer()


@dp.message(EditProductFSM.name)
async def edit_product_name(m: types.Message, state: FSMContext):
    if m.text == "❌ Скасувати":
        await state.clear()
        return await m.answer("❌ Скасовано", reply_markup=admin_menu())

    await state.update_data(name=m.text.strip())
    await state.set_state(EditProductFSM.price)
    await m.answer("💰 Введи нову ціну:")


@dp.message(EditProductFSM.price)
async def edit_product_price(m: types.Message, state: FSMContext):
    try:
        price = float(m.text.replace(",", "."))
    except ValueError:
        return await m.answer("⚠️ Введи число")

    await state.update_data(price=price)
    await state.set_state(EditProductFSM.description)
    await m.answer("📝 Введи новий опис:")


@dp.message(EditProductFSM.description)
async def edit_product_description(m: types.Message, state: FSMContext):
    data = await state.get_data()
    pid = data["pid"]

    d = load_data()
    p = find_product(d, pid)
    if not p:
        await state.clear()
        return await m.answer("❌ Товар не знайдено")

    p["name"] = data["name"]
    p["price"] = data["price"]
    p["description"] = m.text.strip()
    save_data(d)

    await state.clear()
    await m.answer(f"✅ Товар «{p['name']}» оновлено", reply_markup=admin_menu())