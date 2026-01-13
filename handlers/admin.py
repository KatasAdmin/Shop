# handlers/admin.py
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


def _order_products(d: dict, o: dict) -> list[dict]:
    """
    Повертає список товарів замовлення (з нормалізацією полів).
    Потрібно для order_premium_text, щоб суми/акції/назви завжди були коректні.
    """
    products: list[dict] = []
    for pid in (o.get("items", []) or []):
        p = find_product(d, int(pid))
        if p:
            _ensure_product_schema(p)
            products.append(p)
    return products
    

# -------------------- MENUS --------------------

def staff_menu(uid: int) -> types.ReplyKeyboardMarkup:
    rows = [
        [types.KeyboardButton(text="➕ Додати категорію"), types.KeyboardButton(text="➕ Додати підкатегорію")],
        [types.KeyboardButton(text="➕ Додати товар"), types.KeyboardButton(text="🛠 Товари")],
        [types.KeyboardButton(text="🗂 Категорії/Підкатегорії")],
        [types.KeyboardButton(text="📋 Нові (оплачені)"), types.KeyboardButton(text="📦 Усі замовлення")],
        [types.KeyboardButton(text="🔎 Пошук покупця")],
    ]
    if is_admin(uid):
        rows.append([types.KeyboardButton(text="👤 Додати менеджера")])
    rows.append([types.KeyboardButton(text="❌ Відміна")])
    return types.ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


async def cats_inline(action: str) -> types.InlineKeyboardMarkup:
    d = await load_data()
    kb = InlineKeyboardBuilder()
    for c in (d.get("categories", {}) or {}).keys():
        kb.button(text=str(c), callback_data=f"adm:{action}:cat:{c}")
    kb.adjust(2)
    return kb.as_markup()


async def subs_inline(cat: str, action: str, include_no_sub: bool = False) -> types.InlineKeyboardMarkup:
    d = await load_data()
    subs = (d.get("categories", {}) or {}).get(cat, {}) or {}

    kb = InlineKeyboardBuilder()
    if include_no_sub:
        kb.button(text="🧷 Утлет", callback_data=f"adm:{action}:sub:{cat}:{NO_SUB}")

    for s in subs.keys():
        if s == NO_SUB:
            continue
        kb.button(text=str(s), callback_data=f"adm:{action}:sub:{cat}:{s}")

    kb.adjust(1)
    return kb.as_markup()


def confirm_kb(ok_cb: str) -> types.InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Так", callback_data=ok_cb)
    kb.button(text="❌ Ні", callback_data="adm:cancel")
    kb.adjust(2)
    return kb.as_markup()


def confirm_product_delete_kb(pid: int) -> types.InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Так, видалити", callback_data=f"adm:del:{pid}")
    kb.button(text="❌ Ні", callback_data="adm:cancel")
    kb.adjust(2)
    return kb.as_markup()


def edit_menu_kb(pid: int) -> types.InlineKeyboardMarkup:
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

async def product_actions_kb(pid: int) -> types.InlineKeyboardMarkup:
    d = await load_data()
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

def order_actions_kb(oid: int, status: str) -> types.InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()

    # взяти в роботу
    if status in ("paid", "prepay"):
        kb.button(text="🟡 В роботу", callback_data=f"adm:order:in_work:{oid}")

    # завершити (як “закрито”)
    if status in ("paid", "prepay", "in_work", "shipped"):
        kb.button(text="✅ Завершити", callback_data=f"adm:order:done:{oid}")

    # логістика
    if status in ("paid", "prepay", "in_work", "shipped"):
        kb.button(text="🚚 Відправлено", callback_data=f"adm:order:shipped:{oid}")

    if status == "shipped":
        kb.button(text="✅ Забрав (продано)", callback_data=f"adm:order:picked:{oid}")
        kb.button(text="❌ Не забрав", callback_data=f"adm:order:not_picked:{oid}")
        kb.button(text="🔁 Повернуто", callback_data=f"adm:order:returned:{oid}")

    # історія покупця
    kb.button(text="📜 Історія покупця", callback_data=f"adm:order:history:{oid}")

    kb.adjust(1)
    return kb.as_markup()

# -------------------- PANEL (ONE MESSAGE) --------------------

def panel_main_kb(uid: int) -> types.InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🧩 Каталог", callback_data="adm:panel:catalog")
    kb.button(text="📑 Замовлення", callback_data="adm:panel:orders")
    kb.button(text="⚙️ Налаштування", callback_data="adm:panel:settings")
    kb.adjust(1)
    return kb.as_markup()


def panel_catalog_kb() -> types.InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="📦 Товари", callback_data="adm:panel:products")
    kb.button(text="🗂 Категорії/Підкатегорії", callback_data="adm:panel:cats")
    kb.button(text="➕ Додати товар", callback_data="adm:panel:add_product")
    kb.button(text="⬅️ Назад", callback_data="adm:panel:back")
    kb.adjust(1)
    return kb.as_markup()


