# handlers/admin.py
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from aiogram import Router, types, F, Bot
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder

from data import load_data, save_data, next_product_id, find_product
from states import AdminFSM, EditProductFSM
from utils import is_admin, is_staff, notify_user, format_order_text
from text import order_premium_text, product_card

router = Router()

NO_SUB = "_"  # системна підкатегорія (в UI показуємо як "🧷 Утлет")


# =========================================================
# NOTIFY BUYER
# =========================================================

async def _notify_buyer(bot: Bot, d: dict, order: dict, title: str):
    uid = int(order.get("user_id", 0) or 0)
    if not uid:
        return
    txt = title + "\n\n" + format_order_text(d, order)
    await notify_user(bot, uid, txt, parse_mode="HTML")


# =========================================================
# SMALL HELPERS
# =========================================================

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
    """Захист від старих товарів без полів base_price/promo_* та sku/barcode."""
    if "base_price" not in p:
        p["base_price"] = p.get("price", 0) or 0
    if "price" not in p:
        p["price"] = p.get("base_price", 0) or 0
    if "promo_price" not in p:
        p["promo_price"] = 0
    if "promo_until_ts" not in p:
        p["promo_until_ts"] = None
    if "sku" not in p:
        p["sku"] = ""
    if "barcode" not in p:
        p["barcode"] = ""


def _order_products(d: dict, o: dict) -> list[dict]:
    """
    items може бути:
    - [pid, pid, ...] (старий)
    - [{"pid": 12, "qty": 2}, ...] (новий)
    Повертаємо список product dict, додаючи _qty для відображення.
    """
    products: list[dict] = []
    for it in (o.get("items", []) or []):
        pid_int = None
        qty = 1

        if isinstance(it, dict):
            try:
                pid_int = int(it.get("pid"))
                qty = int(it.get("qty", 1) or 1)
            except Exception:
                continue
        else:
            try:
                pid_int = int(it)
                qty = 1
            except Exception:
                continue

        p = find_product(d, pid_int)
        if p:
            _ensure_product_schema(p)
            pp = dict(p)
            pp["_qty"] = max(1, qty)
            products.append(pp)
    return products


async def _cat_by_index(cat_i: int) -> str | None:
    d = await load_data()
    cats = list((d.get("categories", {}) or {}).keys())
    if 0 <= cat_i < len(cats):
        return cats[cat_i]
    return None


async def _sub_by_index(cat_i: int, sub_i: str) -> str | None:
    cat = await _cat_by_index(cat_i)
    if not cat:
        return None

    d = await load_data()
    subs = (d.get("categories", {}) or {}).get(cat, {}) or {}
    subs_list = [s for s in subs.keys() if s != NO_SUB]

    if sub_i == "n":
        return NO_SUB

    try:
        j = int(sub_i)
    except Exception:
        return None

    if 0 <= j < len(subs_list):
        return subs_list[j]
    return None


# =========================================================
# MENUS / INLINE KB
# =========================================================

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
    cats = list((d.get("categories", {}) or {}).keys())

    kb = InlineKeyboardBuilder()
    for i, c in enumerate(cats):
        kb.button(text=str(c), callback_data=f"adm:{action}:cat_i:{i}")
    kb.adjust(2)
    return kb.as_markup()


async def subs_inline(cat_i: int, action: str, include_no_sub: bool = False) -> types.InlineKeyboardMarkup:
    d = await load_data()
    cats = list((d.get("categories", {}) or {}).keys())
    if cat_i < 0 or cat_i >= len(cats):
        return InlineKeyboardBuilder().as_markup()

    cat = cats[cat_i]
    subs = (d.get("categories", {}) or {}).get(cat, {}) or {}
    subs_list = [s for s in subs.keys() if s != NO_SUB]

    kb = InlineKeyboardBuilder()

    if include_no_sub:
        kb.button(text="🧷 Утлет", callback_data=f"adm:{action}:sub_i:{cat_i}:n")

    for j, s in enumerate(subs_list):
        kb.button(text=str(s), callback_data=f"adm:{action}:sub_i:{cat_i}:{j}")

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

    kb.button(text="🏷 Акційна ціна", callback_data=f"adm:edit:promo:{pid}")
    kb.button(text="🧹 Прибрати акцію", callback_data=f"adm:edit:promo_clear:{pid}")

    kb.button(text="🏷 SKU (артикул)", callback_data=f"adm:edit:sku:{pid}")
    kb.button(text="🏁 Штрихкод", callback_data=f"adm:edit:barcode:{pid}")

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


# =========================================================
# PANEL (ONE MESSAGE)
# =========================================================

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
    kb.button(text="➕ Додати категорію", callback_data="adm:panel:add_cat")
    kb.button(text="➕ Додати підкатегорію", callback_data="adm:panel:add_sub")
    kb.button(text="➕ Додати товар", callback_data="adm:panel:add_product")
    kb.button(text="⬅️ Назад", callback_data="adm:panel:back")
    kb.adjust(1)
    return kb.as_markup()


def panel_orders_kb() -> types.InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="📋 Нові (оплачені)", callback_data="adm:panel:orders_paid")
    kb.button(text="📦 Усі замовлення", callback_data="adm:panel:orders_all")
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


# =========================================================
# COMMON ENTRY / CANCEL
# =========================================================

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
    await cb.message.answer(
        "🔧 Панель (Адмін/Персонал)",
        reply_markup=panel_main_kb(cb.from_user.id)
    )
    await cb.answer()

# =========================================================


@router.callback_query(F.data.startswith("adm:plist_sub:sub_i:"))
async def plist_sub(cb: types.CallbackQuery):
    d = await load_data()
    if not is_staff(d, cb.from_user.id):
        return await cb.answer("Немає доступу", show_alert=True)

    # adm:plist_sub:sub_i:<cat_i>:<sub_i|n>
    parts = cb.data.split(":")
    cat_i = int(parts[-2])
    sub_token = parts[-1]

    cat = await _cat_by_index(cat_i)
    sub = await _sub_by_index(cat_i, sub_token)
    if not cat or sub is None:
        return await cb.answer("Не знайдено", show_alert=True)

    # беремо pid'и з categories (це головне джерело правди)
    pids = _pids_in_sub(d, cat, sub)
    if not pids:
        await cb.message.answer("Товарів тут ще немає.")
        return await cb.answer()

    # показуємо знайдені товари
    for pid in pids:
        p = find_product(d, int(pid))
        if not p:
            continue
        _ensure_product_schema(p)
        await cb.message.answer(
            product_card(p),
            parse_mode="HTML",
            reply_markup=await product_actions_kb(int(p.get("id", 0) or 0))
        )

    await cb.answer()
# =========================

import re
from typing import Optional

from orders_timeline import (
    order_set_status,
    order_set_ttn,
    render_timeline_text,
)

# =========================================================
# ROLES / PERMISSIONS (вихід на майбутнє)
# data["roles"] = {"123": "manager"|"packer"|"admin"}
# якщо ролі нема — вважаємо "manager"
# =========================================================

ROLE_ADMIN = "admin"
ROLE_MANAGER = "manager"
ROLE_PACKER = "packer"


def _role_of(d: dict, uid: int) -> str:
    if is_admin(uid):
        return ROLE_ADMIN
    roles = d.get("roles", {}) or {}
    r = (roles.get(str(uid)) or "").strip().lower()
    return r or ROLE_MANAGER


def can_manage_orders(d: dict, uid: int) -> bool:
    return _role_of(d, uid) in (ROLE_ADMIN, ROLE_MANAGER, ROLE_PACKER)


def can_edit_catalog(d: dict, uid: int) -> bool:
    return _role_of(d, uid) in (ROLE_ADMIN, ROLE_MANAGER)


def can_manage_staff(d: dict, uid: int) -> bool:
    return _role_of(d, uid) == ROLE_ADMIN


