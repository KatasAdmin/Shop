# ======= PART 1 START (REPLACE YOUR handlers/admin.py WITH THIS + PART 2) =======

from __future__ import annotations

from datetime import datetime, timezone

from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder

from data import load_data, save_data, next_product_id, find_product
from states import AdminFSM, EditProductFSM
from utils import is_admin, is_staff
from text import order_premium_text, product_card  # ✅ преміум картка товару

router = Router()

NO_SUB = "_"  # системна підкатегорія (в UI показуємо як "🧷 Утлет")


# -------------------- SMALL HELPERS --------------------

def _hits_set(d: dict) -> set[int]:
    """Нормалізує hits до set[int], навіть якщо в JSON збереглись рядки."""
    raw = d.get("hits", []) or []
    out: set[int] = set()
    for x in raw:
        try:
            out.add(int(x))
        except Exception:
            pass
    return out


def _ensure_product_schema(p: dict) -> None:
    """
    Захист від старих товарів без полів base_price/promo_*.
    """
    if "base_price" not in p:
        p["base_price"] = p.get("price", 0) or 0
    if "price" not in p:
        p["price"] = p.get("base_price", 0) or 0
    if "promo_price" not in p:
        p["promo_price"] = 0
    if "promo_until_ts" not in p:
        p["promo_until_ts"] = None


# -------------------- MENUS --------------------

def staff_menu(uid: int) -> types.ReplyKeyboardMarkup:
    rows = [
        [types.KeyboardButton(text="➕ Додати категорію"), types.KeyboardButton(text="➕ Додати підкатегорію")],
        [types.KeyboardButton(text="➕ Додати товар"), types.KeyboardButton(text="🛠 Товари")],
        [types.KeyboardButton(text="🗂 Категорії/Підкатегорії")],
        [types.KeyboardButton(text="📋 Нові (оплачені)"), types.KeyboardButton(text="📦 Усі замовлення")],
    ]
    if is_admin(uid):
        rows.append([types.KeyboardButton(text="👤 Додати менеджера")])
    rows.append([types.KeyboardButton(text="❌ Відміна")])
    return types.ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def cats_inline(action: str):
    d = load_data()
    kb = InlineKeyboardBuilder()
    for c in d["categories"].keys():
        kb.button(text=str(c), callback_data=f"adm:{action}:cat:{c}")
    kb.adjust(2)
    return kb.as_markup()


def subs_inline(cat: str, action: str, include_no_sub: bool = False):
    d = load_data()
    subs = d["categories"].get(cat, {})

    kb = InlineKeyboardBuilder()
    if include_no_sub:
        kb.button(text="🧷 Утлет", callback_data=f"adm:{action}:sub:{cat}:{NO_SUB}")

    for s in subs.keys():
        if s == NO_SUB:
            continue
        kb.button(text=str(s), callback_data=f"adm:{action}:sub:{cat}:{s}")

    kb.adjust(1)
    return kb.as_markup()


def confirm_kb(ok_cb: str):
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Так", callback_data=ok_cb)
    kb.button(text="❌ Ні", callback_data="adm:cancel")
    kb.adjust(2)
    return kb.as_markup()


def confirm_product_delete_kb(pid: int):
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Так, видалити", callback_data=f"adm:del:{pid}")
    kb.button(text="❌ Ні", callback_data="adm:cancel")
    kb.adjust(2)
    return kb.as_markup()


def edit_menu_kb(pid: int):
    kb = InlineKeyboardBuilder()
    kb.button(text="✏️ Назва", callback_data=f"adm:edit:name:{pid}")
    kb.button(text="💰 Ціна", callback_data=f"adm:edit:price:{pid}")
    kb.button(text="📝 Опис", callback_data=f"adm:edit:desc:{pid}")

    # ✅ Акції
    kb.button(text="🏷 Акційна ціна", callback_data=f"adm:edit:promo:{pid}")
    kb.button(text="🧹 Прибрати акцію", callback_data=f"adm:edit:promo_clear:{pid}")

    kb.button(text="⬅️ Назад", callback_data="adm:cancel")
    kb.adjust(1)
    return kb.as_markup()


