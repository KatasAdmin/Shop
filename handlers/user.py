# handlers/user.py
import time

from aiogram import Router, F, types
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder

from data import load_data, save_data, find_product, cart_total, next_order_id
from states import OrderFSM
from utils import notify_staff, format_order_text
from text import product_card, cart_summary

router = Router()

NO_SUB = "_"  # системна підкатегорія (в UI показуємо як "🧷 Утлет")
PREPAY_AMOUNT = 200  # ✅ передплата для наложки


# -------------------- USER MENU --------------------

def main_menu() -> types.ReplyKeyboardMarkup:
    return types.ReplyKeyboardMarkup(
        keyboard=[
            [types.KeyboardButton(text="🛍 Каталог"), types.KeyboardButton(text="🧺 Кошик")],
            [types.KeyboardButton(text="🔥 Хіти/Акції"), types.KeyboardButton(text="⭐ Обране")],
            [types.KeyboardButton(text="📦 Історія замовлень"), types.KeyboardButton(text="🆘 Підтримка")],
        ],
        resize_keyboard=True
    )


# -------------------- INLINE KEYBOARDS --------------------

def catalog_kb(cats):
    kb = InlineKeyboardBuilder()
    for c in cats:
        kb.button(text=str(c), callback_data=f"cat:{c}")
    kb.adjust(2)
    return kb.as_markup()


def subcat_kb(cat: str, subs):
    kb = InlineKeyboardBuilder()
    kb.button(text="🧷 Утлет", callback_data=f"sub:{cat}:{NO_SUB}")

    for s in subs:
        if s == NO_SUB:
            continue
        kb.button(text=str(s), callback_data=f"sub:{cat}:{s}")

    kb.adjust(2)
    return kb.as_markup()


def product_kb(pid: int, fav: bool = False):
    kb = InlineKeyboardBuilder()
    kb.button(text="🛒 В кошик", callback_data=f"add:{pid}")
    if fav:
        kb.button(text="❌ З обраного", callback_data=f"fav:off:{pid}")
    else:
        kb.button(text="⭐ В обране", callback_data=f"fav:on:{pid}")
    kb.adjust(2)
    return kb.as_markup()


def cart_kb(total: float):
    kb = InlineKeyboardBuilder()
    kb.button(text=f"🧾 Оформити ({total:.2f} ₴)", callback_data="checkout")
    kb.button(text="🗑 Очистити", callback_data="clear")
    kb.adjust(1)
    return kb.as_markup()


def payment_choice_kb(oid: int, total: float):
    """
    ✅ Вибір способу оплати:
    - повна оплата
    - передплата 200 (наложка НП)
    """
    kb = InlineKeyboardBuilder()
    kb.button(text=f"💳 Повна оплата ({total:.2f} ₴)", callback_data=f"pay_full:{oid}")
    kb.button(text=f"💵 Передплата {PREPAY_AMOUNT} ₴ (НП/наложка)", callback_data=f"pay_prepay:{oid}")
    kb.adjust(1)
    return kb.as_markup()


# -------------------- HELPERS --------------------

def user_favs(d, uid: int):
    d.setdefault("favorites", {})
    return d["favorites"].setdefault(str(uid), [])


def is_fav(d, uid: int, pid: int) -> bool:
    favs = set(int(x) for x in user_favs(d, uid))
    return pid in favs


async def send_product(message: types.Message, d, uid: int, p: dict):
    txt = product_card(p)
    kb = product_kb(int(p["id"]), fav=is_fav(d, uid, int(p["id"])))

    photos = p.get("photos", [])
    if photos:
        await message.answer_photo(photos[0], caption=txt, parse_mode="HTML", reply_markup=kb)
    else:
        await message.answer(txt, parse_mode="HTML", reply_markup=kb)


def find_order(d, oid: int):
    for o in d.get("orders", []):
        if int(o.get("id", -1)) == int(oid):
            return o
    return None


# -------------------- START --------------------

