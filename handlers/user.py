# handlers/user.py

from aiogram import Router, F, types
from aiogram.filters import CommandStart
from aiogram.utils.keyboard import InlineKeyboardBuilder

from data import load_data, save_data, find_product, cart_total, next_order_id

router = Router()


def main_menu() -> types.ReplyKeyboardMarkup:
    return types.ReplyKeyboardMarkup(
        keyboard=[
            [
                types.KeyboardButton(text="🛍 Каталог"),
                types.KeyboardButton(text="🧺 Кошик"),
            ],
            [
                types.KeyboardButton(text="📦 Історія замовлень"),
            ],
        ],
        resize_keyboard=True
    )


def catalog_kb(cats):
    kb = InlineKeyboardBuilder()
    for c in cats:
        kb.button(text=str(c), callback_data=f"cat:{c}")
    kb.adjust(2)
    return kb.as_markup()


def subcat_kb(cat, subs):
    kb = InlineKeyboardBuilder()
    for s in subs:
        kb.button(text=str(s), callback_data=f"sub:{cat}:{s}")
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


@router.message(CommandStart())
async def start(m: types.Message):
    await m.answer("🏠 Меню", reply_markup=main_menu())


@router.message(F.text == "🛍 Каталог")
async def catalog(m: types.Message):
    d = load_data()
    if not d["categories"]:
        return await m.answer("Каталог порожній")
    await m.answer("Оберіть категорію:", reply_markup=catalog_kb(d["categories"].keys()))


@router.callback_query(F.data.startswith("cat:"))
async def choose_cat(cb: types.CallbackQuery):
    d = load_data()
    cat = cb.data.split(":")[1]
    await cb.message.answer(
        f"<b>{cat}</b>",
        parse_mode="HTML",
        reply_markup=subcat_kb(cat, d["categories"][cat].keys())
    )
    await cb.answer()


@router.callback_query(F.data.startswith("sub:"))
async def choose_sub(cb: types.CallbackQuery):
    d = load_data()
    _, cat, sub = cb.data.split(":")
    for p in d["categories"][cat][sub]:
        text = f"<b>{p['name']}</b>\n💰 {p['price']} ₴\n\n{p.get('description','')}"
        photos = p.get("photos", [])
        if photos:
            await cb.message.answer_photo(
                photos[0],
                caption=text,
                parse_mode="HTML",
                reply_markup=add_cart_kb(p["id"])
            )
        else:
            await cb.message.answer(text, parse_mode="HTML", reply_markup=add_cart_kb(p["id"]))
    await cb.answer()


@router.callback_query(F.data.startswith("add:"))
async def add_cart(cb: types.CallbackQuery):
    d = load_data()
    uid = str(cb.from_user.id)
    d["carts"].setdefault(uid, []).append(int(cb.data.split(":")[1]))
    save_data(d)
    await cb.answer("Додано")


@router.message(F.text == "🧺 Кошик")
async def show_cart(m: types.Message):
    d = load_data()
    uid = str(m.from_user.id)
    cart = d["carts"].get(uid, [])
    if not cart:
        return await m.answer("Кошик порожній")

    total = cart_total(d, cart)
    names = []
    for pid in cart:
        p = find_product(d, pid)
        if p:
            names.append(p["name"])

    await m.answer(
        "🧺 Кошик:\n" + "\n".join(names) + f"\n\nРазом: {total:.2f} ₴",
        reply_markup=cart_kb(total)
    )


@router.callback_query(F.data == "clear")
async def clear_cart(cb: types.CallbackQuery):
    d = load_data()
    d["carts"][str(cb.from_user.id)] = []
    save_data(d)
    await cb.answer("Очищено")


@router.callback_query(F.data == "checkout")
async def checkout(cb: types.CallbackQuery):
    d = load_data()
    uid = str(cb.from_user.id)
    cart = d["carts"].get(uid, [])
    if not cart:
        return await cb.answer("Кошик порожній", show_alert=True)

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

    await cb.message.answer(f"Замовлення #{oid}\nСума: {total:.2f} ₴", reply_markup=pay_kb(oid))
    await cb.answer()


@router.callback_query(F.data.startswith("pay:"))
async def pay(cb: types.CallbackQuery):
    d = load_data()
    oid = int(cb.data.split(":")[1])
    for o in d["orders"]:
        if o["id"] == oid:
            o["status"] = "paid"
    save_data(d)
    await cb.message.answer("✅ Оплачено (симуляція)")
    await cb.answer()