def product_actions_kb(pid: int):
    d = load_data()
    hits = _hits_set(d)

    kb = InlineKeyboardBuilder()
    kb.button(text="✏️ Редагувати", callback_data=f"adm:editmenu:{pid}")
    kb.button(text="🗑 Видалити", callback_data=f"adm:delask:{pid}")

    if pid in hits:
        kb.button(text="❌ Прибрати з Хітів", callback_data=f"adm:hit:off:{pid}")
    else:
        kb.button(text="🔥 Додати в Хіти", callback_data=f"adm:hit:on:{pid}")

    kb.adjust(1)
    return kb.as_markup()


def order_actions_kb(oid: int, status: str):
    kb = InlineKeyboardBuilder()
    if status == "paid":
        kb.button(text="🟡 В роботу", callback_data=f"adm:order:in_work:{oid}")
    if status in ("paid", "in_work"):
        kb.button(text="✅ Завершити", callback_data=f"adm:order:done:{oid}")
    kb.adjust(1)
    return kb.as_markup() if kb.buttons else None


# -------------------- COMMON --------------------

@router.message(Command("admin"))
async def admin_cmd(m: types.Message, state: FSMContext):
    d = load_data()
    if not is_staff(d, m.from_user.id):
        return await m.answer("⛔️ Немає доступу")
    await state.clear()
    await m.answer("🔧 Панель (Адмін/Менеджер)", reply_markup=staff_menu(m.from_user.id))


@router.message(F.text == "❌ Відміна")
async def cancel_any(m: types.Message, state: FSMContext):
    d = load_data()
    if not is_staff(d, m.from_user.id):
        return await m.answer("⛔️ Немає доступу")
    await state.clear()
    await m.answer("Скасовано.", reply_markup=staff_menu(m.from_user.id))


@router.callback_query(F.data == "adm:cancel")
async def cancel_cb(cb: types.CallbackQuery, state: FSMContext):
    d = load_data()
    if not is_staff(d, cb.from_user.id):
        return await cb.answer("Немає доступу", show_alert=True)
    await state.clear()
    await cb.message.answer("Скасовано.", reply_markup=staff_menu(cb.from_user.id))
    await cb.answer()


# -------------------- ORDERS --------------------

@router.message(F.text == "📋 Нові (оплачені)")
async def orders_paid(m: types.Message):
    d = load_data()
    if not is_staff(d, m.from_user.id):
        return await m.answer("⛔️ Немає доступу")

    paid = [o for o in d.get("orders", []) if o.get("status") == "paid"]
    if not paid:
        return await m.answer("Немає нових оплачених замовлень.")

    for o in paid:
        products = []
        for pid in o.get("items", []):
            p = find_product(d, int(pid))
            if p:
                _ensure_product_schema(p)
                products.append(p)

        await m.answer(
            order_premium_text(d, o, products),
            parse_mode="HTML",
            reply_markup=order_actions_kb(o["id"], o.get("status", ""))
        )


@router.message(F.text == "📦 Усі замовлення")
async def orders_all(m: types.Message):
    d = load_data()
    if not is_staff(d, m.from_user.id):
        return await m.answer("⛔️ Немає доступу")

    orders = d.get("orders", [])
    if not orders:
        return await m.answer("Замовлень ще немає.")

    for o in reversed(orders):
        products = []
        for pid in o.get("items", []):
            p = find_product(d, int(pid))
            if p:
                _ensure_product_schema(p)
                products.append(p)

        await m.answer(
            order_premium_text(d, o, products),
            parse_mode="HTML",
            reply_markup=order_actions_kb(o["id"], o.get("status", ""))
        )


@router.callback_query(F.data.startswith("adm:order:"))
async def order_change_status(cb: types.CallbackQuery):
    d = load_data()
    if not is_staff(d, cb.from_user.id):
        return await cb.answer("Немає доступу", show_alert=True)

    _, _, action, oid_str = cb.data.split(":")
    oid = int(oid_str)

    order = next((o for o in d.get("orders", []) if o.get("id") == oid), None)
    if not order:
        await cb.message.answer("❌ Замовлення не знайдено.")
        return await cb.answer()

    if action == "in_work":
        if order.get("status") != "paid":
            return await cb.answer("Тільки paid можна взяти в роботу", show_alert=True)
        order["status"] = "in_work"
        save_data(d)
        await cb.message.answer(f"🟡 Замовлення #{oid} взято в роботу.")

    elif action == "done":
        if order.get("status") not in ("paid", "in_work"):
            return await cb.answer("Неможливо завершити", show_alert=True)
        order["status"] = "done"
        save_data(d)
        await cb.message.answer(f"✅ Замовлення #{oid} завершено.")

    await cb.answer()