def can_set_ttn(d: dict, uid: int) -> bool:
    # ТТН ставить менеджер/адмін
    return _role_of(d, uid) in (ROLE_ADMIN, ROLE_MANAGER)


def can_mark_packing(d: dict, uid: int) -> bool:
    # комплектація/пакування
    return _role_of(d, uid) in (ROLE_ADMIN, ROLE_MANAGER, ROLE_PACKER)


def can_mark_logistics(d: dict, uid: int) -> bool:
    # відправка/отримано/повернення/закриття
    return _role_of(d, uid) in (ROLE_ADMIN, ROLE_MANAGER)


# =========================================================
# STATUS NOTES
# ---------------------------------------------------------
# paid/prepay -> in_work -> packed -> shipped(+ТТН) -> arrived -> received
# not_picked -> returned
# done — закрито
#
# ВАЖЛИВО: "picked/зібрано" — це СКЛАД, а не клієнт.
# Ми його НЕ використовуємо як "отримано".
# =========================================================

def _ttn_norm(s: str) -> str:
    s = (s or "").strip()
    if s == "-":
        return ""
    # прибираємо пробіли
    return re.sub(r"\s+", "", s)


def order_actions_kb(
    oid: int,
    status: str,
    *,
    d: Optional[dict] = None,
    uid: Optional[int] = None,
) -> types.InlineKeyboardMarkup:
    """
    Якщо передати d та uid — кнопки будуть залежати від ролей.
    Якщо не передати — всі кнопки як "без обмежень".
    """
    kb = InlineKeyboardBuilder()
    st = (status or "").strip().lower()

    allow_any = (d is None or uid is None)

    def _allow(fn):
        return True if allow_any else fn(d, uid)

    # 1) В роботу
    if st in ("paid", "prepay") and _allow(can_manage_orders):
        kb.button(text="🟡 В роботу", callback_data=f"adm:order:in_work:{oid}")

    # 2) Запаковано (склад/пакувальник)
    if st in ("paid", "prepay", "in_work", "packed") and _allow(can_mark_packing):
        kb.button(text="📦 Запаковано", callback_data=f"adm:order:packed:{oid}")

    # 3) Відправлено (+ввід ТТН)
    if st in ("paid", "prepay", "in_work", "packed", "shipped") and _allow(can_mark_logistics):
        kb.button(text="🚚 Відправлено + ТТН", callback_data=f"adm:order:shipped:{oid}")

    # 4) Після відправки
    if st in ("shipped", "arrived") and _allow(can_mark_logistics):
        kb.button(text="📍 Прибуло у відділення", callback_data=f"adm:order:arrived:{oid}")
        kb.button(text="✅ Отримано (клієнт)", callback_data=f"adm:order:received:{oid}")
        kb.button(text="❌ Не забрав", callback_data=f"adm:order:not_picked:{oid}")

    # 5) Повернення
    if st in ("shipped", "arrived", "not_picked") and _allow(can_mark_logistics):
        kb.button(text="🔁 Повернуто", callback_data=f"adm:order:returned:{oid}")

    # 6) Закрити (done)
    if st in ("paid", "prepay", "in_work", "packed", "shipped", "arrived", "received", "not_picked", "returned") and _allow(can_mark_logistics):
        kb.button(text="✅ Закрити (done)", callback_data=f"adm:order:done:{oid}")

    # 7) Службові
    kb.button(text="📜 Хронологія", callback_data=f"adm:order:timeline:{oid}")
    kb.button(text="👤 Історія покупця", callback_data=f"adm:order:history:{oid}")

    if _allow(can_set_ttn):
        kb.button(text="🧾 Встановити ТТН", callback_data=f"adm:order:set_ttn:{oid}")

    kb.adjust(1)
    return kb.as_markup()


def _find_order(d: dict, oid: int) -> dict | None:
    for o in (d.get("orders", []) or []):
        try:
            if int(o.get("id", -1)) == int(oid):
                return o
        except Exception:
            continue
    return None


# =========================================================
# PANEL: ORDERS / SEARCH / ADD MANAGER
# (замінимо "⏳ заглушки" з Part 1)
# =========================================================