def panel_orders_kb() -> types.InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="📋 Нові (оплачені)", callback_data="adm:panel:orders_paid")
    kb.button(text="📦 Усі замовлення", callback_data="adm:panel:orders_all")

    # ✅ додали пошук покупця в панель
    kb.button(text="🔎 Пошук покупця", callback_data="adm:panel:buyer_search")

    kb.button(text="⬅️ Назад", callback_data="adm:panel:back")
    kb.adjust(1)
    return kb.as_markup()


def panel_settings_kb(uid: int) -> types.InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if is_admin(uid):
        kb.button(text="👤 Додати менеджера", callback_data="adm:panel:add_manager")
    kb.button(text="⬅️ Назад", callback_data="adm:panel:back")
    kb.adjust(1)
    return kb.as_markup()
# -------------------- COMMON --------------------

@router.message(Command("admin"))
async def admin_cmd(m: types.Message, state: FSMContext):
    d = await load_data()
    if not is_staff(d, m.from_user.id):
        return await m.answer("⛔️ Немає доступу")
    await state.clear()
    await m.answer(
    "🔧 <b>Панель</b>\nОберіть розділ:",
    parse_mode="HTML",
    reply_markup=panel_main_kb(m.from_user.id)
)


@router.message(F.text == "❌ Відміна")
async def cancel_any(m: types.Message, state: FSMContext):
    d = await load_data()
    if not is_staff(d, m.from_user.id):
        return await m.answer("⛔️ Немає доступу")
    await state.clear()
    await m.answer("Скасовано.", reply_markup=staff_menu(m.from_user.id))


@router.callback_query(F.data == "adm:cancel")
async def cancel_cb(cb: types.CallbackQuery, state: FSMContext):
    d = await load_data()
    if not is_staff(d, cb.from_user.id):
        return await cb.answer("Немає доступу", show_alert=True)

    await state.clear()

    # ✅ Повертаємося в компактну панель одним повідомленням
    await cb.message.answer(
        "🔧 Панель (Адмін/Менеджер)",
        reply_markup=panel_main_kb(cb.from_user.id)
    )
    await cb.answer()


# -------------------- PANEL NAV --------------------

@router.callback_query(F.data.startswith("adm:panel:"))
async def panel_nav(cb: types.CallbackQuery, state: FSMContext):
    d = await load_data()
    if not is_staff(d, cb.from_user.id):
        return await cb.answer("Немає доступу", show_alert=True)

    await state.clear()

    action = cb.data.split(":")[2]

    # головна
    if action in ("back", "main"):
        await cb.message.answer("🔧 Панель (Адмін/Менеджер)", reply_markup=panel_main_kb(cb.from_user.id))
        return await cb.answer()

    # розділи
    if action == "catalog":
        await cb.message.answer("🧩 Каталог:", reply_markup=panel_catalog_kb())
        return await cb.answer()

    if action == "orders":
        await cb.message.answer("📑 Замовлення:", reply_markup=panel_orders_kb())
        return await cb.answer()

    if action == "settings":
        await cb.message.answer("⚙️ Налаштування:", reply_markup=panel_settings_kb(cb.from_user.id))
        return await cb.answer()

    # дії (робимо як “перекидання” в існуючі сценарії)
    if action == "cats":
        await cb.message.answer("Оберіть категорію:", reply_markup=await cats_inline("catmgmt"))
        return await cb.answer()

    if action == "products":
        await cb.message.answer("Оберіть категорію:", reply_markup=await cats_inline("plist_cat"))
        return await cb.answer()

    if action == "add_product":
        await state.set_state(AdminFSM.prod_cat)
        await cb.message.answer("Оберіть категорію:", reply_markup=await cats_inline("prod_cat"))
        return await cb.answer()

    if action == "orders_paid":
        # дублюємо логіку "📋 Нові (оплачені)" але через callback
        paid = [o for o in (d.get("orders", []) or []) if o.get("status") in ("paid", "prepay")]
        if not paid:
            await cb.message.answer("Немає нових оплачених/передплачених замовлень.")
            return await cb.answer()

        for o in paid:
            products = _order_products(d, o)
            await cb.message.answer(
                order_premium_text(d, o, products),
                parse_mode="HTML",
                reply_markup=order_actions_kb(int(o["id"]), str(o.get("status", "")))
            )
        return await cb.answer()

    if action == "orders_all":
        orders = d.get("orders", []) or []
        if not orders:
            await cb.message.answer("Замовлень ще немає.")
            return await cb.answer()

        for o in reversed(orders):
            products = _order_products(d, o)
            await cb.message.answer(
                order_premium_text(d, o, products),
                parse_mode="HTML",
                reply_markup=order_actions_kb(int(o["id"]), str(o.get("status", "")))
            )
        return await cb.answer()

        if action == "buyer_search":
        await state.set_state(AdminFSM.search_buyer)
        await cb.message.answer(
            "🔎 <b>Пошук покупця</b>\n\n"
            "Введіть одне з:\n"
            "• ID (число)\n"
            "• @username\n"
            "• частину імені\n\n"
            "Приклад: 123456789 або @katas або Віктор",
            parse_mode="HTML"
        )
        return await cb.answer()

    if action == "add_manager":
        if not is_admin(cb.from_user.id):
            return await cb.answer("⛔️ Тільки адмін", show_alert=True)
        await state.set_state(AdminFSM.add_manager)
        await cb.message.answer("Введіть ID менеджера (число):")
        return await cb.answer()

    return await cb.answer("Невідома дія", show_alert=True)