# -------------------- MANAGERS (ADMIN ONLY) --------------------

@router.message(F.text == "👤 Додати менеджера")
async def add_manager_btn(m: types.Message, state: FSMContext):
    if not is_admin(m.from_user.id):
        return await m.answer("⛔️ Тільки адмін")
    await state.clear()
    await state.set_state(AdminFSM.add_manager)
    await m.answer("Введіть ID менеджера (число):")


@router.message(AdminFSM.add_manager)
async def add_manager_save(m: types.Message, state: FSMContext):
    if not is_admin(m.from_user.id):
        return await m.answer("⛔️ Тільки адмін")

    try:
        uid = int((m.text or "").strip())
    except Exception:
        return await m.answer("Введіть число (ID користувача).")

    d = load_data()
    d.setdefault("managers", [])
    if uid not in d["managers"]:
        d["managers"].append(uid)
        save_data(d)

    await state.clear()
    await m.answer(f"✅ Менеджера додано: {uid}", reply_markup=staff_menu(m.from_user.id))


# -------------------- ADD CATEGORY --------------------

@router.message(F.text == "➕ Додати категорію")
async def add_cat_btn(m: types.Message, state: FSMContext):
    d = load_data()
    if not is_staff(d, m.from_user.id):
        return await m.answer("⛔️ Немає доступу")
    await state.clear()
    await state.set_state(AdminFSM.add_cat)
    await m.answer("Введіть назву категорії:")


@router.message(AdminFSM.add_cat)
async def add_cat_name(m: types.Message, state: FSMContext):
    d = load_data()
    if not is_staff(d, m.from_user.id):
        return await m.answer("⛔️ Немає доступу")

    name = (m.text or "").strip()
    if not name:
        return await m.answer("Введіть назву текстом.")

    d["categories"].setdefault(name, {})
    save_data(d)

    await state.clear()
    await m.answer(f"✅ Категорію «{name}» додано.", reply_markup=staff_menu(m.from_user.id))


# -------------------- ADD SUBCATEGORY --------------------

@router.message(F.text == "➕ Додати підкатегорію")
async def add_sub_btn(m: types.Message, state: FSMContext):
    d = load_data()
    if not is_staff(d, m.from_user.id):
        return await m.answer("⛔️ Немає доступу")

    if not d["categories"]:
        return await m.answer("Спочатку додайте категорію.")

    await state.clear()
    await state.set_state(AdminFSM.add_sub_cat)
    await m.answer("Оберіть категорію:", reply_markup=cats_inline("sub_add"))


@router.callback_query(F.data.startswith("adm:sub_add:cat:"))
async def pick_cat_for_sub(cb: types.CallbackQuery, state: FSMContext):
    d = load_data()
    if not is_staff(d, cb.from_user.id):
        return await cb.answer("Немає доступу", show_alert=True)

    cat = cb.data.split(":")[3]
    await state.update_data(cat=cat)
    await state.set_state(AdminFSM.add_sub_name)
    await cb.message.answer(f"Введіть назву підкатегорії для «{cat}»:")
    await cb.answer()


@router.message(AdminFSM.add_sub_name)
async def add_sub_name(m: types.Message, state: FSMContext):
    d = load_data()
    if not is_staff(d, m.from_user.id):
        return await m.answer("⛔️ Немає доступу")

    sub = (m.text or "").strip()
    if not sub:
        return await m.answer("Введіть назву текстом.")
    if sub == NO_SUB:
        return await m.answer("Ця назва зарезервована. Оберіть іншу.")

    st = await state.get_data()
    cat = st.get("cat")
    if not cat:
        await state.clear()
        return await m.answer("❌ Помилка. Спробуйте ще раз.")

    d["categories"].setdefault(cat, {})
    d["categories"][cat].setdefault(sub, [])
    save_data(d)

    await state.clear()
    await m.answer(f"✅ Підкатегорію «{sub}» додано в «{cat}».", reply_markup=staff_menu(m.from_user.id))