@router.message(CommandStart())
async def start(m: types.Message, state: FSMContext):
    await state.clear()
    await m.answer("🏠 Меню", reply_markup=main_menu())


# -------------------- CATALOG --------------------

@router.message(F.text == "🛍 Каталог")
async def catalog(m: types.Message):
    d = load_data()
    if not d.get("categories"):
        return await m.answer("Каталог порожній")
    await m.answer("Оберіть категорію:", reply_markup=catalog_kb(d["categories"].keys()))


@router.callback_query(F.data.startswith("cat:"))
async def choose_cat(cb: types.CallbackQuery):
    d = load_data()
    cat = cb.data.split(":", 1)[1]
    subs = d["categories"].get(cat, {})
    if not subs:
        await cb.message.answer("У цій категорії поки немає товарів.")
        return await cb.answer()

    await cb.message.answer(
        f"<b>{cat}</b>\nОберіть підкатегорію:",
        parse_mode="HTML",
        reply_markup=subcat_kb(cat, subs.keys())
    )
    await cb.answer()


@router.callback_query(F.data.startswith("sub:"))
async def choose_sub(cb: types.CallbackQuery):
    d = load_data()
    _, cat, sub = cb.data.split(":", 2)

    items = d["categories"].get(cat, {}).get(sub, [])
    if not items:
        await cb.message.answer("Товарів немає.")
        return await cb.answer()

    for p in items:
        await send_product(cb.message, d, cb.from_user.id, p)

    await cb.answer()


# -------------------- HITS --------------------

@router.message(F.text == "🔥 Хіти/Акції")
async def hits(m: types.Message):
    d = load_data()
    hits_ids = set(int(x) for x in d.get("hits", []))
    if not hits_ids:
        return await m.answer("Поки що немає Хітів/Акцій.")

    shown = 0
    for pid in hits_ids:
        p = find_product(d, int(pid))
        if p:
            shown += 1
            await send_product(m, d, m.from_user.id, p)

    if shown == 0:
        await m.answer("Хіти є, але товари не знайдені (перевір data.json).")


# -------------------- FAVORITES --------------------

@router.callback_query(F.data.startswith("fav:"))
async def fav_toggle(cb: types.CallbackQuery):
    d = load_data()
    uid = cb.from_user.id

    _, mode, pid_str = cb.data.split(":")
    pid = int(pid_str)

    favs = user_favs(d, uid)
    sset = set(int(x) for x in favs)

    if mode == "on":
        sset.add(pid)
        await cb.answer("⭐ Додано в обране")
    else:
        sset.discard(pid)
        await cb.answer("❌ Прибрано з обраного")

    d["favorites"][str(uid)] = list(sset)
    save_data(d)


@router.message(F.text == "⭐ Обране")
async def show_favs(m: types.Message):
    d = load_data()
    favs = set(int(x) for x in user_favs(d, m.from_user.id))
    if not favs:
        return await m.answer("Обране порожнє.")

    any_sent = False
    for pid in favs:
        p = find_product(d, int(pid))
        if p:
            any_sent = True
            await send_product(m, d, m.from_user.id, p)

    if not any_sent:
        await m.answer("Обране є, але товари не знайдені (можливо їх видалили).")


# -------------------- CART --------------------

@router.callback_query(F.data.startswith("add:"))
async def add_cart(cb: types.CallbackQuery):
    d = load_data()
    uid = str(cb.from_user.id)
    pid = int(cb.data.split(":")[1])

    d.setdefault("carts", {})
    d["carts"].setdefault(uid, []).append(pid)
    save_data(d)

    await cb.answer("Додано 🛒")


@router.message(F.text == "🧺 Кошик")
async def show_cart(m: types.Message):
    d = load_data()
    uid = str(m.from_user.id)
    cart = d.get("carts", {}).get(uid, [])
    if not cart:
        return await m.answer("Кошик порожній")

    items = []
    for pid in cart:
        p = find_product(d, int(pid))
        if p:
            items.append(p)

    total = cart_total(d, cart)
    txt = cart_summary(d, items)

    await m.answer(txt, parse_mode="HTML", reply_markup=cart_kb(total))