@router.callback_query(F.data.startswith("adm:panel:"))
async def panel_nav(cb: types.CallbackQuery, state: FSMContext):
    d = await load_data()
    if not is_staff(d, cb.from_user.id):
        return await cb.answer("Немає доступу", show_alert=True)

    await state.clear()
    action = cb.data.split(":")[2]

    if action in ("back", "main"):
        await cb.message.answer("🔧 Панель (Адмін/Персонал)", reply_markup=panel_main_kb(cb.from_user.id))
        return await cb.answer()

    if action == "catalog":
        await cb.message.answer("🧩 Каталог:", reply_markup=panel_catalog_kb())
        return await cb.answer()

    if action == "orders":
        await cb.message.answer("📑 Замовлення:", reply_markup=panel_orders_kb())
        return await cb.answer()

    if action == "settings":
        await cb.message.answer("⚙️ Налаштування:", reply_markup=panel_settings_kb(cb.from_user.id))
        return await cb.answer()

    # actions -> FSM
    if action == "add_cat":
        await state.set_state(AdminFSM.add_cat)
        await cb.message.answer("Введіть назву категорії:")
        return await cb.answer()

    if action == "add_sub":
        await state.set_state(AdminFSM.add_sub_cat)
        await cb.message.answer("Оберіть категорію:", reply_markup=await cats_inline("sub_add"))
        return await cb.answer()

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

    # -------- ORDERS LISTS --------

    if action == "orders_paid":
        if not can_manage_orders(d, cb.from_user.id):
            return await cb.answer("⛔️ Недостатньо прав", show_alert=True)

        paid = [o for o in (d.get("orders", []) or []) if (o.get("status") or "").strip().lower() in ("paid", "prepay")]
        if not paid:
            await cb.message.answer("Немає нових оплачених/передплачених замовлень.")
            return await cb.answer()

        for o in paid:
            products = _order_products(d, o)
            await cb.message.answer(
                order_premium_text(d, o, products),
                parse_mode="HTML",
                reply_markup=order_actions_kb(int(o["id"]), str(o.get("status", "")), d=d, uid=cb.from_user.id)
            )
        return await cb.answer()

    if action == "orders_all":
        if not can_manage_orders(d, cb.from_user.id):
            return await cb.answer("⛔️ Недостатньо прав", show_alert=True)

        orders = d.get("orders", []) or []
        if not orders:
            await cb.message.answer("Замовлень ще немає.")
            return await cb.answer()

        for o in reversed(orders):
            products = _order_products(d, o)
            await cb.message.answer(
                order_premium_text(d, o, products),
                parse_mode="HTML",
                reply_markup=order_actions_kb(int(o["id"]), str(o.get("status", "")), d=d, uid=cb.from_user.id)
            )
        return await cb.answer()

    if action == "buyer_search":
        if not can_manage_orders(d, cb.from_user.id):
            return await cb.answer("⛔️ Недостатньо прав", show_alert=True)

        await state.set_state(AdminFSM.search_buyer)
        await cb.message.answer(
            "🔎 <b>Пошук покупця</b>\n\n"
            "Введіть одне з:\n"
            "• ID (число)\n"
            "• @username\n"
            "• частину імені\n\n"
            "Приклад: <code>123456789</code> або <code>@katas</code або <code>Віктор</code>",
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


# =========================================================
# ORDERS: CHANGE STATUS + TTN + TIMELINE + HISTORY
# =========================================================

@router.callback_query(F.data.startswith("adm:order:"))
async def order_change_status(cb: types.CallbackQuery, bot: Bot, state: FSMContext):
    d = await load_data()
    if not is_staff(d, cb.from_user.id):
        return await cb.answer("Немає доступу", show_alert=True)

    # adm:order:<action>:<oid>
    _, _, action, oid_str = cb.data.split(":")
    oid = int(oid_str)

    order = _find_order(d, oid)
    if not order:
        await cb.message.answer("❌ Замовлення не знайдено.")
        return await cb.answer()

    # -------- PERMISSIONS BY ACTION --------
    if action in ("packed",) and not can_mark_packing(d, cb.from_user.id):
        return await cb.answer("⛔️ Недостатньо прав", show_alert=True)

    if action in ("in_work", "shipped", "arrived", "received", "not_picked", "returned", "done", "set_ttn") and not can_set_ttn(d, cb.from_user.id):
        return await cb.answer("⛔️ Недостатньо прав", show_alert=True)

    async def _reply_updated(prefix_text: str):
        products = _order_products(d, order)
        kb = order_actions_kb(oid, str(order.get("status", "")), d=d, uid=cb.from_user.id)
        await cb.message.answer(
            prefix_text + "\n\n" + order_premium_text(d, order, products),
            parse_mode="HTML",
            reply_markup=kb
        )

    st = (order.get("status") or "").strip().lower()

    # ---- IN WORK ----
    if action == "in_work":
        if st not in ("paid", "prepay"):
            return await cb.answer("Тільки paid/prepay можна взяти в роботу", show_alert=True)

        order_set_status(order, "in_work", who=str(cb.from_user.id), details="Взято в роботу")
        await save_data(d)

        await _reply_updated(f"🟡 Замовлення #{oid} взято в роботу.")
        await _notify_buyer(bot, d, order, f"🟡 Ваше замовлення #{oid} взято в роботу ✅")
        return await cb.answer()

    # ---- PACKED ----
    if action == "packed":
        if st not in ("paid", "prepay", "in_work", "packed"):
            return await cb.answer("Запакувати можна після paid/prepay/in_work", show_alert=True)

        order_set_status(order, "packed", who=str(cb.from_user.id), details="Запаковано")
        await save_data(d)

        await _reply_updated(f"📦 Замовлення #{oid} запаковано.")
        await _notify_buyer(bot, d, order, f"📦 Ваше замовлення #{oid} запаковано ✅")
        return await cb.answer()

    # ---- SHIPPED + ASK TTN ----
    if action == "shipped":
        if st not in ("paid", "prepay", "in_work", "packed", "shipped"):
            return await cb.answer("Неможливо позначити як відправлено", show_alert=True)

        order_set_status(order, "shipped", who=str(cb.from_user.id), details="Позначено як відправлено (очікуємо ТТН)")
        await save_data(d)

        await _reply_updated(f"🚚 Замовлення #{oid} позначено як ВІДПРАВЛЕНО.")
        await state.clear()
        await state.set_state(AdminFSM.order_ttn)
        await state.update_data(oid=oid)

        await cb.message.answer("📮 Введіть ТТН для цього замовлення (або '-' щоб без ТТН):")
        return await cb.answer()

    # ---- ARRIVED ----
    if action == "arrived":
        if st not in ("shipped", "arrived"):
            return await cb.answer("Прибуло доречно тільки після 'Відправлено'", show_alert=True)

        order_set_status(order, "arrived", who=str(cb.from_user.id), details="Прибуло у відділення")
        await save_data(d)

        await _reply_updated(f"📍 Замовлення #{oid}: прибуло у відділення.")
        await _notify_buyer(bot, d, order, f"📍 Замовлення #{oid}: прибуло у відділення ✅")
        return await cb.answer()

    # ---- RECEIVED ----
    if action == "received":
        if st not in ("shipped", "arrived", "received"):
            return await cb.answer("Отримано доречно після shipped/arrived", show_alert=True)

        order_set_status(order, "received", who=str(cb.from_user.id), details="Клієнт отримав/забрав")
        await save_data(d)

        await _reply_updated(f"✅ Замовлення #{oid}: клієнт ОТРИМАВ.")
        await _notify_buyer(bot, d, order, f"✅ Замовлення #{oid}: отримано. Дякуємо! 🙌")
        return await cb.answer()

    # ---- NOT PICKED ----
    if action == "not_picked":
        if st not in ("shipped", "arrived", "not_picked"):
            return await cb.answer("Не забрав доречно після shipped/arrived", show_alert=True)

        order_set_status(order, "not_picked", who=str(cb.from_user.id), details="Клієнт не забрав")
        await save_data(d)

        await _reply_updated(f"❌ Замовлення #{oid}: НЕ ЗАБРАВ.")
        await _notify_buyer(bot, d, order, f"❌ Замовлення #{oid}: не забрано. Напишіть нам — допоможемо 🤝")
        return await cb.answer()

    # ---- RETURNED ----
    if action == "returned":
        if st not in ("shipped", "arrived", "not_picked", "returned", "received"):
            return await cb.answer("Повернення ставимо після логістики", show_alert=True)

        order_set_status(order, "returned", who=str(cb.from_user.id), details="Повернено")
        await save_data(d)

        await _reply_updated(f"🔁 Замовлення #{oid}: ПОВЕРНУТО.")
        await _notify_buyer(bot, d, order, f"🔁 Замовлення #{oid}: повернено. Якщо є питання — пишіть 🙏")
        return await cb.answer()

    # ---- DONE ----
    if action == "done":
        if st in ("done", "canceled"):
            return await cb.answer("Вже закрито", show_alert=True)

        order_set_status(order, "done", who=str(cb.from_user.id), details="Закрито (done)")
        await save_data(d)

        await _reply_updated(f"✅ Замовлення #{oid} закрито.")
        await _notify_buyer(bot, d, order, f"✅ Замовлення #{oid} завершено 🎉")
        return await cb.answer()

    # ---- SET TTN (manual) ----
    if action == "set_ttn":
        if not can_set_ttn(d, cb.from_user.id):
            return await cb.answer("⛔️ Недостатньо прав", show_alert=True)

        await state.clear()
        await state.set_state(AdminFSM.order_ttn)
        await state.update_data(oid=oid)

        cur = (order.get("np_ttn") or order.get("ttn") or "").strip() or "—"
        await cb.message.answer(
            f"📮 Поточний ТТН: <code>{cur}</code>\n\n"
            "Введіть новий ТТН або <code>-</code> щоб очистити:",
            parse_mode="HTML"
        )
        return await cb.answer()

    # ---- TIMELINE ----
    if action == "timeline":
        txt = render_timeline_text(order)
        kb = InlineKeyboardBuilder()
        kb.button(text="⬅️ Назад", callback_data="adm:cancel")
        kb.adjust(1)
        await cb.message.answer(txt, parse_mode="HTML", reply_markup=kb.as_markup())
        return await cb.answer()

    # ---- HISTORY OF BUYER ----
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
                reply_markup=order_actions_kb(int(o["id"]), str(o.get("status", "")), d=d, uid=cb.from_user.id)
            )
        return await cb.answer()

    return await cb.answer("Невідома дія", show_alert=True)


# =========================================================
# TTN INPUT HANDLER (FSM)
# =========================================================

@router.message(AdminFSM.order_ttn)
async def admin_set_ttn_msg(m: types.Message, state: FSMContext, bot: Bot):
    st_data = await state.get_data()
    oid = int(st_data.get("oid", 0) or 0)

    raw = (m.text or "").strip()
    ttn = _ttn_norm(raw)

    d = await load_data()
    order = _find_order(d, oid)
    if not order:
        await state.clear()
        return await m.answer("❌ Замовлення не знайдено.")

    # ставимо ТТН в обидва поля (np_ttn + ttn) і пишемо подію
    # (orders_timeline.order_set_ttn це вже робить)
    order_set_ttn(order, ttn, who=str(m.from_user.id), details="TTN set from admin panel")
    await save_data(d)
    await state.clear()

    if not ttn:
        await m.answer("✅ ТТН очищено.")
        return

    await m.answer("✅ ТТН збережено.")

    # якщо замовлення вже shipped — покупцю піде нормальний текст (а в історії "Відправлено" буде тільки якщо є ТТН)
    if (order.get("status") or "").strip().lower() in ("shipped", "sent"):
        await _notify_buyer(bot, d, order, f"🚚 Ваше замовлення #{oid} відправлено ✅")