# -------------------- CATEGORY / SUBCATEGORY MGMT (DELETE) --------------------

@router.message(F.text == "🗂 Категорії/Підкатегорії")
async def cat_mgmt(m: types.Message):
    d = load_data()
    if not is_staff(d, m.from_user.id):
        return await m.answer("⛔️ Немає доступу")

    if not d["categories"]:
        return await m.answer("Категорій ще немає.")

    await m.answer("Оберіть категорію:", reply_markup=cats_inline("catmgmt"))


@router.callback_query(F.data.startswith("adm:catmgmt:cat:"))
async def catmgmt_pick(cb: types.CallbackQuery):
    d = load_data()
    if not is_staff(d, cb.from_user.id):
        return await cb.answer("Немає доступу", show_alert=True)

    cat = cb.data.split(":")[3]
    kb = InlineKeyboardBuilder()
    kb.button(text="🗑 Видалити категорію", callback_data=f"adm:catdelask:{cat}")
    kb.button(text="🗑 Видалити підкатегорію", callback_data=f"adm:subdelpick:{cat}")
    kb.adjust(1)

    await cb.message.answer(
        f"Категорія: <b>{cat}</b>\nОберіть дію:",
        parse_mode="HTML",
        reply_markup=kb.as_markup()
    )
    await cb.answer()


@router.callback_query(F.data.startswith("adm:catdelask:"))
async def cat_del_ask(cb: types.CallbackQuery):
    d = load_data()
    if not is_staff(d, cb.from_user.id):
        return await cb.answer("Немає доступу", show_alert=True)

    cat = cb.data.split(":")[2]
    await cb.message.answer(
        f"⚠️ Видалити категорію «{cat}» разом з підкатегоріями і товарами?",
        reply_markup=confirm_kb(f"adm:catdel:{cat}")
    )
    await cb.answer()


@router.callback_query(F.data.startswith("adm:catdel:"))
async def cat_del(cb: types.CallbackQuery):
    d = load_data()
    if not is_staff(d, cb.from_user.id):
        return await cb.answer("Немає доступу", show_alert=True)

    cat = cb.data.split(":")[2]
    if cat in d["categories"]:
        hits = _hits_set(d)
        for sub, items in d["categories"][cat].items():
            for p in items:
                hits.discard(int(p.get("id", -1)))
        d["hits"] = list(hits)

        del d["categories"][cat]
        save_data(d)
        await cb.message.answer(f"✅ Категорію «{cat}» видалено.")
    else:
        await cb.message.answer("❌ Категорію не знайдено.")
    await cb.answer()


@router.callback_query(F.data.startswith("adm:subdelpick:"))
async def sub_del_pick(cb: types.CallbackQuery):
    d = load_data()
    if not is_staff(d, cb.from_user.id):
        return await cb.answer("Немає доступу", show_alert=True)

    cat = cb.data.split(":")[2]
    subs = d["categories"].get(cat, {})
    real = [s for s in subs.keys() if s != NO_SUB]
    if not real:
        await cb.message.answer("У цій категорії немає підкатегорій.")
        return await cb.answer()

    await cb.message.answer(
        "Оберіть підкатегорію:",
        reply_markup=subs_inline(cat, "subdelask", include_no_sub=False)
    )
    await cb.answer()


@router.callback_query(F.data.startswith("adm:subdelask:sub:"))
async def sub_del_ask(cb: types.CallbackQuery):
    d = load_data()
    if not is_staff(d, cb.from_user.id):
        return await cb.answer("Немає доступу", show_alert=True)

    _, _, _, cat, sub = cb.data.split(":")
    await cb.message.answer(
        f"⚠️ Видалити підкатегорію «{sub}» у «{cat}» разом з товарами?",
        reply_markup=confirm_kb(f"adm:subdel:{cat}:{sub}")
    )
    await cb.answer()