@router.callback_query(F.data == "clear")
async def clear_cart(cb: types.CallbackQuery):
    d = load_data()
    d.setdefault("carts", {})
    d["carts"][str(cb.from_user.id)] = []
    save_data(d)
    await cb.answer("Очищено 🗑")


# -------------------- CHECKOUT (FORM) --------------------

@router.callback_query(F.data == "checkout")
async def checkout(cb: types.CallbackQuery, state: FSMContext):
    d = load_data()
    uid = str(cb.from_user.id)
    cart = d.get("carts", {}).get(uid, [])
    if not cart:
        return await cb.answer("Кошик порожній", show_alert=True)

    await state.clear()
    await state.set_state(OrderFSM.name)
    await cb.message.answer("🧾 Оформлення\n\nВведіть ваше ім’я:")
    await cb.answer()


@router.message(OrderFSM.name)
async def order_name(m: types.Message, state: FSMContext):
    name = (m.text or "").strip()
    if not name:
        return await m.answer("Введіть ім’я текстом.")
    await state.update_data(name=name)
    await state.set_state(OrderFSM.phone)
    await m.answer("📞 Введіть номер телефону:")


@router.message(OrderFSM.phone)
async def order_phone(m: types.Message, state: FSMContext):
    phone = (m.text or "").strip()
    if not phone:
        return await m.answer("Введіть номер телефону.")
    await state.update_data(phone=phone)
    await state.set_state(OrderFSM.city)
    await m.answer("🏙 Введіть місто:")


@router.message(OrderFSM.city)
async def order_city(m: types.Message, state: FSMContext):
    city = (m.text or "").strip()
    if not city:
        return await m.answer("Введіть місто текстом.")
    await state.update_data(city=city)
    await state.set_state(OrderFSM.np_branch)
    await m.answer("📦 Нова Пошта: відділення/поштомат (наприклад: Відділення №12):")


@router.message(OrderFSM.np_branch)
async def order_np(m: types.Message, state: FSMContext):
    np_branch = (m.text or "").strip()
    if not np_branch:
        return await m.answer("Введіть відділення/поштомат.")
    await state.update_data(np_branch=np_branch)
    await state.set_state(OrderFSM.comment)
    await m.answer("📝 Коментар (або '-' щоб пропустити):")


@router.message(OrderFSM.comment)
async def order_finish(m: types.Message, state: FSMContext):
    comment = (m.text or "").strip()
    if comment == "-":
        comment = ""

    st = await state.get_data()
    st["comment"] = comment

    d = load_data()
    uid_str = str(m.from_user.id)
    cart = d.get("carts", {}).get(uid_str, [])
    if not cart:
        await state.clear()
        return await m.answer("Кошик порожній. Почніть знову.", reply_markup=main_menu())

    total = cart_total(d, cart)
    oid = next_order_id(d)

    d.setdefault("orders", [])
    d["orders"].append({
        "id": oid,
        "user_id": m.from_user.id,
        "items": list(cart),
        "total": float(total),
        "status": "pending",

        # ✅ для обліку
        "created_ts": int(time.time()),

        # ✅ оплата
        "payment_method": None,    # "full" | "np_prepay_200"
        "paid_ts": None,           # для full
        "prepay_amount": 0,        # для наложки
        "prepay_ts": None,         # час передплати

        "delivery": {
            "name": st.get("name", ""),
            "phone": st.get("phone", ""),
            "city": st.get("city", ""),
            "np_branch": st.get("np_branch", ""),
            "comment": st.get("comment", ""),
        }
    })

    save_data(d)
    await state.clear()

    await m.answer(
        f"✅ Замовлення створено #{oid}\n"
        f"Сума: {total:.2f} ₴\n\n"
        f"Оберіть спосіб оплати:",
        reply_markup=payment_choice_kb(oid, total)
    )


