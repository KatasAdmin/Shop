from aiogram import Router, F, types
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder

from data import load_data, save_data, find_product, cart_total, next_order_id
from states import OrderFSM
from utils import notify_managers, format_order_text

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


def contact_kb():
    return types.ReplyKeyboardMarkup(
        keyboard=[
            [types.KeyboardButton(text="📲 Поділитися номером", request_contact=True)],
            [types.KeyboardButton(text="✍️ Ввести номер вручну")],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


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
            names.append(f"• {p['name']} — {float(p['price']):.2f} ₴")

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


# ====== CHECKOUT: собираем данные доставки через FSM ======

@router.callback_query(F.data == "checkout")
async def checkout(cb: types.CallbackQuery, state: FSMContext):
    d = load_data()
    uid = str(cb.from_user.id)
    cart = d["carts"].get(uid, [])
    if not cart:
        return await cb.answer("Кошик порожній", show_alert=True)

    total = cart_total(d, cart)

    await state.clear()
    await state.update_data(cart=cart, total=total)
    await state.set_state(OrderFSM.name)

    await cb.message.answer("Введіть ваше ім'я (ПІБ):")
    await cb.answer()


@router.message(OrderFSM.name)
async def order_name(m: types.Message, state: FSMContext):
    name = (m.text or "").strip()
    if not name:
        return await m.answer("Введіть ім'я текстом.")
    await state.update_data(customer_name=name)
    await state.set_state(OrderFSM.phone)
    await m.answer("Тепер телефон (можна кнопкою):", reply_markup=contact_kb())


@router.message(OrderFSM.phone, F.contact)
async def order_phone_contact(m: types.Message, state: FSMContext):
    phone = (m.contact.phone_number or "").strip()
    if not phone:
        return await m.answer("Не бачу номер. Спробуйте ще раз.")
    await state.update_data(phone=phone)
    await state.set_state(OrderFSM.address)
    await m.answer("Введіть адресу доставки:", reply_markup=types.ReplyKeyboardRemove())


@router.message(OrderFSM.phone)
async def order_phone_text(m: types.Message, state: FSMContext):
    t = (m.text or "").strip()
    if t == "✍️ Ввести номер вручну":
        return await m.answer("Введіть номер телефону текстом (наприклад +380...):", reply_markup=types.ReplyKeyboardRemove())

    # минимальная проверка
    phone = t.replace(" ", "")
    if len(phone) < 6:
        return await m.answer("Невірний номер. Введіть ще раз (наприклад +380...):")

    await state.update_data(phone=phone)
    await state.set_state(OrderFSM.address)
    await m.answer("Введіть адресу доставки:", reply_markup=types.ReplyKeyboardRemove())


@router.message(OrderFSM.address)
async def order_address(m: types.Message, state: FSMContext):
    address = (m.text or "").strip()
    if not address:
        return await m.answer("Введіть адресу текстом.")
    await state.update_data(address=address)
    await state.set_state(OrderFSM.comment)
    await m.answer("Коментар до доставки? (або напишіть '-' щоб пропустити)")


@router.message(OrderFSM.comment)
async def order_comment(m: types.Message, state: FSMContext):
    comment = (m.text or "").strip()
    if comment == "-":
        comment = ""

    st = await state.get_data()
    cart = st["cart"]
    total = float(st["total"])

    d = load_data()
    uid = str(m.from_user.id)
    oid = next_order_id(d)

    d["orders"].append({
        "id": oid,
        "user_id": m.from_user.id,
        "username": (m.from_user.username or ""),
        "items": cart,
        "total": total,
        "status": "new",  # станет paid после оплаты
        "customer_name": st.get("customer_name", ""),
        "phone": st.get("phone", ""),
        "address": st.get("address", ""),
        "comment": comment,
    })

    # очищаем корзину
    d["carts"][uid] = []
    save_data(d)

    await state.clear()
    await m.answer(
        f"✅ Замовлення створено #{oid}\nСума: {total:.2f} ₴\n\nНатисніть «Оплатити» (симуляція):",
        reply_markup=pay_kb(oid)
    )


# ====== PAY: после "оплачено" — уведомляем менеджеров ======

@router.callback_query(F.data.startswith("pay:"))
async def pay(cb: types.CallbackQuery):
    d = load_data()
    oid = int(cb.data.split(":")[1])

    order = None
    for o in d["orders"]:
        if o["id"] == oid:
            o["status"] = "paid"
            order = o
            break

    save_data(d)

    if order:
        # Формируем полный текст для менеджера
        text = "💰 ОПЛАЧЕНО!\n\n" + format_order_text(d, order)
        await notify_managers(cb.bot, text)

    await cb.message.answer("✅ Оплачено (симуляція)")
    await cb.answer()


@router.message(F.text == "📦 Історія замовлень")
async def order_history(m: types.Message):
    d = load_data()
    uid = m.from_user.id
    my = [o for o in d["orders"] if o.get("user_id") == uid]
    if not my:
        return await m.answer("Історія порожня.")

    lines = []
    for o in reversed(my[-20:]):
        lines.append(f"#{o['id']} — {o.get('status','new')} — {float(o.get('total',0)):.2f} ₴")

    await m.answer("📦 Ваші замовлення:\n" + "\n".join(lines))