@router.callback_query(F.data.startswith("adm:subdel:"))
async def sub_del(cb: types.CallbackQuery):
    d = load_data()
    if not is_staff(d, cb.from_user.id):
        return await cb.answer("Немає доступу", show_alert=True)

    _, _, cat, sub = cb.data.split(":")
    if cat in d["categories"] and sub in d["categories"][cat]:
        hits = _hits_set(d)
        for p in d["categories"][cat][sub]:
            hits.discard(int(p.get("id", -1)))
        d["hits"] = list(hits)

        del d["categories"][cat][sub]
        save_data(d)
        await cb.message.answer(f"✅ Підкатегорію «{sub}» видалено.")
    else:
        await cb.message.answer("❌ Підкатегорію не знайдено.")
    await cb.answer()


# -------------------- ADD PRODUCT (NO SUB OK) --------------------

@router.message(F.text == "➕ Додати товар")
async def add_product_btn(m: types.Message, state: FSMContext):
    d = load_data()
    if not is_staff(d, m.from_user.id):
        return await m.answer("⛔️ Немає доступу")

    if not d["categories"]:
        return await m.answer("Спочатку додайте категорію.")

    await state.clear()
    await state.set_state(AdminFSM.prod_cat)
    await m.answer("Оберіть категорію:", reply_markup=cats_inline("prod_cat"))


@router.callback_query(F.data.startswith("adm:prod_cat:cat:"))
async def prod_pick_cat(cb: types.CallbackQuery, state: FSMContext):
    d = load_data()
    if not is_staff(d, cb.from_user.id):
        return await cb.answer("Немає доступу", show_alert=True)

    cat = cb.data.split(":")[3]
    await state.update_data(cat=cat)

    await state.set_state(AdminFSM.prod_sub)
    await cb.message.answer(
        "Оберіть підкатегорію або 🧷 Утлет:",
        reply_markup=subs_inline(cat, "prod_sub", include_no_sub=True)
    )
    await cb.answer()


@router.callback_query(F.data.startswith("adm:prod_sub:sub:"))
async def prod_pick_sub(cb: types.CallbackQuery, state: FSMContext):
    d = load_data()
    if not is_staff(d, cb.from_user.id):
        return await cb.answer("Немає доступу", show_alert=True)

    _, _, _, cat, sub = cb.data.split(":")
    await state.update_data(cat=cat, sub=sub)

    await state.set_state(AdminFSM.prod_name)
    await cb.message.answer("Введіть назву товару:")
    await cb.answer()


@router.message(AdminFSM.prod_name)
async def prod_name(m: types.Message, state: FSMContext):
    d = load_data()
    if not is_staff(d, m.from_user.id):
        return await m.answer("⛔️ Немає доступу")

    name = (m.text or "").strip()
    if not name:
        return await m.answer("Введіть назву текстом.")
    await state.update_data(name=name)
    await state.set_state(AdminFSM.prod_price)
    await m.answer("Введіть ціну (наприклад 199.99):")


@router.message(AdminFSM.prod_price)
async def prod_price(m: types.Message, state: FSMContext):
    d = load_data()
    if not is_staff(d, m.from_user.id):
        return await m.answer("⛔️ Немає доступу")

    t = (m.text or "").replace(",", ".").strip()
    try:
        price = float(t)
    except Exception:
        return await m.answer("❌ Невірна ціна. Введіть число (наприклад 199.99).")

    await state.update_data(price=price)
    await state.set_state(AdminFSM.prod_desc)
    await m.answer("Введіть опис (або '-' щоб пропустити):")


@router.message(AdminFSM.prod_desc)
async def prod_desc(m: types.Message, state: FSMContext):
    d = load_data()
    if not is_staff(d, m.from_user.id):
        return await m.answer("⛔️ Немає доступу")

    desc = (m.text or "").strip()
    if desc == "-":
        desc = ""

    await state.update_data(description=desc, photos=[])
    await state.set_state(AdminFSM.prod_photos)
    await m.answer("Надішліть фото (можна кілька). Коли закінчите — напишіть: ГОТОВО\n(або одразу ГОТОВО без фото)")


@router.message(AdminFSM.prod_photos, F.photo)
async def prod_photo(m: types.Message, state: FSMContext):
    d = load_data()
    if not is_staff(d, m.from_user.id):
        return await m.answer("⛔️ Немає доступу")

    st = await state.get_data()
    photos = st.get("photos", [])
    photos.append(m.photo[-1].file_id)
    await state.update_data(photos=photos)
    await m.answer("📸 Фото додано. Ще фото або напишіть: ГОТОВО")