# -------------------- PAYMENT: FULL --------------------

@router.callback_query(F.data.startswith("pay_full:"))
async def pay_full(cb: types.CallbackQuery):
    d = load_data()
    oid = int(cb.data.split(":")[1])

    order = find_order(d, oid)
    if not order:
        await cb.message.answer("❌ Замовлення не знайдено.")
        return await cb.answer()

    if order.get("status") in ("paid", "prepay", "in_work", "done"):
        return await cb.answer("Це замовлення вже опрацьовується.", show_alert=True)

    # ✅ симуляція повної оплати
    order["payment_method"] = "full"
    order["status"] = "paid"
    order["paid_ts"] = int(time.time())

    # чистимо кошик
    d.setdefault("carts", {})
    d["carts"][str(order["user_id"])] = []
    save_data(d)

    await cb.message.answer(
        f"✅ Оплачено (симуляція).\n\n"
        f"Дякуємо! Замовлення #{oid} прийнято.\n"
        f"Менеджер зв’яжеться з вами найближчим часом.",
        reply_markup=main_menu()
    )
    await cb.answer()

    txt = "🆕 НОВЕ ОПЛАЧЕНЕ ЗАМОВЛЕННЯ\n\n" + format_order_text(d, order)
    await notify_staff(cb.bot, txt, parse_mode="HTML")


# -------------------- PAYMENT: PREPAY 200 (NP COD) --------------------

@router.callback_query(F.data.startswith("pay_prepay:"))
async def pay_prepay(cb: types.CallbackQuery):
    d = load_data()
    oid = int(cb.data.split(":")[1])

    order = find_order(d, oid)
    if not order:
        await cb.message.answer("❌ Замовлення не знайдено.")
        return await cb.answer()

    if order.get("status") in ("paid", "prepay", "in_work", "done"):
        return await cb.answer("Це замовлення вже опрацьовується.", show_alert=True)

    total = float(order.get("total", 0) or 0)
    prepay = PREPAY_AMOUNT
    rest = max(0.0, total - prepay)

    # ✅ симуляція передплати
    order["payment_method"] = "np_prepay_200"
    order["status"] = "prepay"
    order["prepay_amount"] = prepay
    order["prepay_ts"] = int(time.time())

    # чистимо кошик
    d.setdefault("carts", {})
    d["carts"][str(order["user_id"])] = []
    save_data(d)

    await cb.message.answer(
        "✅ Передплату зафіксовано (симуляція).\n\n"
        f"Передплата: {prepay} ₴\n"
        f"Залишок до сплати на НП: {rest:.2f} ₴\n\n"
        f"Замовлення #{oid} прийнято. Менеджер зв’яжеться з вами.",
        reply_markup=main_menu()
    )
    await cb.answer()

    txt = "🆕 НОВЕ ЗАМОВЛЕННЯ (ПЕРЕДПЛАТА / НП)\n\n" + format_order_text(d, order)
    await notify_staff(cb.bot, txt, parse_mode="HTML")


# -------------------- ORDERS HISTORY --------------------

@router.message(F.text == "📦 Історія замовлень")
async def history(m: types.Message):
    d = load_data()
    uid = m.from_user.id
    orders = [o for o in d.get("orders", []) if int(o.get("user_id", -1)) == int(uid)]
    if not orders:
        return await m.answer("Історія порожня.")

    for o in reversed(orders):
        await m.answer(format_order_text(d, o), parse_mode="HTML")


# -------------------- SUPPORT --------------------

@router.message(F.text == "🆘 Підтримка")
async def support(m: types.Message):
    await m.answer(
        "🆘 Підтримка\n\n"
        "Напишіть нам:\n"
        "• Telegram: @katas_support\n"
        "• Або просто відповідайте на це повідомлення — ми передамо менеджеру.",
        reply_markup=main_menu()
    )