# =========================
# PART 3A/3 — CATALOG CORE
# =========================
@router.callback_query(F.data.startswith("adm:catmgmt:cat_i:"))
async def cat_mgmt_choose(cb: types.CallbackQuery):
    d = await load_data()
    if not is_staff(d, cb.from_user.id) or not can_edit_catalog(d, cb.from_user.id):
        return await cb.answer("⛔️ Немає доступу", show_alert=True)

    cat_i = int(cb.data.split(":")[3])
    cat = await _cat_by_index(cat_i)
    if not cat:
        return await cb.answer("Категорію не знайдено", show_alert=True)

    subs = (d.get("categories", {}) or {}).get(cat, {}) or {}
    subs_list = [s for s in subs.keys() if s != NO_SUB]

    text_lines = [
        f"🗂 <b>{cat}</b>",
        "",
        "Оберіть підкатегорію для керування:",
    ]

    kb = InlineKeyboardBuilder()

    # Утлет (NO_SUB)
    kb.button(text="🧷 Утлет", callback_data=f"adm:catmgmt:sub_i:{cat_i}:n")

    # Звичайні підкатегорії
    for j, s in enumerate(subs_list):
        kb.button(text=str(s), callback_data=f"adm:catmgmt:sub_i:{cat_i}:{j}")

    kb.adjust(1)

    # Службові кнопки
    kb.button(text="➕ Додати підкатегорію", callback_data=f"adm:sub_add:cat_i:{cat_i}")
    kb.button(text="📦 Товари в категорії", callback_data=f"adm:plist_cat:cat_i:{cat_i}")
    kb.button(text="⬅️ Назад", callback_data="adm:panel:cats")
    kb.adjust(1)

    await cb.message.answer("\n".join(text_lines), parse_mode="HTML", reply_markup=kb.as_markup())
    await cb.answer()
# =========================================================
# ADD CATEGORY (FSM AdminFSM.add_cat)
# =========================================================

@router.message(AdminFSM.add_cat)
async def add_cat_name(m: types.Message, state: FSMContext):
    d = await load_data()
    if not is_staff(d, m.from_user.id) or not can_edit_catalog(d, m.from_user.id):
        return await m.answer("⛔️ Немає доступу")

    name = (m.text or "").strip()
    if not name:
        return await m.answer("Введіть назву категорії текстом.")

    d.setdefault("categories", {})
    if name in d["categories"]:
        return await m.answer("Така категорія вже існує.")

    d["categories"][name] = {NO_SUB: []}  # утлет-підкатегорія існує завжди
    await save_data(d)
    await state.clear()

    await m.answer(f"✅ Категорію <b>{name}</b> додано.", parse_mode="HTML", reply_markup=staff_menu(m.from_user.id))


# =========================================================
# ADD SUBCATEGORY (FSM AdminFSM.add_sub_cat -> add_sub_name)
# =========================================================

@router.callback_query(F.data.startswith("adm:sub_add:cat_i:"))
async def add_sub_choose_cat(cb: types.CallbackQuery, state: FSMContext):
    d = await load_data()
    if not is_staff(d, cb.from_user.id) or not can_edit_catalog(d, cb.from_user.id):
        return await cb.answer("⛔️ Немає доступу", show_alert=True)

    cat_i = int(cb.data.split(":")[3])
    cat = await _cat_by_index(cat_i)
    if not cat:
        return await cb.answer("Категорію не знайдено", show_alert=True)

    await state.set_state(AdminFSM.add_sub_name)
    await state.update_data(cat_i=cat_i)
    await cb.message.answer(f"Введіть назву підкатегорії для <b>{cat}</b>:", parse_mode="HTML")
    await cb.answer()


@router.message(AdminFSM.add_sub_name)
async def add_sub_name(m: types.Message, state: FSMContext):
    d = await load_data()
    if not is_staff(d, m.from_user.id) or not can_edit_catalog(d, m.from_user.id):
        return await m.answer("⛔️ Немає доступу")

    st = await state.get_data()
    cat_i = int(st.get("cat_i", -1))
    cat = await _cat_by_index(cat_i)
    if not cat:
        await state.clear()
        return await m.answer("Категорію не знайдено.")

    name = (m.text or "").strip()
    if not name:
        return await m.answer("Введіть назву підкатегорії текстом.")

    d.setdefault("categories", {})
    d["categories"].setdefault(cat, {NO_SUB: []})
    if name in d["categories"][cat]:
        return await m.answer("Така підкатегорія вже існує.")

    d["categories"][cat][name] = []
    await save_data(d)
    await state.clear()
    await m.answer(f"✅ Підкатегорію <b>{name}</b> додано в <b>{cat}</b>.", parse_mode="HTML", reply_markup=staff_menu(m.from_user.id))


# PRODUCT ACTIONS: HIT ON/OFF, DELETE ASK/DELETE, EDIT MENU
# =========================================================

@router.callback_query(F.data.startswith("adm:hit:"))
async def hit_toggle(cb: types.CallbackQuery):
    d = await load_data()
    if not is_staff(d, cb.from_user.id) or not can_edit_catalog(d, cb.from_user.id):
        return await cb.answer("⛔️ Немає доступу", show_alert=True)

    # adm:hit:on|off:<pid>
    _, _, mode, pid_str = cb.data.split(":")
    pid = int(pid_str)

    d.setdefault("hits", [])
    hits = _hits_set(d)

    if mode == "on":
        hits.add(pid)
        await cb.answer("🔥 Додано в Хіти")
    else:
        hits.discard(pid)
        await cb.answer("❌ Прибрано з Хітів")

    d["hits"] = list(sorted(hits))
    await save_data(d)


@router.callback_query(F.data.startswith("adm:delask:"))
async def product_delete_ask(cb: types.CallbackQuery):
    d = await load_data()
    if not is_staff(d, cb.from_user.id) or not can_edit_catalog(d, cb.from_user.id):
        return await cb.answer("⛔️ Немає доступу", show_alert=True)

    pid = int(cb.data.split(":")[2])
    p = find_product(d, pid)
    if not p:
        return await cb.answer("Товар не знайдено", show_alert=True)

    await cb.message.answer(
        f"⚠️ Видалити товар <b>{p.get('name','')}</b> (ID {pid})?",
        parse_mode="HTML",
        reply_markup=confirm_product_delete_kb(pid)
    )
    await cb.answer()


@router.callback_query(F.data.startswith("adm:del:"))
async def product_delete_do(cb: types.CallbackQuery):
    d = await load_data()
    if not is_staff(d, cb.from_user.id) or not can_edit_catalog(d, cb.from_user.id):
        return await cb.answer("⛔️ Немає доступу", show_alert=True)

    pid = int(cb.data.split(":")[2])

    # видаляємо з products
    prods = d.get("products", []) or []
    d["products"] = [p for p in prods if int(p.get("id", -1)) != pid]

    # прибираємо з categories списків
    cats = d.get("categories", {}) or {}
    for cat, subs in cats.items():
        for sub, arr in (subs or {}).items():
            if isinstance(arr, list):
                subs[sub] = [x for x in arr if str(x) != str(pid)]

    # прибираємо з hits
    hits = _hits_set(d)
    hits.discard(pid)
    d["hits"] = list(sorted(hits))

    await save_data(d)
    await cb.message.answer(f"✅ Товар {pid} видалено.")
    await cb.answer()


@router.callback_query(F.data.startswith("adm:editmenu:"))
async def product_editmenu(cb: types.CallbackQuery):
    d = await load_data()
    if not is_staff(d, cb.from_user.id) or not can_edit_catalog(d, cb.from_user.id):
        return await cb.answer("⛔️ Немає доступу", show_alert=True)

    pid = int(cb.data.split(":")[2])
    p = find_product(d, pid)
    if not p:
        return await cb.answer("Товар не знайдено", show_alert=True)

    _ensure_product_schema(p)
    await cb.message.answer(
        product_card(p),
        parse_mode="HTML",
        reply_markup=edit_menu_kb(pid)
    )
    await cb.answer()