@router.message(AdminFSM.prod_photos)
async def prod_done(m: types.Message, state: FSMContext):
    d = load_data()
    if not is_staff(d, m.from_user.id):
        return await m.answer("⛔️ Немає доступу")

    if (m.text or "").strip().lower() not in ("готово", "готов", "done", "ok"):
        return await m.answer("Надішліть фото або напишіть: ГОТОВО")

    st = await state.get_data()
    cat = st["cat"]
    sub = st["sub"]

    d = load_data()
    pid = next_product_id(d)

    d["categories"].setdefault(cat, {})
    d["categories"][cat].setdefault(sub, [])

    price = float(st["price"])
    product = {
        "id": pid,
        "name": st["name"],
        # ✅ сумісність: і price, і base_price
        "price": price,
        "base_price": price,
        "promo_price": 0,
        "promo_until_ts": None,
        "description": st.get("description", ""),
        "photos": st.get("photos", []),
    }

    d["categories"][cat][sub].append(product)
    save_data(d)

    await state.clear()
    await m.answer(f"✅ Товар додано: {product['name']} (ID: {pid})", reply_markup=staff_menu(m.from_user.id))


# -------------------- PRODUCTS LIST / EDIT / DELETE --------------------

@router.message(F.text == "🛠 Товари")
async def products_btn(m: types.Message):
    d = load_data()
    if not is_staff(d, m.from_user.id):
        return await m.answer("⛔️ Немає доступу")

    if not d["categories"]:
        return await m.answer("Категорій немає.")

    await m.answer("Оберіть категорію:", reply_markup=cats_inline("plist_cat"))


@router.callback_query(F.data.startswith("adm:plist_cat:cat:"))
async def plist_pick_cat(cb: types.CallbackQuery):
    d = load_data()
    if not is_staff(d, cb.from_user.id):
        return await cb.answer("Немає доступу", show_alert=True)

    cat = cb.data.split(":")[3]
    subs = d["categories"].get(cat, {})
    if not subs:
        await cb.message.answer("У категорії немає підкатегорій/товарів.")
        return await cb.answer()

    await cb.message.answer(
        "Оберіть підкатегорію (або 🧷 Утлет):",
        reply_markup=subs_inline(cat, "plist_sub", include_no_sub=True)
    )
    await cb.answer()


@router.callback_query(F.data.startswith("adm:plist_sub:sub:"))
async def plist_pick_sub(cb: types.CallbackQuery):
    d = load_data()
    if not is_staff(d, cb.from_user.id):
        return await cb.answer("Немає доступу", show_alert=True)

    _, _, _, cat, sub = cb.data.split(":")
    items = d["categories"].get(cat, {}).get(sub, [])
    if not items:
        await cb.message.answer("Товарів немає.")
        return await cb.answer()

    for p in items:
        _ensure_product_schema(p)
        txt = product_card(p)
        if p.get("photos"):
            await cb.message.answer_photo(
                p["photos"][0],
                caption=txt,
                parse_mode="HTML",
                reply_markup=product_actions_kb(int(p["id"]))
            )
        else:
            await cb.message.answer(txt, parse_mode="HTML", reply_markup=product_actions_kb(int(p["id"])))

    await cb.answer()


# -------------------- HITS --------------------

@router.callback_query(F.data.startswith("adm:hit:"))
async def toggle_hit(cb: types.CallbackQuery):
    d = load_data()
    if not is_staff(d, cb.from_user.id):
        return await cb.answer("Немає доступу", show_alert=True)

    _, _, mode, pid_str = cb.data.split(":")
    pid = int(pid_str)

    hits = _hits_set(d)

    if mode == "on":
        hits.add(pid)
        await cb.answer("Додано в Хіти 🔥")
    else:
        hits.discard(pid)
        await cb.answer("Прибрано з Хітів")

    d["hits"] = list(hits)
    save_data(d)

    await cb.message.answer("✅ Оновлено (Хіти/Акції).")


# -------------------- DELETE PRODUCT --------------------

@router.callback_query(F.data.startswith("adm:delask:"))
async def product_del_ask(cb: types.CallbackQuery):
    d = load_data()
    if not is_staff(d, cb.from_user.id):
        return await cb.answer("Немає доступу", show_alert=True)

    pid = int(cb.data.split(":")[2])
    p = find_product(d, pid)
    name = p["name"] if p else f"#{pid}"
    await cb.message.answer(f"⚠️ Видалити товар {name}?", reply_markup=confirm_product_delete_kb(pid))
    await cb.answer()