# -------------------- ORDERS --------------------

@router.message(F.text == "📋 Нові (оплачені)")
async def orders_paid(m: types.Message):
    d = await load_data()
    if not is_staff(d, m.from_user.id):
        return await m.answer("⛔️ Немає доступу")

    paid = [o for o in (d.get("orders", []) or []) if o.get("status") in ("paid", "prepay")]
    if not paid:
        return await m.answer("Немає нових оплачених/передплачених замовлень.")

    for o in paid:
        products = _order_products(d, o)
        await m.answer(
            order_premium_text(d, o, products),
            parse_mode="HTML",
            reply_markup=order_actions_kb(int(o["id"]), str(o.get("status", "")))
        )


@router.message(F.text == "📦 Усі замовлення")
async def orders_all(m: types.Message):
    d = await load_data()
    if not is_staff(d, m.from_user.id):
        return await m.answer("⛔️ Немає доступу")

    orders = d.get("orders", []) or []
    if not orders:
        return await m.answer("Замовлень ще немає.")

    for o in reversed(orders):
        products = _order_products(d, o)
        await m.answer(
            order_premium_text(d, o, products),
            parse_mode="HTML",
            reply_markup=order_actions_kb(int(o["id"]), str(o.get("status", "")))
        )


@router.callback_query(F.data.startswith("adm:order:"))
async def order_change_status(cb: types.CallbackQuery):
    d = await load_data()
    if not is_staff(d, cb.from_user.id):
        return await cb.answer("Немає доступу", show_alert=True)

    _, _, action, oid_str = cb.data.split(":")
    oid = int(oid_str)

    order = next((o for o in (d.get("orders", []) or []) if int(o.get("id", -1)) == oid), None)
    if not order:
        await cb.message.answer("❌ Замовлення не знайдено.")
        return await cb.answer()

    def _reply_updated(prefix_text: str):
        # показуємо оновлену карточку замовлення з кнопками
        products = _order_products(d, order)
        return cb.message.answer(
            prefix_text + "\n\n" + order_premium_text(d, order, products),
            parse_mode="HTML",
            reply_markup=order_actions_kb(oid, str(order.get("status", "")))
        )

    # ---- стандартні ----
    if action == "in_work":
        if order.get("status") not in ("paid", "prepay"):
            return await cb.answer("Тільки paid/prepay можна взяти в роботу", show_alert=True)
        order["status"] = "in_work"
        await save_data(d)
        await _reply_updated(f"🟡 Замовлення #{oid} взято в роботу.")
        return await cb.answer()

    if action == "done":
        if order.get("status") not in ("paid", "prepay", "in_work", "shipped"):
            return await cb.answer("Неможливо завершити", show_alert=True)
        order["status"] = "done"
        await save_data(d)
        await _reply_updated(f"✅ Замовлення #{oid} завершено.")
        return await cb.answer()

    # ---- логістика ----
    if action == "shipped":
        if order.get("status") not in ("paid", "prepay", "in_work", "shipped"):
            return await cb.answer("Неможливо позначити як відправлено", show_alert=True)
        order["status"] = "shipped"
        await save_data(d)
        await _reply_updated(f"🚚 Замовлення #{oid} позначено як ВІДПРАВЛЕНО.")
        return await cb.answer()

    if action == "picked":
        if order.get("status") != "shipped":
            return await cb.answer("Спочатку треба 'Відправлено'", show_alert=True)
        order["status"] = "picked"
        await save_data(d)
        await _reply_updated(f"✅ Замовлення #{oid}: клієнт ЗАБРАВ (продано).")
        return await cb.answer()

    if action == "not_picked":
        if order.get("status") != "shipped":
            return await cb.answer("Це доречно тільки після 'Відправлено'", show_alert=True)
        order["status"] = "not_picked"
        await save_data(d)
        await _reply_updated(f"❌ Замовлення #{oid}: НЕ ЗАБРАВ.")
        return await cb.answer()

    if action == "returned":
        if order.get("status") not in ("shipped", "not_picked", "picked"):
            return await cb.answer("Повернення ставимо після логістики", show_alert=True)
        order["status"] = "returned"
        await save_data(d)
        await _reply_updated(f"🔁 Замовлення #{oid}: ПОВЕРНУТО.")
        return await cb.answer()

    # ---- історія покупця ----
    if action == "history":
        uid = int(order.get("user_id", 0) or 0)
        if not uid:
            await cb.message.answer("❌ У замовлення немає user_id.")
            return await cb.answer()

        user_orders = [o for o in (d.get("orders", []) or []) if int(o.get("user_id", -1)) == uid]
        if not user_orders:
            await cb.message.answer("Історія порожня.")
            return await cb.answer()

        user_link = f'<a href="tg://user?id={uid}">👤 Покупець</a>'
        await cb.message.answer(user_link + "\n<b>📜 Історія замовлень покупця:</b>", parse_mode="HTML")

        for o in reversed(user_orders):
            products = _order_products(d, o)
            await cb.message.answer(
                order_premium_text(d, o, products),
                parse_mode="HTML",
                reply_markup=order_actions_kb(int(o["id"]), str(o.get("status", "")))
            )
        return await cb.answer()

    return await cb.answer("Невідома дія", show_alert=True)