# =========================
# PART 3B/3 — PRODUCT CREATE/EDIT + STAFF/ROLES + BUYER SEARCH
# =========================

import random
import string

# =========================================================
# BARCODE / SKU HELPERS
# =========================================================

def _gen_barcode_ean13_like() -> str:
    """
    Простий генератор 13-значного "EAN-стайл" коду.
    Це НЕ офіційний EAN з перевіркою — але достатньо як внутрішній штрихкод.
    """
    return "".join(random.choice(string.digits) for _ in range(13))


def _ensure_unique_barcode(d: dict, candidate: str) -> str:
    cand = (candidate or "").strip()
    if not cand:
        cand = _gen_barcode_ean13_like()

    used = set()
    for p in (d.get("products", []) or []):
        bc = (p.get("barcode") or "").strip()
        if bc:
            used.add(bc)

    # якщо зайнято — перегенеруємо
    while cand in used:
        cand = _gen_barcode_ean13_like()
    return cand


def _normalize_sku(s: str) -> str:
    return (s or "").strip()


# =========================================================
# ADD PRODUCT (FSM AdminFSM.prod_cat -> prod_sub -> prod_name -> prod_sku -> prod_price -> prod_desc -> prod_photos)
# =========================================================

@router.callback_query(F.data.startswith("adm:prod_cat:cat_i:"))
async def prod_choose_cat(cb: types.CallbackQuery, state: FSMContext):
    d = await load_data()
    if not is_staff(d, cb.from_user.id) or not can_edit_catalog(d, cb.from_user.id):
        return await cb.answer("⛔️ Немає доступу", show_alert=True)

    cat_i = int(cb.data.split(":")[3])
    cat = await _cat_by_index(cat_i)
    if not cat:
        return await cb.answer("Категорію не знайдено", show_alert=True)

    await state.set_state(AdminFSM.prod_sub)
    await state.update_data(cat_i=cat_i)

    await cb.message.answer(
        f"Оберіть підкатегорію для <b>{cat}</b>:",
        parse_mode="HTML",
        reply_markup=await subs_inline(cat_i, "prod_sub", include_no_sub=True)
    )
    await cb.answer()


@router.callback_query(F.data.startswith("adm:prod_sub:sub_i:"))
async def prod_choose_sub(cb: types.CallbackQuery, state: FSMContext):
    d = await load_data()
    if not is_staff(d, cb.from_user.id) or not can_edit_catalog(d, cb.from_user.id):
        return await cb.answer("⛔️ Немає доступу", show_alert=True)

    parts = cb.data.split(":")
    cat_i = int(parts[3])
    sub_i = parts[4]

    cat = await _cat_by_index(cat_i)
    sub = await _sub_by_index(cat_i, sub_i)
    if not cat or sub is None:
        return await cb.answer("Не знайдено", show_alert=True)

    await state.set_state(AdminFSM.prod_name)
    await state.update_data(cat=cat, sub=sub)

    sub_name = "🧷 Утлет" if sub == NO_SUB else sub
    await cb.message.answer(f"Введіть <b>назву</b> товару (категорія: <b>{cat}</b> / <b>{sub_name}</b>):", parse_mode="HTML")
    await cb.answer()


@router.message(AdminFSM.prod_name)
async def prod_set_name(m: types.Message, state: FSMContext):
    d = await load_data()
    if not is_staff(d, m.from_user.id) or not can_edit_catalog(d, m.from_user.id):
        return await m.answer("⛔️ Немає доступу")

    name = (m.text or "").strip()
    if not name:
        return await m.answer("Введіть назву товару текстом.")

    await state.update_data(name=name)
    await state.set_state(AdminFSM.prod_sku)
    await m.answer("Введіть <b>SKU / артикул</b> (або <code>-</code> щоб пропустити):", parse_mode="HTML")


@router.message(AdminFSM.prod_sku)
async def prod_set_sku(m: types.Message, state: FSMContext):
    d = await load_data()
    if not is_staff(d, m.from_user.id) or not can_edit_catalog(d, m.from_user.id):
        return await m.answer("⛔️ Немає доступу")

    sku_raw = (m.text or "").strip()
    sku = "" if sku_raw == "-" else _normalize_sku(sku_raw)

    await state.update_data(sku=sku)
    await state.set_state(AdminFSM.prod_price)
    await m.answer("Введіть <b>ціну</b> (число):", parse_mode="HTML")


@router.message(AdminFSM.prod_price)
async def prod_set_price(m: types.Message, state: FSMContext):
    d = await load_data()
    if not is_staff(d, m.from_user.id) or not can_edit_catalog(d, m.from_user.id):
        return await m.answer("⛔️ Немає доступу")

    txt = (m.text or "").strip().replace(" ", "")
    try:
        price = int(float(txt))
    except Exception:
        return await m.answer("Ціна має бути числом. Приклад: 199")

    if price < 0:
        price = 0

    await state.update_data(price=price)
    await state.set_state(AdminFSM.prod_desc)
    await m.answer("Введіть <b>опис</b> товару (або <code>-</code> якщо без опису):", parse_mode="HTML")


@router.message(AdminFSM.prod_desc)
async def prod_set_desc(m: types.Message, state: FSMContext):
    d = await load_data()
    if not is_staff(d, m.from_user.id) or not can_edit_catalog(d, m.from_user.id):
        return await m.answer("⛔️ Немає доступу")

    desc_raw = (m.text or "").strip()
    desc = "" if desc_raw == "-" else desc_raw

    await state.update_data(desc=desc)
    await state.set_state(AdminFSM.prod_photos)
    await m.answer("Надішліть <b>фото</b> товару (1+). Коли готово — напишіть <code>готово</code>.", parse_mode="HTML")


@router.message(AdminFSM.prod_photos)
async def prod_photos_collect(m: types.Message, state: FSMContext):
    d = await load_data()
    if not is_staff(d, m.from_user.id) or not can_edit_catalog(d, m.from_user.id):
        return await m.answer("⛔️ Немає доступу")

    st = await state.get_data()
    photos = list(st.get("photos", []) or [])

    # завершення
    if (m.text or "").strip().lower() in ("готово", "done", "ok"):
        if not photos:
            return await m.answer("Додайте хоча б 1 фото або напишіть '-' щоб створити без фото.")

        # збираємо дані
        cat = st.get("cat")
        sub = st.get("sub", NO_SUB)
        name = st.get("name", "")
        sku = st.get("sku", "")
        price = int(st.get("price", 0) or 0)
        desc = st.get("desc", "")

        # створюємо продукт
        pid = next_product_id(d)
        barcode = _ensure_unique_barcode(d, "")

        p = {
            "id": pid,
            "name": name,
            "price": price,
            "base_price": price,
            "promo_price": 0,
            "promo_until_ts": None,
            "desc": desc,
            "photos": photos,
            "sku": sku,
            "barcode": barcode,
            "category": cat,
            "sub_category": sub,
        }

        d.setdefault("products", [])
        d["products"].append(p)

        # додаємо pid у категорію/підкатегорію
        d.setdefault("categories", {})
        d["categories"].setdefault(cat, {NO_SUB: []})
        d["categories"][cat].setdefault(sub, [])
        d["categories"][cat][sub].append(pid)

        await save_data(d)
        await state.clear()

        sub_name = "🧷 Утлет" if sub == NO_SUB else sub
        await m.answer(
            "✅ Товар створено!\n\n"
            f"<b>{name}</b>\n"
            f"ID: <code>{pid}</code>\n"
            f"SKU: <code>{sku or '—'}</code>\n"
            f"BARCODE: <code>{barcode}</code>\n"
            f"Категорія: <b>{cat}</b> / <b>{sub_name}</b>\n",
            parse_mode="HTML",
            reply_markup=staff_menu(m.from_user.id)
        )
        # покажемо картку
        await m.answer(product_card(p), parse_mode="HTML", reply_markup=await product_actions_kb(pid))
        return

    # дозволимо створити без фото
    if (m.text or "").strip() == "-":
        # створюємо без фото
        cat = st.get("cat")
        sub = st.get("sub", NO_SUB)
        name = st.get("name", "")
        sku = st.get("sku", "")
        price = int(st.get("price", 0) or 0)
        desc = st.get("desc", "")

        pid = next_product_id(d)
        barcode = _ensure_unique_barcode(d, "")

        p = {
            "id": pid,
            "name": name,
            "price": price,
            "base_price": price,
            "promo_price": 0,
            "promo_until_ts": None,
            "desc": desc,
            "photos": [],
            "sku": sku,
            "barcode": barcode,
            "category": cat,
            "sub_category": sub,
        }

        d.setdefault("products", [])
        d["products"].append(p)

        d.setdefault("categories", {})
        d["categories"].setdefault(cat, {NO_SUB: []})
        d["categories"][cat].setdefault(sub, [])
        d["categories"][cat][sub].append(pid)

        await save_data(d)
        await state.clear()

        await m.answer("✅ Товар створено (без фото).", reply_markup=staff_menu(m.from_user.id))
        await m.answer(product_card(p), parse_mode="HTML", reply_markup=await product_actions_kb(pid))
        return

    # приймаємо фото
    if m.photo:
        file_id = m.photo[-1].file_id
        photos.append(file_id)
        await state.update_data(photos=photos)
        return await m.answer(f"📷 Додано фото ({len(photos)}). Напишіть <code>готово</code>, коли достатньо.", parse_mode="HTML")

    return await m.answer("Надішліть фото або напишіть <code>готово</code>.", parse_mode="HTML")