@router.callback_query(F.data.startswith("adm:del:"))
async def product_del(cb: types.CallbackQuery):
    d = load_data()
    if not is_staff(d, cb.from_user.id):
        return await cb.answer("Немає доступу", show_alert=True)

    pid = int(cb.data.split(":")[2])
    deleted = False

    for cat in d["categories"].values():
        for sub, items in cat.items():
            for i, p in enumerate(items):
                if int(p.get("id", -1)) == pid:
                    items.pop(i)
                    deleted = True
                    break
            if deleted:
                break
        if deleted:
            break

    hits = _hits_set(d)
    hits.discard(pid)
    d["hits"] = list(hits)

    if deleted:
        save_data(d)
        await cb.message.answer("✅ Товар видалено.")
    else:
        await cb.message.answer("❌ Товар не знайдено.")
    await cb.answer()


# -------------------- EDIT PRODUCT --------------------

@router.callback_query(F.data.startswith("adm:editmenu:"))
async def edit_menu(cb: types.CallbackQuery, state: FSMContext):
    d = load_data()
    if not is_staff(d, cb.from_user.id):
        return await cb.answer("Немає доступу", show_alert=True)

    pid = int(cb.data.split(":")[2])
    p = find_product(d, pid)
    if not p:
        await cb.message.answer("❌ Товар не знайдено.")
        return await cb.answer()

    _ensure_product_schema(p)

    await cb.message.answer(
        f"Редагування: <b>{p['name']}</b>",
        parse_mode="HTML",
        reply_markup=edit_menu_kb(pid)
    )
    await cb.answer()


@router.callback_query(F.data.startswith("adm:edit:"))
async def edit_field(cb: types.CallbackQuery, state: FSMContext):
    d = load_data()
    if not is_staff(d, cb.from_user.id):
        return await cb.answer("Немає доступу", show_alert=True)

    _, _, field, pid_str = cb.data.split(":")
    pid = int(pid_str)

    p = find_product(d, pid)
    if not p:
        await cb.message.answer("❌ Товар не знайдено.")
        return await cb.answer()

    _ensure_product_schema(p)

    await state.clear()
    await state.update_data(pid=pid)

    if field == "name":
        await state.set_state(EditProductFSM.name)
        await cb.message.answer("Введіть нову назву:")

    elif field == "price":
        await state.set_state(EditProductFSM.price)
        await cb.message.answer("Введіть нову базову ціну (число):")

    elif field == "desc":
        await state.set_state(EditProductFSM.desc)
        await cb.message.answer("Введіть новий опис (або '-' щоб очистити):")

    elif field == "promo":
        await state.set_state(EditProductFSM.promo_price)
        await cb.message.answer(
            "Введіть акційну ціну (число).\n"
            "Потім я спитаю дату/час завершення (або '-' щоб без дати)."
        )

    elif field == "promo_clear":
        p["promo_price"] = 0
        p["promo_until_ts"] = None
        save_data(d)
        await cb.message.answer("✅ Акцію прибрано.", reply_markup=staff_menu(cb.from_user.id))

    await cb.answer()


@router.message(EditProductFSM.name)
async def edit_name(m: types.Message, state: FSMContext):
    d = load_data()
    if not is_staff(d, m.from_user.id):
        return await m.answer("⛔️ Немає доступу")

    st = await state.get_data()
    pid = st.get("pid")
    p = find_product(d, pid)
    if not p:
        await state.clear()
        return await m.answer("❌ Товар не знайдено.")

    _ensure_product_schema(p)

    new = (m.text or "").strip()
    if not new:
        return await m.answer("Введіть назву текстом.")

    p["name"] = new
    save_data(d)
    await state.clear()
    await m.answer("✅ Назву оновлено.", reply_markup=staff_menu(m.from_user.id))