# -------------------- BUYER SEARCH --------------------

@router.message(F.text == "🔎 Пошук покупця")
async def buyer_search_btn(m: types.Message, state: FSMContext):
    d = await load_data()
    if not is_staff(d, m.from_user.id):
        return await m.answer("⛔️ Немає доступу")

    await state.clear()
    await state.set_state(AdminFSM.search_buyer)
    await m.answer(
        "🔎 Пошук покупця\n\n"
        "Введіть одне з:\n"
        "• ID (число)\n"
        "• @username\n"
        "• частину імені\n\n"
        "Приклад: 123456789 або @katas або Віктор",
        reply_markup=staff_menu(m.from_user.id)
    )


@router.message(AdminFSM.search_buyer)
async def buyer_search_run(m: types.Message, state: FSMContext):
    d = await load_data()
    if not is_staff(d, m.from_user.id):
        return await m.answer("⛔️ Немає доступу")

    q = (m.text or "").strip()
    if not q:
        return await m.answer("Введіть ID / @username / ім’я.")

    orders = d.get("orders", []) or []

    # 1) якщо число — шукаємо по user_id
    uid = None
    if q.isdigit():
        uid = int(q)

    # 2) якщо @username
    uname = q[1:].lower() if q.startswith("@") else None

    # підбираємо кандидатів по замовленнях
    matches = []
    for o in orders:
        ouid = int(o.get("user_id", 0) or 0)
        ouname = str(o.get("user_username", "") or "")
        ofull = str(o.get("user_full_name", "") or "")

        if uid is not None and ouid == uid:
            matches.append(o)
            continue

        if uname is not None and ouname.lower() == uname:
            matches.append(o)
            continue

        if uid is None and uname is None:
            # пошук по імені/юзернейму частково
            if q.lower() in ofull.lower() or q.lower() in ouname.lower():
                matches.append(o)

    if not matches:
        await state.clear()
        return await m.answer("❌ Нічого не знайдено.", reply_markup=staff_menu(m.from_user.id))

    # групуємо по user_id (щоб не показувати 20 однакових)
    by_user = {}
    for o in matches:
        by_user.setdefault(int(o.get("user_id", 0) or 0), []).append(o)

    # показуємо короткий список знайдених покупців
    await m.answer(f"✅ Знайдено покупців: {len(by_user)}\n")

    for u, u_orders in by_user.items():
        # беремо останнє замовлення для інфо
        last = sorted(u_orders, key=lambda x: int(x.get("id", 0)), reverse=True)[0]
        uname2 = (last.get("user_username") or "")
        full2 = (last.get("user_full_name") or "")
        uname_show = f"@{uname2}" if uname2 else "—"

        # лінк на юзера
        user_link = f'<a href="tg://user?id={u}">👤 покупець</a>'

        await m.answer(
            f"{user_link}\n"
            f"<b>{full2}</b>\n"
            f"ID: <code>{u}</code>\n"
            f"Username: {uname_show}\n"
            f"Замовлень (знайдено): {len(u_orders)}\n\n"
            f"Щоб показати історію — натисни «📜 Історія покупця» в будь-якому замовленні цього юзера "
            f"(або введи його ID ще раз і я виведу всі замовлення).",
            parse_mode="HTML"
        )

    await state.clear()
    await m.answer("Готово ✅", reply_markup=staff_menu(m.from_user.id))
    
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

    d = await load_data()
    d.setdefault("managers", [])
    if uid not in d["managers"]:
        d["managers"].append(uid)
        await save_data(d)

    await state.clear()
    await m.answer(f"✅ Менеджера додано: {uid}", reply_markup=staff_menu(m.from_user.id))


# -------------------- BUYER SEARCH --------------------

def _norm(s: str) -> str:
    return (s or "").strip().lower()

def _match_user_record(u: dict, q: str) -> bool:
    q = _norm(q)
    if not q:
        return False

    uid = str(u.get("id", "") or "")
    username = _norm(u.get("username", "") or "")
    full_name = _norm(u.get("full_name", "") or "")

    # якщо ввели цифри — шукаємо по id
    if q.isdigit():
        return q in uid

    # якщо ввели @username або просто username
    q2 = q[1:] if q.startswith("@") else q
    return (q2 and q2 in username) or (q in full_name)

def _user_brief(u: dict) -> str:
    uid = int(u.get("id", 0) or 0)
    username = (u.get("username") or "").strip()
    full_name = (u.get("full_name") or "").strip()

    user_link = f'<a href="tg://user?id={uid}">👤 Покупець</a>'
    uname_show = f"@{username}" if username else "—"

    return (
        f"{user_link}\n"
        f"<b>{full_name or '—'}</b>\n"
        f"ID: <code>{uid}</code>\n"
        f"Username: {uname_show}"
    )