# =========================================================
# EDIT PRODUCT (FSM EditProductFSM.*)
# =========================================================

def _find_product_by_id(d: dict, pid: int) -> dict | None:
    for p in (d.get("products", []) or []):
        try:
            if int(p.get("id", -1)) == int(pid):
                return p
        except Exception:
            continue
    return None


@router.callback_query(F.data.startswith("adm:edit:"))
async def edit_product_router(cb: types.CallbackQuery, state: FSMContext):
    d = await load_data()
    if not is_staff(d, cb.from_user.id) or not can_edit_catalog(d, cb.from_user.id):
        return await cb.answer("⛔️ Немає доступу", show_alert=True)

    # adm:edit:<field>:<pid>
    _, _, field, pid_str = cb.data.split(":")
    pid = int(pid_str)

    p = _find_product_by_id(d, pid)
    if not p:
        return await cb.answer("Товар не знайдено", show_alert=True)

    _ensure_product_schema(p)

    if field == "name":
        await state.set_state(EditProductFSM.name)
        await state.update_data(pid=pid)
        await cb.message.answer("Введіть нову <b>назву</b>:", parse_mode="HTML")
        return await cb.answer()

    if field == "price":
        await state.set_state(EditProductFSM.price)
        await state.update_data(pid=pid)
        await cb.message.answer("Введіть нову <b>ціну</b> (число):", parse_mode="HTML")
        return await cb.answer()

    if field == "desc":
        await state.set_state(EditProductFSM.desc)
        await state.update_data(pid=pid)
        await cb.message.answer("Введіть новий <b>опис</b> (або <code>-</code> щоб очистити):", parse_mode="HTML")
        return await cb.answer()

    if field == "promo":
        await state.set_state(EditProductFSM.promo_price)
        await state.update_data(pid=pid)
        await cb.message.answer("Введіть <b>акційну ціну</b> (0 щоб прибрати):", parse_mode="HTML")
        return await cb.answer()

    if field == "promo_clear":
        p["promo_price"] = 0
        p["promo_until_ts"] = None
        # повертаємо базову
        p["price"] = int(p.get("base_price", 0) or 0)
        await save_data(d)
        await cb.message.answer("✅ Акцію прибрано.")
        await cb.message.answer(product_card(p), parse_mode="HTML", reply_markup=edit_menu_kb(pid))
        return await cb.answer()

    if field == "sku":
        await state.set_state(EditProductFSM.name)  # використаємо тимчасово name як input
        await state.update_data(pid=pid, _edit_field="sku")
        await cb.message.answer("Введіть <b>SKU</b> (або <code>-</code> щоб очистити):", parse_mode="HTML")
        return await cb.answer()

    if field == "barcode":
        await state.set_state(EditProductFSM.name)  # використаємо тимчасово name як input
        await state.update_data(pid=pid, _edit_field="barcode")
        await cb.message.answer(
            "Введіть <b>BARCODE</b> (13 цифр) або <code>-</code> щоб згенерувати автоматично:",
            parse_mode="HTML"
        )
        return await cb.answer()

    return await cb.answer("Невідоме поле", show_alert=True)


@router.message(EditProductFSM.name)
async def edit_name_or_meta(m: types.Message, state: FSMContext):
    d = await load_data()
    st = await state.get_data()
    pid = int(st.get("pid", 0) or 0)

    if not is_staff(d, m.from_user.id) or not can_edit_catalog(d, m.from_user.id):
        await state.clear()
        return await m.answer("⛔️ Немає доступу")

    p = _find_product_by_id(d, pid)
    if not p:
        await state.clear()
        return await m.answer("Товар не знайдено")

    _ensure_product_schema(p)

    # універсальний редактор для sku/barcode
    meta_field = st.get("_edit_field")
    txt = (m.text or "").strip()

    if meta_field == "sku":
        p["sku"] = "" if txt == "-" else _normalize_sku(txt)
        await save_data(d)
        await state.clear()
        await m.answer("✅ SKU оновлено.")
        return await m.answer(product_card(p), parse_mode="HTML", reply_markup=edit_menu_kb(pid))

    if meta_field == "barcode":
        if txt == "-":
            p["barcode"] = _ensure_unique_barcode(d, "")
        else:
            p["barcode"] = _ensure_unique_barcode(d, txt)
        await save_data(d)
        await state.clear()
        await m.answer("✅ BARCODE оновлено.")
        return await m.answer(product_card(p), parse_mode="HTML", reply_markup=edit_menu_kb(pid))

    # звичайна назва
    name = (m.text or "").strip()
    if not name:
        return await m.answer("Введіть назву текстом.")
    p["name"] = name
    await save_data(d)
    await state.clear()
    await m.answer("✅ Назву оновлено.")
    await m.answer(product_card(p), parse_mode="HTML", reply_markup=edit_menu_kb(pid))


@router.message(EditProductFSM.price)
async def edit_price(m: types.Message, state: FSMContext):
    d = await load_data()
    st = await state.get_data()
    pid = int(st.get("pid", 0) or 0)

    if not is_staff(d, m.from_user.id) or not can_edit_catalog(d, m.from_user.id):
        await state.clear()
        return await m.answer("⛔️ Немає доступу")

    p = _find_product_by_id(d, pid)
    if not p:
        await state.clear()
        return await m.answer("Товар не знайдено")

    txt = (m.text or "").strip().replace(" ", "")
    try:
        price = int(float(txt))
    except Exception:
        return await m.answer("Ціна має бути числом.")

    if price < 0:
        price = 0

    _ensure_product_schema(p)
    p["base_price"] = price
    # якщо немає активної акції — актуальна ціна теж price
    if int(p.get("promo_price", 0) or 0) <= 0:
        p["price"] = price

    await save_data(d)
    await state.clear()
    await m.answer("✅ Ціну оновлено.")
    await m.answer(product_card(p), parse_mode="HTML", reply_markup=edit_menu_kb(pid))