@router.message(EditProductFSM.price)
async def edit_price(m: types.Message, state: FSMContext):
    d = load_data()
    if not is_staff(d, m.from_user.id):
        return await m.answer("⛔️ Немає доступу")

    st = await state.get_data()
    pid = st.get("pid")
    p = find_product(d, pid)
    if not p:
        await state.clear()
        return await m.answer("❌ Товар не знайдено.")

    _ensure_product_schema(p)

    t = (m.text or "").replace(",", ".").strip()
    try:
        price = float(t)
    except Exception:
        return await m.answer("Введіть число (наприклад 199.99).")

    p["base_price"] = price
    p["price"] = price  # сумісність
    save_data(d)

    await state.clear()
    await m.answer("✅ Ціну оновлено.", reply_markup=staff_menu(m.from_user.id))


@router.message(EditProductFSM.desc)
async def edit_desc(m: types.Message, state: FSMContext):
    d = load_data()
    if not is_staff(d, m.from_user.id):
        return await m.answer("⛔️ Немає доступу")

    st = await state.get_data()
    pid = st.get("pid")
    p = find_product(d, pid)
    if not p:
        await state.clear()
        return await m.answer("❌ Товар не знайдено.")

    _ensure_product_schema(p)

    desc = (m.text or "").strip()
    if desc == "-":
        desc = ""

    p["description"] = desc
    save_data(d)

    await state.clear()
    await m.answer("✅ Опис оновлено.", reply_markup=staff_menu(m.from_user.id))


# -------- PROMO FLOW --------

@router.message(EditProductFSM.promo_price)
async def edit_promo_price(m: types.Message, state: FSMContext):
    d = load_data()
    if not is_staff(d, m.from_user.id):
        return await m.answer("⛔️ Немає доступу")

    st = await state.get_data()
    pid = st.get("pid")
    p = find_product(d, pid)
    if not p:
        await state.clear()
        return await m.answer("❌ Товар не знайдено.")

    _ensure_product_schema(p)

    t = (m.text or "").replace(",", ".").strip()
    try:
        promo = float(t)
    except Exception:
        return await m.answer("Введіть число (наприклад 1499.99).")

    if promo <= 0:
        return await m.answer("Акційна ціна має бути > 0.")

    p["promo_price"] = promo
    save_data(d)

    await state.set_state(EditProductFSM.promo_until)
    await m.answer(
        "Вкажіть дату завершення акції у форматі:\n"
        "<b>YYYY-MM-DD</b> або <b>YYYY-MM-DD HH:MM</b>\n"
        "Наприклад: 2026-01-20 або 2026-01-20 23:59\n\n"
        "Або напишіть <b>-</b>, якщо без дати.",
        parse_mode="HTML"
    )


# ======= PART 1 END (DO NOT EDIT ABOVE) =======
# ======= PART 2 START (PASTE IMMEDIATELY AFTER PART 1) =======

@router.message(EditProductFSM.promo_until)
async def edit_promo_until(m: types.Message, state: FSMContext):
    d = load_data()
    if not is_staff(d, m.from_user.id):
        return await m.answer("⛔️ Немає доступу")

    st = await state.get_data()
    pid = st.get("pid")
    p = find_product(d, pid)
    if not p:
        await state.clear()
        return await m.answer("❌ Товар не знайдено.")

    _ensure_product_schema(p)

    txt = (m.text or "").strip()

    if txt == "-":
        p["promo_until_ts"] = None
        save_data(d)
        await state.clear()
        return await m.answer("✅ Акцію встановлено (без дати).", reply_markup=staff_menu(m.from_user.id))

    # приймаємо 2 формати: YYYY-MM-DD або YYYY-MM-DD HH:MM
    try:
        if len(txt) == 10:
            dt = datetime.strptime(txt, "%Y-%m-%d")
        else:
            dt = datetime.strptime(txt, "%Y-%m-%d %H:%M")

        # Зберігаємо як UTC timestamp (як у text.py: datetime.now(tz=timezone.utc))
        ts = int(dt.replace(tzinfo=timezone.utc).timestamp())
    except Exception:
        return await m.answer(
            "❌ Невірний формат.\n"
            "Приклад:\n"
            "• 2026-01-20\n"
            "• 2026-01-20 23:59\n"
            "• або '-'"
        )

    p["promo_until_ts"] = ts
    save_data(d)

    await state.clear()
    await m.answer("✅ Акцію встановлено.", reply_markup=staff_menu(m.from_user.id))


# ======= PART 2 END =======