def _orders_of_user(d: dict, uid: int) -> list[dict]:
    return [o for o in (d.get("orders", []) or []) if int(o.get("user_id", -1)) == int(uid)]

@router.message(F.text == "🔎 Пошук покупця")
async def buyer_search_btn(m: types.Message, state: FSMContext):
    d = await load_data()
    if not is_staff(d, m.from_user.id):
        return await m.answer("⛔️ Немає доступу")

    await state.clear()
    await state.set_state(AdminFSM.search_buyer)

    await m.answer(
        "🔎 <b>Пошук покупця</b>\n\n"
        "Введіть одне з:\n"
        "• ID (число)\n"
        "• @username\n"
        "• частину імені\n\n"
        "Приклад: <code>123456789</code> або <code>@katas</code> або <code>Віктор</code>",
        parse_mode="HTML",
        reply_markup=staff_menu(m.from_user.id)
    )

@router.message(AdminFSM.search_buyer)
async def buyer_search_run(m: types.Message, state: FSMContext):
    d = await load_data()
    if not is_staff(d, m.from_user.id):
        return await m.answer("⛔️ Немає доступу")

    q = (m.text or "").strip()
    if not q:
        return await m.answer("Введіть ID / @username / ім’я.")

    users = list((d.get("users", {}) or {}).values())

    # 1) спочатку шукаємо по users (кращий варіант, бо це всі хто натискав /start або писав)
    found_users = [u for u in users if _match_user_record(u, q)]

    # 2) якщо users пусті або нікого не знайшли — fallback на замовлення
    if not found_users:
        # по замовленнях шукаємо: user_id, user_username, user_full_name
        qn = _norm(q)
        qn2 = qn[1:] if qn.startswith("@") else qn

        cand_uids: set[int] = set()
        for o in (d.get("orders", []) or []):
            ouid = int(o.get("user_id", 0) or 0)
            ouname = _norm(o.get("user_username", "") or "")
            ofull = _norm(o.get("user_full_name", "") or "")

            if qn.isdigit() and int(qn) == ouid:
                cand_uids.add(ouid)
            elif qn.startswith("@") and qn2 and ouname == qn2:
                cand_uids.add(ouid)
            else:
                if qn and (qn in ofull or qn in ouname):
                    cand_uids.add(ouid)

        # формуємо "віртуальні" user-записи з замовлень
        for uid in cand_uids:
            last = None
            for o in reversed(d.get("orders", []) or []):
                if int(o.get("user_id", 0) or 0) == uid:
                    last = o
                    break
            found_users.append({
                "id": uid,
                "username": (last.get("user_username") if last else "") or "",
                "full_name": (last.get("user_full_name") if last else "") or "",
            })

    if not found_users:
        await state.clear()
        return await m.answer("❌ Нічого не знайдено.", reply_markup=staff_menu(m.from_user.id))

    # якщо знайшло багато — покажемо максимум 10, щоб не спамити
    found_users = found_users[:10]

    await m.answer(f"✅ Знайдено: <b>{len(found_users)}</b>", parse_mode="HTML")

    for u in found_users:
        uid = int(u.get("id", 0) or 0)
        u_orders = _orders_of_user(d, uid)

        await m.answer(
            _user_brief(u) + f"\nЗамовлень: <b>{len(u_orders)}</b>\n\n"
            "Щоб подивитись деталі — введи ID ще раз (я покажу всі його замовлення нижче).",
            parse_mode="HTML"
        )

        # якщо запит був прям ID — одразу покажемо історію (щоб було “вау”)
        if q.strip().isdigit() and int(q.strip()) == uid:
            if not u_orders:
                await m.answer("📭 У цього покупця ще немає замовлень.")
            else:
                await m.answer("📜 <b>Історія замовлень:</b>", parse_mode="HTML")
                for o in reversed(u_orders):
                    products = _order_products(d, o)
                    await m.answer(
                        order_premium_text(d, o, products),
                        parse_mode="HTML",
                        reply_markup=order_actions_kb(int(o["id"]), str(o.get("status", "")))
                    )

    await state.clear()
    await m.answer("Готово ✅", reply_markup=staff_menu(m.from_user.id))


# -------------------- ADD CATEGORY --------------------

@router.message(F.text == "➕ Додати категорію")
async def add_cat_btn(m: types.Message, state: FSMContext):
    d = await load_data()
    if not is_staff(d, m.from_user.id):
        return await m.answer("⛔️ Немає доступу")
    await state.clear()
    await state.set_state(AdminFSM.add_cat)
    await m.answer("Введіть назву категорії:")


@router.message(AdminFSM.add_cat)
async def add_cat_name(m: types.Message, state: FSMContext):
    d = await load_data()
    if not is_staff(d, m.from_user.id):
        return await m.answer("⛔️ Немає доступу")

    name = (m.text or "").strip()
    if not name:
        return await m.answer("Введіть назву текстом.")

    d.setdefault("categories", {})
    d["categories"].setdefault(name, {})
    await save_data(d)

    await state.clear()
    await m.answer(f"✅ Категорію «{name}» додано.", reply_markup=staff_menu(m.from_user.id))