@router.message(EditProductFSM.desc)
async def edit_desc(m: types.Message, state: FSMContext):
    d = await load_data()
    st = await state.get_data()
    pid = int(st.get("pid", 0) or 0)

    if not is_staff(d, m.from_user.id) or not can_edit_catalog(d, m.from_user.id):
        await state.clear()
        return await m.answer("⛔️ Немає доступу")

    p = _find_product_by_id(d, pid)
    if not p:
        await state.clear()
        return await m.answer("Товар не знайдено")

    txt = (m.text or "").strip()
    p["desc"] = "" if txt == "-" else txt

    await save_data(d)
    await state.clear()
    await m.answer("✅ Опис оновлено.")
    await m.answer(product_card(p), parse_mode="HTML", reply_markup=edit_menu_kb(pid))


@router.message(EditProductFSM.promo_price)
async def edit_promo_price(m: types.Message, state: FSMContext):
    d = await load_data()
    st = await state.get_data()
    pid = int(st.get("pid", 0) or 0)

    if not is_staff(d, m.from_user.id) or not can_edit_catalog(d, m.from_user.id):
        await state.clear()
        return await m.answer("⛔️ Немає доступу")

    p = _find_product_by_id(d, pid)
    if not p:
        await state.clear()
        return await m.answer("Товар не знайдено")

    txt = (m.text or "").strip().replace(" ", "")
    try:
        promo = int(float(txt))
    except Exception:
        return await m.answer("Акційна ціна має бути числом.")

    _ensure_product_schema(p)

    if promo <= 0:
        p["promo_price"] = 0
        p["promo_until_ts"] = None
        p["price"] = int(p.get("base_price", 0) or 0)
        await save_data(d)
        await state.clear()
        await m.answer("✅ Акцію прибрано.")
        return await m.answer(product_card(p), parse_mode="HTML", reply_markup=edit_menu_kb(pid))

    p["promo_price"] = promo
    p["price"] = promo  # застосовуємо одразу
    await state.set_state(EditProductFSM.promo_until)
    await state.update_data(pid=pid)
    await m.answer(
        "Введіть <b>до якої дати</b> діє акція (формат <code>YYYY-MM-DD</code>) або <code>-</code> (без дати):",
        parse_mode="HTML"
    )