# -------------------- ADD SUBCATEGORY --------------------

@router.message(F.text == "➕ Додати підкатегорію")
async def add_sub_btn(m: types.Message, state: FSMContext):
    d = await load_data()
    if not is_staff(d, m.from_user.id):
        return await m.answer("⛔️ Немає доступу")

    if not d.get("categories"):
        return await m.answer("Спочатку додайте категорію.")

    await state.clear()
    await state.set_state(AdminFSM.add_sub_cat)
    await m.answer("Оберіть категорію:", reply_markup=await cats_inline("sub_add"))


@router.callback_query(F.data.startswith("adm:sub_add:cat:"))
async def pick_cat_for_sub(cb: types.CallbackQuery, state: FSMContext):
    d = await load_data()
    if not is_staff(d, cb.from_user.id):
        return await cb.answer("Немає доступу", show_alert=True)

    cat = cb.data.split(":")[3]
    await state.update_data(cat=cat)
    await state.set_state(AdminFSM.add_sub_name)
    await cb.message.answer(f"Введіть назву підкатегорії для «{cat}»:")
    await cb.answer()


@router.message(AdminFSM.add_sub_name)
async def add_sub_name(m: types.Message, state: FSMContext):
    d = await load_data()
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

    d.setdefault("categories", {})
    d["categories"].setdefault(cat, {})
    d["categories"][cat].setdefault(sub, [])
    await save_data(d)

    await state.clear()
    await m.answer(f"✅ Підкатегорію «{sub}» додано в «{cat}».", reply_markup=staff_menu(m.from_user.id))


# -------------------- CATEGORY / SUBCATEGORY MGMT (DELETE) --------------------

@router.message(F.text == "🗂 Категорії/Підкатегорії")
async def cat_mgmt(m: types.Message):
    d = await load_data()
    if not is_staff(d, m.from_user.id):
        return await m.answer("⛔️ Немає доступу")

    if not d.get("categories"):
        return await m.answer("Категорій ще немає.")

    await m.answer("Оберіть категорію:", reply_markup=await cats_inline("catmgmt"))


@router.callback_query(F.data.startswith("adm:catmgmt:cat:"))
async def catmgmt_pick(cb: types.CallbackQuery):
    d = await load_data()
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
    d = await load_data()
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
    d = await load_data()
    if not is_staff(d, cb.from_user.id):
        return await cb.answer("Немає доступу", show_alert=True)

    cat = cb.data.split(":")[2]
    if cat in (d.get("categories", {}) or {}):
        hits = _hits_set(d)
        for _, items in (d["categories"].get(cat, {}) or {}).items():
            for p in items:
                hits.discard(int(p.get("id", -1)))
        d["hits"] = list(hits)

        del d["categories"][cat]
        await save_data(d)
        await cb.message.answer(f"✅ Категорію «{cat}» видалено.")
    else:
        await cb.message.answer("❌ Категорію не знайдено.")
    await cb.answer()


@router.callback_query(F.data.startswith("adm:subdelpick:"))
async def sub_del_pick(cb: types.CallbackQuery):
    d = await load_data()
    if not is_staff(d, cb.from_user.id):
        return await cb.answer("Немає доступу", show_alert=True)

    cat = cb.data.split(":")[2]
    subs = (d.get("categories", {}) or {}).get(cat, {}) or {}
    real = [s for s in subs.keys() if s != NO_SUB]
    if not real:
        await cb.message.answer("У цій категорії немає підкатегорій.")
        return await cb.answer()

    await cb.message.answer(
        "Оберіть підкатегорію:",
        reply_markup=await subs_inline(cat, "subdelask", include_no_sub=False)
    )
    await cb.answer()


@router.callback_query(F.data.startswith("adm:subdelask:sub:"))
async def sub_del_ask(cb: types.CallbackQuery):
    d = await load_data()
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
    d = await load_data()
    if not is_staff(d, cb.from_user.id):
        return await cb.answer("Немає доступу", show_alert=True)

    _, _, cat, sub = cb.data.split(":")
    if cat in (d.get("categories", {}) or {}) and sub in (d["categories"].get(cat, {}) or {}):
        hits = _hits_set(d)
        for p in d["categories"][cat][sub]:
            hits.discard(int(p.get("id", -1)))
        d["hits"] = list(hits)

        del d["categories"][cat][sub]
        await save_data(d)
        await cb.message.answer(f"✅ Підкатегорію «{sub}» видалено.")
    else:
        await cb.message.answer("❌ Підкатегорію не знайдено.")
    await cb.answer()


# -------------------- ADD PRODUCT (NO SUB OK) --------------------

@router.message(F.text == "➕ Додати товар")
async def add_product_btn(m: types.Message, state: FSMContext):
    d = await load_data()
    if not is_staff(d, m.from_user.id):
        return await m.answer("⛔️ Немає доступу")

    if not d.get("categories"):
        return await m.answer("Спочатку додайте категорію.")

    await state.clear()
    await state.set_state(AdminFSM.prod_cat)
    await m.answer("Оберіть категорію:", reply_markup=await cats_inline("prod_cat"))


@router.callback_query(F.data.startswith("adm:prod_cat:cat:"))
async def prod_pick_cat(cb: types.CallbackQuery, state: FSMContext):
    d = await load_data()
    if not is_staff(d, cb.from_user.id):
        return await cb.answer("Немає доступу", show_alert=True)

    cat = cb.data.split(":")[3]
    await state.update_data(cat=cat)

    await state.set_state(AdminFSM.prod_sub)
    await cb.message.answer(
        "Оберіть підкатегорію або 🧷 Утлет:",
        reply_markup=await subs_inline(cat, "prod_sub", include_no_sub=True)
    )
    await cb.answer()


@router.callback_query(F.data.startswith("adm:prod_sub:sub:"))
async def prod_pick_sub(cb: types.CallbackQuery, state: FSMContext):
    d = await load_data()
    if not is_staff(d, cb.from_user.id):
        return await cb.answer("Немає доступу", show_alert=True)

    _, _, _, cat, sub = cb.data.split(":")
    await state.update_data(cat=cat, sub=sub)

    await state.set_state(AdminFSM.prod_name)
    await cb.message.answer("Введіть назву товару:")
    await cb.answer()


@router.message(AdminFSM.prod_name)
async def prod_name(m: types.Message, state: FSMContext):
    d = await load_data()
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
    d = await load_data()
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
    d = await load_data()
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
    d = await load_data()
    if not is_staff(d, m.from_user.id):
        return await m.answer("⛔️ Немає доступу")

    st = await state.get_data()
    photos = st.get("photos", [])
    photos.append(m.photo[-1].file_id)
    await state.update_data(photos=photos)
    await m.answer("📸 Фото додано. Ще фото або напишіть: ГОТОВО")


@router.message(AdminFSM.prod_photos)
async def prod_done(m: types.Message, state: FSMContext):
    d = await load_data()
    if not is_staff(d, m.from_user.id):
        return await m.answer("⛔️ Немає доступу")

    if (m.text or "").strip().lower() not in ("готово", "готов", "done", "ok"):
        return await m.answer("Надішліть фото або напишіть: ГОТОВО")

    st = await state.get_data()
    cat = st["cat"]
    sub = st["sub"]

    d = await load_data()
    pid = next_product_id(d)

    d.setdefault("categories", {})
    d["categories"].setdefault(cat, {})
    d["categories"][cat].setdefault(sub, [])

    price = float(st["price"])
    product = {
        "id": pid,
        "name": st["name"],
        "price": price,
        "base_price": price,
        "promo_price": 0,
        "promo_until_ts": None,
        "description": st.get("description", ""),
        "photos": st.get("photos", []),
    }

    d["categories"][cat][sub].append(product)
    await save_data(d)

    await state.clear()
    await m.answer(f"✅ Товар додано: {product['name']} (ID: {pid})", reply_markup=staff_menu(m.from_user.id))

# ======= END OF PART 1 =======
# -------------------- PRODUCTS LIST / EDIT / DELETE --------------------

@router.message(F.text == "🛠 Товари")
async def products_btn(m: types.Message):
    d = await load_data()
    if not is_staff(d, m.from_user.id):
        return await m.answer("⛔️ Немає доступу")

    if not d.get("categories"):
        return await m.answer("Категорій немає.")

    await m.answer("Оберіть категорію:", reply_markup=await cats_inline("plist_cat"))


@router.callback_query(F.data.startswith("adm:plist_cat:cat:"))
async def plist_pick_cat(cb: types.CallbackQuery):
    d = await load_data()
    if not is_staff(d, cb.from_user.id):
        return await cb.answer("Немає доступу", show_alert=True)

    cat = cb.data.split(":")[3]
    subs = d.get("categories", {}).get(cat, {})
    if not subs:
        await cb.message.answer("У категорії немає підкатегорій/товарів.")
        return await cb.answer()

    await cb.message.answer(
        "Оберіть підкатегорію (або 🧷 Утлет):",
        reply_markup=await subs_inline(cat, "plist_sub", include_no_sub=True)
    )
    await cb.answer()


@router.callback_query(F.data.startswith("adm:plist_sub:sub:"))
async def plist_pick_sub(cb: types.CallbackQuery):
    d = await load_data()
    if not is_staff(d, cb.from_user.id):
        return await cb.answer("Немає доступу", show_alert=True)

    _, _, _, cat, sub = cb.data.split(":")
    items = d.get("categories", {}).get(cat, {}).get(sub, [])
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
                reply_markup=await product_actions_kb(int(p["id"]))
            )
        else:
            await cb.message.answer(
                txt,
                parse_mode="HTML",
                reply_markup=await product_actions_kb(int(p["id"]))
            )

    await cb.answer()


# -------------------- HITS --------------------