@router.message(EditProductFSM.promo_until)
async def edit_promo_until(m: types.Message, state: FSMContext):
    d = await load_data()
    st = await state.get_data()
    pid = int(st.get("pid", 0) or 0)

    if not is_staff(d, m.from_user.id) or not can_edit_catalog(d, m.from_user.id):
        await state.clear()
        return await m.answer("⛔️ Немає доступу")

    p = _find_product_by_id(d, pid)
    if not p:
        await state.clear()
        return await m.answer("Товар не знайдено")

    txt = (m.text or "").strip()
    _ensure_product_schema(p)

    if txt == "-":
        p["promo_until_ts"] = None
        await save_data(d)
        await state.clear()
        await m.answer("✅ Акцію встановлено (без дати завершення).")
        return await m.answer(product_card(p), parse_mode="HTML", reply_markup=edit_menu_kb(pid))

    try:
        # YYYY-MM-DD
        dt = datetime.strptime(txt, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        p["promo_until_ts"] = int(dt.timestamp())
    except Exception:
        return await m.answer("Невірний формат. Приклад: 2026-02-01 або '-'")

    await save_data(d)
    await state.clear()
    await m.answer("✅ Дату завершення акції збережено.")
    await m.answer(product_card(p), parse_mode="HTML", reply_markup=edit_menu_kb(pid))


# =========================================================
# ADD MANAGER / ROLE (AdminFSM.add_manager)
# =========================================================

@router.message(AdminFSM.add_manager)
async def add_manager(m: types.Message, state: FSMContext):
    d = await load_data()
    if not is_staff(d, m.from_user.id) or not can_manage_staff(d, m.from_user.id):
        await state.clear()
        return await m.answer("⛔️ Тільки адмін")

    txt = (m.text or "").strip()
    try:
        uid = int(txt)
    except Exception:
        return await m.answer("ID має бути числом.")

    # додаємо в managers (для сумісності зі старим is_staff)
    d.setdefault("managers", [])
    if uid not in [int(x) for x in (d.get("managers", []) or [])]:
        d["managers"].append(uid)

    # питаємо роль через кнопки
    kb = InlineKeyboardBuilder()
    kb.button(text="👨‍💼 Менеджер", callback_data=f"adm:role:set:{uid}:manager")
    kb.button(text="📦 Пакувальник", callback_data=f"adm:role:set:{uid}:packer")
    kb.button(text="⬅️ Скасувати", callback_data="adm:cancel")
    kb.adjust(1)

    await save_data(d)
    await state.clear()
    await m.answer(
        f"✅ Додано ID <code>{uid}</code>.\nОберіть роль:",
        parse_mode="HTML",
        reply_markup=kb.as_markup()
    )


@router.callback_query(F.data.startswith("adm:role:set:"))
async def set_role(cb: types.CallbackQuery):
    d = await load_data()
    if not is_staff(d, cb.from_user.id) or not can_manage_staff(d, cb.from_user.id):
        return await cb.answer("⛔️ Тільки адмін", show_alert=True)

    # adm:role:set:<uid>:<role>
    parts = cb.data.split(":")
    uid = int(parts[3])
    role = (parts[4] or "").strip().lower()
    if role not in ("manager", "packer"):
        role = "manager"

    d.setdefault("roles", {})
    d["roles"][str(uid)] = role

    # для пакувальника можна НЕ додавати в managers, але ми вже додали для сумісності — ок
    await save_data(d)

    await cb.message.answer(f"✅ Роль для <code>{uid}</code> встановлено: <b>{role}</b>", parse_mode="HTML")
    await cb.answer()


# =========================================================
# BUYER SEARCH (AdminFSM.search_buyer)
# =========================================================

def _match_user(order: dict, q: str) -> bool:
    ql = (q or "").strip().lower()
    if not ql:
        return False

    uid = str(order.get("user_id", "") or "")
    uname = str(order.get("username", "") or "")
    name = str(order.get("name", "") or order.get("full_name", "") or "")

    if ql.isdigit() and uid == ql:
        return True

    if ql.startswith("@") and uname.lower() == ql[1:]:
        return True

    # частковий збіг
    if ql in uname.lower() or ql in name.lower():
        return True

    return False


@router.message(AdminFSM.search_buyer)
async def search_buyer(m: types.Message, state: FSMContext):
    d = await load_data()
    if not is_staff(d, m.from_user.id) or not can_manage_orders(d, m.from_user.id):
        await state.clear()
        return await m.answer("⛔️ Немає доступу")

    q = (m.text or "").strip()
    if not q:
        return await m.answer("Введіть запит.")

    orders = d.get("orders", []) or []
    found = [o for o in orders if _match_user(o, q)]

    if not found:
        return await m.answer("Нічого не знайдено.")

    # групуємо по user_id
    groups: dict[int, list[dict]] = {}
    for o in found:
        try:
            uid = int(o.get("user_id", 0) or 0)
        except Exception:
            uid = 0
        groups.setdefault(uid, []).append(o)

    for uid, arr in groups.items():
        arr_sorted = sorted(arr, key=lambda x: int(x.get("created_ts", 0) or 0), reverse=True)
        link = f'<a href="tg://user?id={uid}">👤 Покупець</a>' if uid else "👤 Покупець"
        await m.answer(f"{link}\n<b>Знайдено замовлень:</b> {len(arr_sorted)}", parse_mode="HTML")

        for o in arr_sorted[:15]:  # ліміт щоб не спамити
            products = _order_products(d, o)
            kb = order_actions_kb(int(o.get("id", 0)), str(o.get("status", "")), d=d, uid=m.from_user.id)
            await m.answer(
                order_premium_text(d, o, products),
                parse_mode="HTML",
                reply_markup=kb
            )

    await state.clear()

# =========================================================

def _pids_in_sub(d: dict, cat: str, sub: str) -> list[int]:
    """
    Дістаємо pid'и товарів у підкатегорії:
    1) categories[cat][sub] як список pid (головне джерело)
    2) fallback: по полях товару category + sub_category / subcategory
    """
    out: list[int] = []

    cats_map = (d.get("categories", {}) or {})
    subs_map = (cats_map.get(cat, {}) or {})
    bucket = subs_map.get(sub)

    if isinstance(bucket, list):
        for x in bucket:
            try:
                out.append(int(x))
            except Exception:
                pass

    # fallback якщо bucket порожній/не заповнений
    if not out:
        for p in (d.get("products", []) or []):
            try:
                pc = str(p.get("category", "") or "")
                ps = str(
                    p.get("sub_category", p.get("subcategory", ""))  # підтримка обох назв
                    or NO_SUB
                )
                if pc == str(cat) and ps == str(sub):
                    out.append(int(p.get("id")))
            except Exception:
                continue

    # uniq
    seen = set()
    uniq: list[int] = []
    for pid in out:
        if pid not in seen:
            seen.add(pid)
            uniq.append(pid)
    return uniq


@router.callback_query(F.data.startswith("adm:plist_cat:cat_i:"))
async def adm_products_choose_cat(cb: types.CallbackQuery):
    d = await load_data()
    if not is_staff(d, cb.from_user.id):
        return await cb.answer("Немає доступу", show_alert=True)

    cat_i = int(cb.data.split(":")[-1])
    cats = list((d.get("categories", {}) or {}).keys())
    if cat_i < 0 or cat_i >= len(cats):
        return await cb.answer("Категорію не знайдено", show_alert=True)

    cat = cats[cat_i]
    await cb.message.answer(
        f"📦 <b>Товари</b>\nКатегорія: <b>{cat}</b>\n\nОберіть підкатегорію:",
        parse_mode="HTML",
        reply_markup=await subs_inline(cat_i, "plist_sub", include_no_sub=True),
    )
    return await cb.answer()


@router.callback_query(F.data.startswith("adm:catmgmt:sub_i:"))
async def adm_submgmt_open(cb: types.CallbackQuery):
    d = await load_data()
    if not is_staff(d, cb.from_user.id):
        return await cb.answer("Немає доступу", show_alert=True)

    # adm:catmgmt:sub_i:<cat_i>:<sub_i|n>
    parts = cb.data.split(":")
    cat_i = int(parts[-2])
    sub_token = parts[-1]

    cats = list((d.get("categories", {}) or {}).keys())
    if cat_i < 0 or cat_i >= len(cats):
        return await cb.answer("Категорію не знайдено", show_alert=True)
    cat = cats[cat_i]

    if sub_token == "n":
        sub_title = "🧷 Утлет"
        can_delete = False
    else:
        subs_map = (d.get("categories", {}) or {}).get(cat, {}) or {}
        subs_list = [s for s in subs_map.keys() if s != NO_SUB]
        try:
            j = int(sub_token)
            sub_title = str(subs_list[j])
        except Exception:
            return await cb.answer("Підкатегорію не знайдено", show_alert=True)
        can_delete = True

    kb = InlineKeyboardBuilder()
    kb.button(text="📦 Товари в підкатегорії", callback_data=f"adm:plist_sub:sub_i:{cat_i}:{sub_token}")
    if can_delete:
        kb.button(text="🗑 Видалити підкатегорію", callback_data=f"adm:subdelask:{cat_i}:{sub_token}")
    kb.button(text="⬅️ Назад", callback_data="adm:panel:cats")
    kb.adjust(1)

    await cb.message.answer(
        f"🛠 <b>Керування</b>\nКатегорія: <b>{cat}</b>\nПідкатегорія: <b>{sub_title}</b>",
        parse_mode="HTML",
        reply_markup=kb.as_markup(),
    )
    return await cb.answer()


# =========================================================
# SUBCATEGORY DELETE (ASK / DO)
# =========================================================

@router.callback_query(F.data.startswith("adm:subdelask:"))
async def sub_delete_ask(cb: types.CallbackQuery):
    d = await load_data()
    if not is_staff(d, cb.from_user.id) or not can_edit_catalog(d, cb.from_user.id):
        return await cb.answer("⛔️ Немає доступу", show_alert=True)

    # adm:subdelask:<cat_i>:<sub_token>
    parts = cb.data.split(":")
    cat_i = int(parts[2])
    sub_token = parts[3]

    cat = await _cat_by_index(cat_i)
    sub = await _sub_by_index(cat_i, sub_token)

    if not cat or sub is None:
        return await cb.answer("Не знайдено", show_alert=True)

    # Утлет видаляти не можна
    if sub == NO_SUB:
        return await cb.answer("🧷 Утлет видаляти не можна", show_alert=True)

    # перевіримо, чи є товари
    pids = _pids_in_sub(d, cat, sub)
    cnt = len(pids)

    kb = InlineKeyboardBuilder()
    if cnt > 0:
        kb.button(
            text=f"✅ Так, видалити і перенести {cnt} товар(ів) в 🧷 Утлет",
            callback_data=f"adm:subdeldo:{cat_i}:{sub_token}:mv"
        )
        kb.button(text="❌ Ні", callback_data="adm:cancel")
        kb.adjust(1)

        await cb.message.answer(
            f"⚠️ Підкатегорія <b>{sub}</b> містить товарів: <b>{cnt}</b>\n\n"
            f"Видалити підкатегорію і перенести всі товари в <b>🧷 Утлет</b>?",
            parse_mode="HTML",
            reply_markup=kb.as_markup()
        )
        return await cb.answer()

    # порожня — видаляємо без переносу
    kb.button(text="✅ Так, видалити", callback_data=f"adm:subdeldo:{cat_i}:{sub_token}:del")
    kb.button(text="❌ Ні", callback_data="adm:cancel")
    kb.adjust(2)

    await cb.message.answer(
        f"⚠️ Видалити підкатегорію <b>{sub}</b> в категорії <b>{cat}</b>?",
        parse_mode="HTML",
        reply_markup=kb.as_markup()
    )
    return await cb.answer()


@router.callback_query(F.data.startswith("adm:subdeldo:"))
async def sub_delete_do(cb: types.CallbackQuery):
    d = await load_data()
    if not is_staff(d, cb.from_user.id) or not can_edit_catalog(d, cb.from_user.id):
        return await cb.answer("⛔️ Немає доступу", show_alert=True)

    # adm:subdeldo:<cat_i>:<sub_token>:<mode>
    parts = cb.data.split(":")
    cat_i = int(parts[2])
    sub_token = parts[3]
    mode = parts[4] if len(parts) > 4 else "del"

    cat = await _cat_by_index(cat_i)
    sub = await _sub_by_index(cat_i, sub_token)

    if not cat or sub is None:
        return await cb.answer("Не знайдено", show_alert=True)

    if sub == NO_SUB:
        return await cb.answer("🧷 Утлет видаляти не можна", show_alert=True)

    cats_map = d.get("categories", {}) or {}
    subs_map = (cats_map.get(cat, {}) or {})

    # якщо немає такої підкатегорії — нічого робити
    if sub not in subs_map:
        return await cb.answer("Підкатегорію не знайдено", show_alert=True)

    # Якщо mode == mv: переносимо pid'и в Утлет, потім видаляємо підкатегорію
    if mode == "mv":
        pids = _pids_in_sub(d, cat, sub)
        subs_map.setdefault(NO_SUB, [])
        # додаємо без дублікатів
        exist = set(int(x) for x in subs_map.get(NO_SUB, []) or [] if str(x).isdigit() or isinstance(x, int))
        for pid in pids:
            if pid not in exist:
                subs_map[NO_SUB].append(pid)
                exist.add(pid)

    # видаляємо підкатегорію (разом зі списком pid)
    subs_map.pop(sub, None)

    # запис назад
    cats_map[cat] = subs_map
    d["categories"] = cats_map
    await save_data(d)

    await cb.message.answer(f"✅ Підкатегорію <b>{sub}</b> видалено.", parse_mode="HTML")
    await cb.answer()