@router.callback_query(F.data.startswith("adm:hit:"))
async def toggle_hit(cb: types.CallbackQuery):
    d = await load_data()
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
    await save_data(d)

    await cb.message.answer("✅ Оновлено (Хіти/Акції).")


# -------------------- DELETE PRODUCT --------------------

@router.callback_query(F.data.startswith("adm:delask:"))
async def product_del_ask(cb: types.CallbackQuery):
    d = await load_data()
    if not is_staff(d, cb.from_user.id):
        return await cb.answer("Немає доступу", show_alert=True)

    pid = int(cb.data.split(":")[2])
    p = find_product(d, pid)
    name = p["name"] if p else f"#{pid}"
    await cb.message.answer(
        f"⚠️ Видалити товар {name}?",
        reply_markup=confirm_product_delete_kb(pid)
    )
    await cb.answer()


@router.callback_query(F.data.startswith("adm:del:"))
async def product_del(cb: types.CallbackQuery):
    d = await load_data()
    if not is_staff(d, cb.from_user.id):
        return await cb.answer("Немає доступу", show_alert=True)

    pid = int(cb.data.split(":")[2])
    deleted = False

    for cat in d.get("categories", {}).values():
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
        await save_data(d)
        await cb.message.answer("✅ Товар видалено.")
    else:
        await cb.message.answer("❌ Товар не знайдено.")
    await cb.answer()


# -------------------- EDIT PRODUCT --------------------

@router.callback_query(F.data.startswith("adm:editmenu:"))
async def edit_menu(cb: types.CallbackQuery, state: FSMContext):
    d = await load_data()
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
    d = await load_data()
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
        await save_data(d)
        await cb.message.answer("✅ Акцію прибрано.", reply_markup=staff_menu(cb.from_user.id))

    await cb.answer()


@router.message(EditProductFSM.name)
async def edit_name(m: types.Message, state: FSMContext):
    d = await load_data()
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
    await save_data(d)
    await state.clear()
    await m.answer("✅ Назву оновлено.", reply_markup=staff_menu(m.from_user.id))


@router.message(EditProductFSM.price)
async def edit_price(m: types.Message, state: FSMContext):
    d = await load_data()
    if not is_staff(d, m.from_user.id):
        return await m.answer("⛔️ Немає доступу")

    st = await state.get_data()
    pid = st.get("pid")
    p = find_product(d, pid)
    if not p:
        await state.clear()
        return await m.answer("❌ Товар не знайдено.")

    _ensure_product_schema(p)

    try:
        price = float((m.text or "").replace(",", "."))
    except Exception:
        return await m.answer("Введіть число (наприклад 199.99).")

    p["base_price"] = price
    p["price"] = price
    await save_data(d)

    await state.clear()
    await m.answer("✅ Ціну оновлено.", reply_markup=staff_menu(m.from_user.id))


@router.message(EditProductFSM.desc)
async def edit_desc(m: types.Message, state: FSMContext):
    d = await load_data()
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
    await save_data(d)

    await state.clear()
    await m.answer("✅ Опис оновлено.", reply_markup=staff_menu(m.from_user.id))


# -------- PROMO FLOW --------

@router.message(EditProductFSM.promo_price)
async def edit_promo_price(m: types.Message, state: FSMContext):
    d = await load_data()
    if not is_staff(d, m.from_user.id):
        return await m.answer("⛔️ Немає доступу")

    st = await state.get_data()
    pid = st.get("pid")
    p = find_product(d, pid)
    if not p:
        await state.clear()
        return await m.answer("❌ Товар не знайдено.")

    _ensure_product_schema(p)

    try:
        promo = float((m.text or "").replace(",", "."))
    except Exception:
        return await m.answer("Введіть число (наприклад 1499.99).")

    if promo <= 0:
        return await m.answer("Акційна ціна має бути > 0.")

    p["promo_price"] = promo
    await save_data(d)

    await state.set_state(EditProductFSM.promo_until)
    await m.answer(
        "Вкажіть дату завершення акції:\n"
        "<b>YYYY-MM-DD</b> або <b>YYYY-MM-DD HH:MM</b>\n"
        "Або <b>-</b> без дати.",
        parse_mode="HTML"
    )


@router.message(EditProductFSM.promo_until)
async def edit_promo_until(m: types.Message, state: FSMContext):
    d = await load_data()
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
        await save_data(d)
        await state.clear()
        return await m.answer("✅ Акцію встановлено (без дати).", reply_markup=staff_menu(m.from_user.id))

    try:
        if len(txt) == 10:
            dt = datetime.strptime(txt, "%Y-%m-%d")
        else:
            dt = datetime.strptime(txt, "%Y-%m-%d %H:%M")
        ts = int(dt.replace(tzinfo=timezone.utc).timestamp())
    except Exception:
        return await m.answer(
            "❌ Невірний формат.\n"
            "• 2026-01-20\n"
            "• 2026-01-20 23:59\n"
            "• або '-'"
        )

    p["promo_until_ts"] = ts
    await save_data(d)

    await state.clear()
    await m.answer("✅ Акцію встановлено.", reply_markup=staff_menu(m.from_user.id))


# ==================== END OF FILE ====================