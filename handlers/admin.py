# handlers/admin.py
from __future__ import annotations

import re
import random
import string
from html import escape
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from aiogram import Router, types, F, Bot
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder

from data import default_data, save_data, load_data
from data import load_data, save_data, next_product_id, find_product
from states import AdminFSM, EditProductFSM
from utils import is_admin, is_staff, notify_user, format_order_text
from text import order_premium_text, product_card

from audit import fmt_ts, audit_add, pick_fields
from orders_timeline import (
    order_set_status,
    order_set_ttn,
    render_timeline_text,
)

router = Router()

NO_SUB = "_"                 # системна підкатегорія
TRASH_CAT = "🧷 Утлет"       # системна категорія (для переносу)


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
# ROLES / PERMISSIONS
# data["roles"] = {"123": "manager"|"packer"|"admin"}
# =========================================================

ROLE_ADMIN = "admin"
ROLE_MANAGER = "manager"
ROLE_PACKER = "packer"


def _role_of(d: dict, uid: int) -> str:
    roles = d.get("roles", {}) or {}
    r = (roles.get(str(uid)) or "").strip().lower()

    if r in (ROLE_ADMIN, ROLE_MANAGER, ROLE_PACKER):
        return r

    # “вшитий” адмін з config/utils (твій is_admin)
    if is_admin(uid):
        return ROLE_ADMIN

    return ROLE_MANAGER


def can_manage_orders(d: dict, uid: int) -> bool:
    return _role_of(d, uid) in (ROLE_ADMIN, ROLE_MANAGER, ROLE_PACKER)


def can_edit_catalog(d: dict, uid: int) -> bool:
    return _role_of(d, uid) in (ROLE_ADMIN, ROLE_MANAGER)


def can_manage_staff(d: dict, uid: int) -> bool:
    return _role_of(d, uid) == ROLE_ADMIN


def can_set_ttn(d: dict, uid: int) -> bool:
    return _role_of(d, uid) in (ROLE_ADMIN, ROLE_MANAGER)


def can_mark_packing(d: dict, uid: int) -> bool:
    return _role_of(d, uid) in (ROLE_ADMIN, ROLE_MANAGER, ROLE_PACKER)


def can_mark_logistics(d: dict, uid: int) -> bool:
    return _role_of(d, uid) in (ROLE_ADMIN, ROLE_MANAGER)


# =========================================================
# SMALL HELPERS
# =========================================================

def _hits_set(d: dict) -> set[int]:
    raw = d.get("hits", []) or []
    out: set[int] = set()
    for x in raw:
        try:
            out.add(int(x))
        except Exception:
            pass
    return out


def _ensure_product_schema(p: dict) -> None:
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
    - [pid, pid, ...]
    - [{"pid": 12, "qty": 2}, ...]
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


def _ttn_norm(s: str) -> str:
    s = (s or "").strip()
    if s == "-":
        return ""
    return re.sub(r"\s+", "", s)


# =========================================================
# INLINE KB
# =========================================================

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
# PANEL KB
# =========================================================

def panel_main_kb(uid: int) -> types.InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🧩 Каталог", callback_data="adm:panel:catalog")
    kb.button(text="📄 Накладна (нові)", callback_data="adm:panel:picklist_new")
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
    kb.button(text="📄 Накладна (нові)", callback_data="adm:panel:picklist_new")
    kb.button(text="📋 Нові (оплачені)", callback_data="adm:panel:orders_paid")
    kb.button(text="📦 Усі замовлення", callback_data="adm:panel:orders_all")
    kb.button(text="🔎 Пошук покупця", callback_data="adm:panel:buyer_search")
    kb.button(text="⬅️ Назад", callback_data="adm:panel:back")
    kb.adjust(1)
    return kb.as_markup()


def panel_settings_kb(uid: int) -> types.InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if is_admin(uid):
        kb.button(text="👤 Додати/керувати персоналом", callback_data="adm:panel:add_manager")
        kb.button(text="👥 Ролі персоналу", callback_data="adm:roles:list")
        kb.button(text="📜 Історія змін", callback_data="adm:audit:last:20:0")
    kb.button(text="⬅️ Назад", callback_data="adm:panel:back")
    kb.adjust(1)
    return kb.as_markup()


# =========================================================
# AUDIT VIEW
# =========================================================

@router.callback_query(F.data.startswith("adm:audit:last:"))
async def audit_show(cb: types.CallbackQuery):
    d = await load_data()
    if not is_staff(d, cb.from_user.id):
        return await cb.answer("Немає доступу", show_alert=True)

    parts = cb.data.split(":")
    limit = int(parts[3])
    offset = int(parts[4])

    logs = list(d.get("audit", []) or [])
    logs = list(reversed(logs))  # newest first

    chunk = logs[offset: offset + limit]
    if not chunk:
        await cb.message.answer("📜 Історія змін порожня.")
        return await cb.answer()

    lines = ["📜 <b>Історія змін</b>\n"]
    for e in chunk:
        ts = fmt_ts(e.get("ts", 0))
        actor_id = e.get("actor_id", 0)
        actor_role = e.get("actor_role", "manager")
        action = e.get("action", "")
        ent = e.get("entity", {}) or {}
        et = ent.get("type", "")
        eid = ent.get("id", "")
        ename = ent.get("name", "")

        lines.append(
            f"🕒 <code>{escape(str(ts))}</code>\n"
            f"👤 <a href=\"tg://user?id={actor_id}\">{actor_id}</a> (<code>{escape(str(actor_role))}</code>)\n"
            f"⚙️ <code>{escape(str(action))}</code>\n"
            f"📌 <b>{escape(str(et))}</b> | ID: <code>{escape(str(eid))}</code> | <b>{escape(str(ename))}</b>\n"
        )

        before = e.get("before")
        after = e.get("after")
        if isinstance(before, dict) or isinstance(after, dict):
            lines.append("🔁 <b>Зміни:</b>")
            keys = set()
            if isinstance(before, dict):
                keys |= set(before.keys())
            if isinstance(after, dict):
                keys |= set(after.keys())
            for k in sorted(keys):
                bv = None if not isinstance(before, dict) else before.get(k)
                av = None if not isinstance(after, dict) else after.get(k)
                if bv != av:
                    lines.append(f" • <code>{escape(str(k))}</code>: <code>{escape(str(bv))}</code> → <code>{escape(str(av))}</code>")

        note = (e.get("note") or "").strip()
        if note:
            lines.append(f"📝 {escape(note)}")

        lines.append("\n———\n")

    kb = InlineKeyboardBuilder()
    if offset + limit < len(logs):
        kb.button(text="➡️ Далі", callback_data=f"adm:audit:last:{limit}:{offset+limit}")
    if offset > 0:
        kb.button(text="⬅️ Назад", callback_data=f"adm:audit:last:{limit}:{max(0, offset-limit)}")
    kb.button(text="🔙 В панель", callback_data="adm:panel:settings")
    kb.adjust(2, 1)

    await cb.message.answer("\n".join(lines).strip(), parse_mode="HTML", reply_markup=kb.as_markup(), disable_web_page_preview=True)
    await cb.answer()


# =========================================================
# ENTRY / CANCEL
# =========================================================

@router.message(Command("admin"))
async def admin_cmd(m: types.Message, state: FSMContext):
    d = await load_data()
    if not is_staff(d, m.from_user.id):
        return await m.answer("⛔️ Немає доступу")
    await state.clear()
    await m.answer("🔧 <b>Панель</b>\nОберіть розділ:", parse_mode="HTML", reply_markup=panel_main_kb(m.from_user.id))


@router.callback_query(F.data == "adm:cancel")
async def cancel_cb(cb: types.CallbackQuery, state: FSMContext):
    d = await load_data()
    if not is_staff(d, cb.from_user.id):
        return await cb.answer("Немає доступу", show_alert=True)

    await state.clear()
    await cb.message.answer("🔧 Панель (Адмін/Персонал)", reply_markup=panel_main_kb(cb.from_user.id))
    await cb.answer()


# =========================================================
# PANEL NAV
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

    # ----- CATALOG -----
    if action == "add_cat":
        if not can_edit_catalog(d, cb.from_user.id):
            return await cb.answer("⛔️ Недостатньо прав", show_alert=True)
        await state.set_state(AdminFSM.add_cat)
        await cb.message.answer("Введіть назву категорії:")
        return await cb.answer()

    if action == "add_sub":
        if not can_edit_catalog(d, cb.from_user.id):
            return await cb.answer("⛔️ Недостатньо прав", show_alert=True)
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
        if not can_edit_catalog(d, cb.from_user.id):
            return await cb.answer("⛔️ Недостатньо прав", show_alert=True)
        await state.set_state(AdminFSM.prod_cat)
        await cb.message.answer("Оберіть категорію:", reply_markup=await cats_inline("prod_cat"))
        return await cb.answer()

    # ----- ORDERS -----
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

        orders = d.get("orders", []) or []
        orders_sorted = sorted(orders, key=lambda x: int(x.get("created_ts", 0) or 0))

        for o in orders_sorted:
            products = _order_products(d, o)
            await cb.message.answer(
                order_premium_text(d, o, products),
                parse_mode="HTML",
                reply_markup=order_actions_kb(int(o["id"]), str(o.get("status", "")), d=d, uid=cb.from_user.id)
            )
        return await cb.answer()
        
    if action == "picklist_new":
        if not can_manage_orders(d, cb.from_user.id):
            return await cb.answer("⛔️ Недостатньо прав", show_alert=True)

        orders = d.get("orders", []) or []
    # “нові/в роботі” — налаштуй під себе:
        new_orders = [o for o in orders if (o.get("status") or "").strip().lower() in ("pending", "paid", "prepay", "new", "in_work")]

        if not new_orders:
            await cb.message.answer("✅ Немає нових замовлень для складу.")
            return await cb.answer()

    # найновіші зверху:
        new_orders.sort(key=lambda x: int(x.get("created_ts", 0) or 0), reverse=True)

        for o in new_orders:
            await cb.message.answer(picklist_order_text(d, o), parse_mode="HTML")

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
            "Приклад: <code>123456789</code> або <code>@katas</code> або <code>Віктор</code>",
            parse_mode="HTML"
        )
        return await cb.answer()

    if action == "add_manager":
        if not can_manage_staff(d, cb.from_user.id):
            return await cb.answer("⛔️ Тільки адмін", show_alert=True)

        await state.set_state(AdminFSM.add_manager)
        await cb.message.answer(
            "Введіть ID користувача.\n"
            "Або щоб зняти доступ — введіть так: <code>-123456789</code>",
            parse_mode="HTML"
        )
        return await cb.answer()

    return await cb.answer("Невідома дія", show_alert=True)


# =========================================================
# ORDER ACTIONS KB
# =========================================================

def order_actions_kb(
    oid: int,
    status: str,
    *,
    d: Optional[dict] = None,
    uid: Optional[int] = None,
) -> types.InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    st = (status or "").strip().lower()

    allow_any = (d is None or uid is None)

    def _allow(fn):
        return True if allow_any else fn(d, uid)

    if st in ("paid", "prepay") and _allow(can_manage_orders):
        kb.button(text="🟡 В роботу", callback_data=f"adm:order:in_work:{oid}")

    if st in ("paid", "prepay", "in_work", "packed") and _allow(can_mark_packing):
        kb.button(text="📦 Запаковано", callback_data=f"adm:order:packed:{oid}")

    if st in ("paid", "prepay", "in_work", "packed", "shipped") and _allow(can_mark_logistics):
        kb.button(text="🚚 Відправлено + ТТН", callback_data=f"adm:order:shipped:{oid}")

    if st in ("shipped", "arrived") and _allow(can_mark_logistics):
        kb.button(text="📍 Прибуло у відділення", callback_data=f"adm:order:arrived:{oid}")
        kb.button(text="✅ Отримано (клієнт)", callback_data=f"adm:order:received:{oid}")
        kb.button(text="❌ Не забрав", callback_data=f"adm:order:not_picked:{oid}")

    if st in ("shipped", "arrived", "not_picked") and _allow(can_mark_logistics):
        kb.button(text="🔁 Повернуто", callback_data=f"adm:order:returned:{oid}")

    if st in ("paid", "prepay", "in_work", "packed", "shipped", "arrived", "received", "not_picked", "returned") and _allow(can_mark_logistics):
        kb.button(text="✅ Закрити (done)", callback_data=f"adm:order:done:{oid}")

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
# ORDERS: CHANGE STATUS + TTN + TIMELINE + HISTORY
# =========================================================

@router.callback_query(F.data.startswith("adm:order:"))
async def order_change_status(cb: types.CallbackQuery, bot: Bot, state: FSMContext):
    d = await load_data()
    if not is_staff(d, cb.from_user.id):
        return await cb.answer("Немає доступу", show_alert=True)

    _, _, action, oid_str = cb.data.split(":")
    oid = int(oid_str)

    order = _find_order(d, oid)
    if not order:
        await cb.message.answer("❌ Замовлення не знайдено.")
        return await cb.answer()

    before = pick_fields(order, ["status", "ttn", "np_ttn"])

    async def _reply_updated(prefix_text: str):
        products = _order_products(d, order)
        kb = order_actions_kb(oid, str(order.get("status", "")), d=d, uid=cb.from_user.id)
        await cb.message.answer(prefix_text + "\n\n" + order_premium_text(d, order, products), parse_mode="HTML", reply_markup=kb)

    st = (order.get("status") or "").strip().lower()

    if action == "in_work":
        if not can_manage_orders(d, cb.from_user.id):
            return await cb.answer("⛔️ Недостатньо прав", show_alert=True)
        if st not in ("paid", "prepay"):
            return await cb.answer("Тільки paid/prepay можна взяти в роботу", show_alert=True)

        order_set_status(order, "in_work", who=str(cb.from_user.id), details="Взято в роботу")
        after = pick_fields(order, ["status", "ttn", "np_ttn"])
        audit_add(d, actor_id=cb.from_user.id, actor_role=_role_of(d, cb.from_user.id),
                  action="order.in_work", entity_type="order", entity_id=oid, entity_name=f"#{oid}",
                  before=before, after=after)

        await save_data(d)
        await _reply_updated(f"🟡 Замовлення #{oid} взято в роботу.")
        await _notify_buyer(bot, d, order, f"🟡 Ваше замовлення #{oid} взято в роботу ✅")
        return await cb.answer()

    if action == "packed":
        if not can_mark_packing(d, cb.from_user.id):
            return await cb.answer("⛔️ Недостатньо прав", show_alert=True)
        if st not in ("paid", "prepay", "in_work", "packed"):
            return await cb.answer("Запакувати можна після paid/prepay/in_work", show_alert=True)

        order_set_status(order, "packed", who=str(cb.from_user.id), details="Запаковано")
        after = pick_fields(order, ["status", "ttn", "np_ttn"])
        audit_add(d, actor_id=cb.from_user.id, actor_role=_role_of(d, cb.from_user.id),
                  action="order.packed", entity_type="order", entity_id=oid, entity_name=f"#{oid}",
                  before=before, after=after)

        await save_data(d)
        await _reply_updated(f"📦 Замовлення #{oid} запаковано.")
        await _notify_buyer(bot, d, order, f"📦 Ваше замовлення #{oid} запаковано ✅")
        return await cb.answer()

    if action == "shipped":
        if not can_mark_logistics(d, cb.from_user.id):
            return await cb.answer("⛔️ Недостатньо прав", show_alert=True)
        if st not in ("paid", "prepay", "in_work", "packed", "shipped"):
            return await cb.answer("Неможливо позначити як відправлено", show_alert=True)

        order_set_status(order, "shipped", who=str(cb.from_user.id), details="Позначено як відправлено (очікуємо ТТН)")
        after = pick_fields(order, ["status", "ttn", "np_ttn"])
        audit_add(d, actor_id=cb.from_user.id, actor_role=_role_of(d, cb.from_user.id),
                  action="order.shipped", entity_type="order", entity_id=oid, entity_name=f"#{oid}",
                  before=before, after=after)

        await save_data(d)
        await _reply_updated(f"🚚 Замовлення #{oid} позначено як ВІДПРАВЛЕНО.")

        await state.clear()
        await state.set_state(AdminFSM.order_ttn)
        await state.update_data(oid=oid)
        await cb.message.answer("📮 Введіть ТТН для цього замовлення (або '-' щоб без ТТН):")
        return await cb.answer()

    if action == "arrived":
        if not can_mark_logistics(d, cb.from_user.id):
            return await cb.answer("⛔️ Недостатньо прав", show_alert=True)
        if st not in ("shipped", "arrived"):
            return await cb.answer("Прибуло доречно тільки після 'Відправлено'", show_alert=True)

        order_set_status(order, "arrived", who=str(cb.from_user.id), details="Прибуло у відділення")
        after = pick_fields(order, ["status", "ttn", "np_ttn"])
        audit_add(d, actor_id=cb.from_user.id, actor_role=_role_of(d, cb.from_user.id),
                  action="order.arrived", entity_type="order", entity_id=oid, entity_name=f"#{oid}",
                  before=before, after=after)

        await save_data(d)
        await _reply_updated(f"📍 Замовлення #{oid}: прибуло у відділення.")
        await _notify_buyer(bot, d, order, f"📍 Замовлення #{oid}: прибуло у відділення ✅")
        return await cb.answer()

    if action == "received":
        if not can_mark_logistics(d, cb.from_user.id):
            return await cb.answer("⛔️ Недостатньо прав", show_alert=True)
        if st not in ("shipped", "arrived", "received"):
            return await cb.answer("Отримано доречно після shipped/arrived", show_alert=True)

        order_set_status(order, "received", who=str(cb.from_user.id), details="Клієнт отримав/забрав")
        after = pick_fields(order, ["status", "ttn", "np_ttn"])
        audit_add(d, actor_id=cb.from_user.id, actor_role=_role_of(d, cb.from_user.id),
                  action="order.received", entity_type="order", entity_id=oid, entity_name=f"#{oid}",
                  before=before, after=after)

        await save_data(d)
        await _reply_updated(f"✅ Замовлення #{oid}: клієнт ОТРИМАВ.")
        await _notify_buyer(bot, d, order, f"✅ Замовлення #{oid}: отримано. Дякуємо! 🙌")
        return await cb.answer()

    if action == "not_picked":
        if not can_mark_logistics(d, cb.from_user.id):
            return await cb.answer("⛔️ Недостатньо прав", show_alert=True)
        if st not in ("shipped", "arrived", "not_picked"):
            return await cb.answer("Не забрав доречно після shipped/arrived", show_alert=True)

        order_set_status(order, "not_picked", who=str(cb.from_user.id), details="Клієнт не забрав")
        after = pick_fields(order, ["status", "ttn", "np_ttn"])
        audit_add(d, actor_id=cb.from_user.id, actor_role=_role_of(d, cb.from_user.id),
                  action="order.not_picked", entity_type="order", entity_id=oid, entity_name=f"#{oid}",
                  before=before, after=after)

        await save_data(d)
        await _reply_updated(f"❌ Замовлення #{oid}: НЕ ЗАБРАВ.")
        await _notify_buyer(bot, d, order, f"❌ Замовлення #{oid}: не забрано. Напишіть нам — допоможемо 🤝")
        return await cb.answer()

    if action == "returned":
        if not can_mark_logistics(d, cb.from_user.id):
            return await cb.answer("⛔️ Недостатньо прав", show_alert=True)
        if st not in ("shipped", "arrived", "not_picked", "returned", "received"):
            return await cb.answer("Повернення ставимо після логістики", show_alert=True)

        order_set_status(order, "returned", who=str(cb.from_user.id), details="Повернено")
        after = pick_fields(order, ["status", "ttn", "np_ttn"])
        audit_add(d, actor_id=cb.from_user.id, actor_role=_role_of(d, cb.from_user.id),
                  action="order.returned", entity_type="order", entity_id=oid, entity_name=f"#{oid}",
                  before=before, after=after)

        await save_data(d)
        await _reply_updated(f"🔁 Замовлення #{oid}: ПОВЕРНУТО.")
        await _notify_buyer(bot, d, order, f"🔁 Замовлення #{oid}: повернено. Якщо є питання — пишіть 🙏")
        return await cb.answer()

    if action == "done":
        if not can_mark_logistics(d, cb.from_user.id):
            return await cb.answer("⛔️ Недостатньо прав", show_alert=True)
        if st in ("done", "canceled"):
            return await cb.answer("Вже закрито", show_alert=True)

        order_set_status(order, "done", who=str(cb.from_user.id), details="Закрито (done)")
        after = pick_fields(order, ["status", "ttn", "np_ttn"])
        audit_add(d, actor_id=cb.from_user.id, actor_role=_role_of(d, cb.from_user.id),
                  action="order.done", entity_type="order", entity_id=oid, entity_name=f"#{oid}",
                  before=before, after=after)

        await save_data(d)
        await _reply_updated(f"✅ Замовлення #{oid} закрито.")
        await _notify_buyer(bot, d, order, f"✅ Замовлення #{oid} завершено 🎉")
        return await cb.answer()

    if action == "set_ttn":
        if not can_set_ttn(d, cb.from_user.id):
            return await cb.answer("⛔️ Недостатньо прав", show_alert=True)

        await state.clear()
        await state.set_state(AdminFSM.order_ttn)
        await state.update_data(oid=oid)

        cur = (order.get("np_ttn") or order.get("ttn") or "").strip() or "—"
        await cb.message.answer(
            f"📮 Поточний ТТН: <code>{escape(cur)}</code>\n\n"
            "Введіть новий ТТН або <code>-</code> щоб очистити:",
            parse_mode="HTML"
        )
        return await cb.answer()

    if action == "timeline":
        txt = render_timeline_text(order)
        kb = InlineKeyboardBuilder()
        kb.button(text="⬅️ Назад", callback_data="adm:cancel")
        kb.adjust(1)
        await cb.message.answer(txt, parse_mode="HTML", reply_markup=kb.as_markup())
        return await cb.answer()

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

    before = pick_fields(order, ["ttn", "np_ttn"])
    order_set_ttn(order, ttn, who=str(m.from_user.id), details="TTN set from admin panel")
    after = pick_fields(order, ["ttn", "np_ttn"])

    audit_add(
        d,
        actor_id=m.from_user.id,
        actor_role=_role_of(d, m.from_user.id),
        action="order.ttn.set",
        entity_type="order",
        entity_id=oid,
        entity_name=f"#{oid}",
        before=before,
        after=after,
        note="TTN updated from admin panel",
    )

    await save_data(d)
    await state.clear()

    if not ttn:
        await m.answer("✅ ТТН очищено.")
        return

    await m.answer("✅ ТТН збережено.")
    if (order.get("status") or "").strip().lower() in ("shipped", "sent"):
        await _notify_buyer(bot, d, order, f"🚚 Ваше замовлення #{oid} відправлено ✅")
# =========================================================
# CATALOG: CATEGORY / SUBCATEGORY MANAGEMENT
# =========================================================

def _pids_in_sub(d: dict, cat: str, sub: str) -> list[int]:
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

    # fallback: по товару
    if not out:
        for p in (d.get("products", []) or []):
            try:
                pc = str(p.get("category", "") or "")
                ps = str(p.get("sub_category", p.get("subcategory", "")) or NO_SUB)
                if pc == str(cat) and ps == str(sub):
                    out.append(int(p.get("id")))
            except Exception:
                continue

    seen = set()
    uniq: list[int] = []
    for pid in out:
        if pid not in seen:
            seen.add(pid)
            uniq.append(pid)
    return uniq


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
        f"🗂 <b>{escape(str(cat))}</b>",
        "",
        "Оберіть підкатегорію для керування:",
    ]

    kb = InlineKeyboardBuilder()

    kb.button(text="🧷 Утлет", callback_data=f"adm:catmgmt:sub_i:{cat_i}:n")
    for j, s in enumerate(subs_list):
        kb.button(text=str(s), callback_data=f"adm:catmgmt:sub_i:{cat_i}:{j}")

    kb.adjust(1)

    kb.button(text="➕ Додати підкатегорію", callback_data=f"adm:sub_add:cat_i:{cat_i}")
    kb.button(text="📦 Товари в категорії", callback_data=f"adm:plist_cat:cat_i:{cat_i}")
    kb.button(text="🗑 Видалити категорію", callback_data=f"adm:catdelask:{cat_i}")
    kb.button(text="⬅️ Назад", callback_data="adm:panel:cats")
    kb.adjust(1)

    await cb.message.answer("\n".join(text_lines), parse_mode="HTML", reply_markup=kb.as_markup())
    await cb.answer()


@router.callback_query(F.data.startswith("adm:catmgmt:sub_i:"))
async def adm_submgmt_open(cb: types.CallbackQuery):
    d = await load_data()
    if not is_staff(d, cb.from_user.id):
        return await cb.answer("Немає доступу", show_alert=True)

    parts = cb.data.split(":")
    cat_i = int(parts[-2])
    sub_token = parts[-1]

    cats = list((d.get("categories", {}) or {}).keys())
    if cat_i < 0 or cat_i >= len(cats):
        return await cb.answer("Категорію не знайдено", show_alert=True)
    cat = cats[cat_i]

    if sub_token == "n":
        sub_title = "🧷 Утлет"
        can_delete_sub = False
    else:
        subs_map = (d.get("categories", {}) or {}).get(cat, {}) or {}
        subs_list = [s for s in subs_map.keys() if s != NO_SUB]
        try:
            j = int(sub_token)
            sub_title = str(subs_list[j])
        except Exception:
            return await cb.answer("Підкатегорію не знайдено", show_alert=True)
        can_delete_sub = True

    kb = InlineKeyboardBuilder()
    kb.button(text="📦 Товари в підкатегорії", callback_data=f"adm:plist_sub:sub_i:{cat_i}:{sub_token}")

    if can_delete_sub:
        kb.button(text="🗑 Видалити підкатегорію", callback_data=f"adm:subdelask:{cat_i}:{sub_token}")

    kb.button(text="🗑 Видалити категорію", callback_data=f"adm:catdelask:{cat_i}")
    kb.button(text="⬅️ Назад", callback_data="adm:panel:cats")
    kb.adjust(1)

    await cb.message.answer(
        f"🛠 <b>Керування</b>\nКатегорія: <b>{escape(str(cat))}</b>\nПідкатегорія: <b>{escape(str(sub_title))}</b>",
        parse_mode="HTML",
        reply_markup=kb.as_markup(),
    )
    return await cb.answer()


# =========================================================
# CATEGORY DELETE (ASK / DO) -> переносимо товари у TRASH_CAT/NO_SUB
# =========================================================

@router.callback_query(F.data.startswith("adm:catdelask:"))
async def cat_delete_ask(cb: types.CallbackQuery):
    d = await load_data()
    if not is_staff(d, cb.from_user.id) or not can_edit_catalog(d, cb.from_user.id):
        return await cb.answer("⛔️ Немає доступу", show_alert=True)

    cat_i = int(cb.data.split(":")[2])
    cats = list((d.get("categories", {}) or {}).keys())

    if cat_i < 0 or cat_i >= len(cats):
        return await cb.answer("Категорію не знайдено", show_alert=True)

    cat = cats[cat_i]
    subs = (d.get("categories", {}) or {}).get(cat, {}) or {}

    total_pids: list[int] = []
    for arr in subs.values():
        if isinstance(arr, list):
            for x in arr:
                try:
                    total_pids.append(int(x))
                except Exception:
                    pass

    total = len(set(total_pids))

    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Так, видалити (товари → 🧷 Утлет)", callback_data=f"adm:catdeldo:{cat_i}")
    kb.button(text="❌ Ні", callback_data="adm:cancel")
    kb.adjust(1)

    await cb.message.answer(
        f"⚠️ Видалити категорію <b>{escape(str(cat))}</b>?\n\n"
        f"Товарів у категорії: <b>{total}</b>\n"
        f"Усі товари буде перенесено в <b>{escape(TRASH_CAT)}</b>.",
        parse_mode="HTML",
        reply_markup=kb.as_markup()
    )
    await cb.answer()


@router.callback_query(F.data.startswith("adm:catdeldo:"))
async def cat_delete_do(cb: types.CallbackQuery):
    d = await load_data()
    if not is_staff(d, cb.from_user.id) or not can_edit_catalog(d, cb.from_user.id):
        return await cb.answer("⛔️ Немає доступу", show_alert=True)

    cat_i = int(cb.data.split(":")[2])
    cats = list((d.get("categories", {}) or {}).keys())

    if cat_i < 0 or cat_i >= len(cats):
        return await cb.answer("Категорію не знайдено", show_alert=True)

    cat = cats[cat_i]
    subs = d.get("categories", {}).get(cat, {}) or {}

    # зібрати всі pid
    outlet: list[int] = []
    for arr in subs.values():
        if isinstance(arr, list):
            for pid in arr:
                try:
                    outlet.append(int(pid))
                except Exception:
                    pass

    before = {"category": cat, "pids": sorted(list(set(outlet)))}

    # прибрати категорію
    d["categories"].pop(cat, None)

    # додати в TRASH_CAT/NO_SUB
    if outlet:
        d.setdefault("categories", {})
        d["categories"].setdefault(TRASH_CAT, {NO_SUB: []})
        d["categories"][TRASH_CAT].setdefault(NO_SUB, [])
        exist = set()
        for x in (d["categories"][TRASH_CAT][NO_SUB] or []):
            try:
                exist.add(int(x))
            except Exception:
                pass
        for pid in outlet:
            if pid not in exist:
                d["categories"][TRASH_CAT][NO_SUB].append(pid)
                exist.add(pid)

        # ще й оновимо category/sub_category в товарах (щоб було консистентно)
        for p in (d.get("products", []) or []):
            try:
                if int(p.get("id", -1)) in exist:
                    if str(p.get("category")) == str(cat):
                        p["category"] = TRASH_CAT
                        p["sub_category"] = NO_SUB
            except Exception:
                pass

    audit_add(
        d,
        actor_id=cb.from_user.id,
        actor_role=_role_of(d, cb.from_user.id),
        action="category.delete",
        entity_type="category",
        entity_id=cat,
        entity_name=cat,
        before=before,
        after={"moved_to": f"{TRASH_CAT}/{NO_SUB}"},
    )

    await save_data(d)
    await cb.message.answer(f"✅ Категорію <b>{escape(str(cat))}</b> видалено.", parse_mode="HTML")
    await cb.answer()


# =========================================================
# SUBCATEGORY DELETE (ASK / DO)
# =========================================================

@router.callback_query(F.data.startswith("adm:subdelask:"))
async def sub_delete_ask(cb: types.CallbackQuery):
    d = await load_data()
    if not is_staff(d, cb.from_user.id) or not can_edit_catalog(d, cb.from_user.id):
        return await cb.answer("⛔️ Немає доступу", show_alert=True)

    parts = cb.data.split(":")
    cat_i = int(parts[2])
    sub_token = parts[3]

    cat = await _cat_by_index(cat_i)
    sub = await _sub_by_index(cat_i, sub_token)

    if not cat or sub is None:
        return await cb.answer("Не знайдено", show_alert=True)

    if sub == NO_SUB:
        return await cb.answer("🧷 Утлет видаляти не можна", show_alert=True)

    pids = _pids_in_sub(d, cat, sub)
    cnt = len(pids)

    kb = InlineKeyboardBuilder()
    if cnt > 0:
        kb.button(text=f"✅ Так, видалити і перенести {cnt} товар(ів) в 🧷 Утлет",
                  callback_data=f"adm:subdeldo:{cat_i}:{sub_token}:mv")
        kb.button(text="❌ Ні", callback_data="adm:cancel")
        kb.adjust(1)

        await cb.message.answer(
            f"⚠️ Підкатегорія <b>{escape(str(sub))}</b> містить товарів: <b>{cnt}</b>\n\n"
            f"Видалити підкатегорію і перенести всі товари в <b>🧷 Утлет</b>?",
            parse_mode="HTML",
            reply_markup=kb.as_markup()
        )
        return await cb.answer()

    kb.button(text="✅ Так, видалити", callback_data=f"adm:subdeldo:{cat_i}:{sub_token}:del")
    kb.button(text="❌ Ні", callback_data="adm:cancel")
    kb.adjust(2)

    await cb.message.answer(
        f"⚠️ Видалити підкатегорію <b>{escape(str(sub))}</b> в категорії <b>{escape(str(cat))}</b>?",
        parse_mode="HTML",
        reply_markup=kb.as_markup()
    )
    return await cb.answer()


@router.callback_query(F.data.startswith("adm:subdeldo:"))
async def sub_delete_do(cb: types.CallbackQuery):
    d = await load_data()
    if not is_staff(d, cb.from_user.id) or not can_edit_catalog(d, cb.from_user.id):
        return await cb.answer("⛔️ Немає доступу", show_alert=True)

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

    if sub not in subs_map:
        return await cb.answer("Підкатегорію не знайдено", show_alert=True)

    pids = _pids_in_sub(d, cat, sub)
    before = {"category": cat, "sub": sub, "pids": sorted(list(set(pids)))}

    if mode == "mv":
        subs_map.setdefault(NO_SUB, [])
        exist = set()
        for x in (subs_map.get(NO_SUB, []) or []):
            try:
                exist.add(int(x))
            except Exception:
                pass
        for pid in pids:
            if pid not in exist:
                subs_map[NO_SUB].append(pid)
                exist.add(pid)

        # узгодимо product.category/sub_category
        for p in (d.get("products", []) or []):
            try:
                if int(p.get("id", -1)) in set(pids):
                    if str(p.get("category")) == str(cat) and str(p.get("sub_category", NO_SUB)) == str(sub):
                        p["sub_category"] = NO_SUB
            except Exception:
                pass

    subs_map.pop(sub, None)
    cats_map[cat] = subs_map
    d["categories"] = cats_map

    audit_add(
        d,
        actor_id=cb.from_user.id,
        actor_role=_role_of(d, cb.from_user.id),
        action="subcategory.delete",
        entity_type="subcategory",
        entity_id=f"{cat}::{sub}",
        entity_name=f"{cat} / {sub}",
        before=before,
        after={"mode": mode, "moved_to": NO_SUB if mode == "mv" else None},
    )

    await save_data(d)
    await cb.message.answer(f"✅ Підкатегорію <b>{escape(str(sub))}</b> видалено.", parse_mode="HTML")
    await cb.answer()


# =========================================================
# PRODUCTS LIST BY CATEGORY/SUBCATEGORY
# =========================================================

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
        f"📦 <b>Товари</b>\nКатегорія: <b>{escape(str(cat))}</b>\n\nОберіть підкатегорію:",
        parse_mode="HTML",
        reply_markup=await subs_inline(cat_i, "plist_sub", include_no_sub=True),
    )
    return await cb.answer()


@router.callback_query(F.data.startswith("adm:plist_sub:sub_i:"))
async def plist_sub(cb: types.CallbackQuery):
    d = await load_data()
    if not is_staff(d, cb.from_user.id):
        return await cb.answer("Немає доступу", show_alert=True)

    parts = cb.data.split(":")
    cat_i = int(parts[-2])
    sub_token = parts[-1]

    cat = await _cat_by_index(cat_i)
    sub = await _sub_by_index(cat_i, sub_token)
    if not cat or sub is None:
        return await cb.answer("Не знайдено", show_alert=True)

    pids = _pids_in_sub(d, cat, sub)
    if not pids:
        await cb.message.answer("Товарів тут ще немає.")
        return await cb.answer()

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


# =========================================================
# HIT TOGGLE + PRODUCT DELETE
# =========================================================

@router.callback_query(F.data.startswith("adm:hit:"))
async def hit_toggle(cb: types.CallbackQuery):
    d = await load_data()
    if not is_staff(d, cb.from_user.id) or not can_edit_catalog(d, cb.from_user.id):
        return await cb.answer("⛔️ Немає доступу", show_alert=True)

    _, _, mode, pid_str = cb.data.split(":")
    pid = int(pid_str)

    hits = _hits_set(d)
    before = {"hits": sorted(list(hits))}

    if mode == "on":
        hits.add(pid)
        note = "on"
        await cb.answer("🔥 Додано в Хіти")
    else:
        hits.discard(pid)
        note = "off"
        await cb.answer("❌ Прибрано з Хітів")

    d["hits"] = list(sorted(hits))
    after = {"hits": sorted(list(hits))}

    audit_add(
        d,
        actor_id=cb.from_user.id,
        actor_role=_role_of(d, cb.from_user.id),
        action="hits.toggle",
        entity_type="product",
        entity_id=pid,
        entity_name=str(pid),
        before=before,
        after=after,
        note=f"mode={note}"
    )

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
        f"⚠️ Видалити товар <b>{escape(str(p.get('name','')))}</b> (ID {pid})?",
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
    p_old = find_product(d, pid) or {}
    before_prod = pick_fields(p_old, ["id", "name", "sku", "barcode", "category", "sub_category", "price", "base_price", "promo_price", "promo_until_ts"])

    # видаляємо з products
    prods = d.get("products", []) or []
    d["products"] = [p for p in prods if int(p.get("id", -1)) != pid]

    # прибираємо з categories
    cats = d.get("categories", {}) or {}
    for cat, subs in (cats.items() if isinstance(cats, dict) else []):
        if not isinstance(subs, dict):
            continue
        for sub, arr in (subs.items() if isinstance(subs, dict) else []):
            if isinstance(arr, list):
                subs[sub] = [x for x in arr if str(x) != str(pid)]

    # прибираємо з hits
    hits = _hits_set(d)
    before_hits = {"hits": sorted(list(hits))}
    hits.discard(pid)
    d["hits"] = list(sorted(hits))
    after_hits = {"hits": sorted(list(hits))}

    audit_add(
        d,
        actor_id=cb.from_user.id,
        actor_role=_role_of(d, cb.from_user.id),
        action="product.delete",
        entity_type="product",
        entity_id=pid,
        entity_name=str(p_old.get("name", "")),
        before={"product": before_prod, **before_hits},
        after={"product": None, **after_hits},
    )

    await save_data(d)
    await cb.message.answer(f"✅ Товар <code>{pid}</code> видалено.", parse_mode="HTML")
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
    await cb.message.answer(product_card(p), parse_mode="HTML", reply_markup=edit_menu_kb(pid))
    await cb.answer()


# =========================================================
# BARCODE / SKU HELPERS
# =========================================================

def _gen_barcode_ean13_like() -> str:
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

    while cand in used:
        cand = _gen_barcode_ean13_like()
    return cand


def _normalize_sku(s: str) -> str:
    return (s or "").strip()


def _find_product_by_id(d: dict, pid: int) -> dict | None:
    for p in (d.get("products", []) or []):
        try:
            if int(p.get("id", -1)) == int(pid):
                return p
        except Exception:
            continue
    return None


# =========================================================
# ADD CATEGORY (FSM)
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

    d["categories"][name] = {NO_SUB: []}

    audit_add(
        d,
        actor_id=m.from_user.id,
        actor_role=_role_of(d, m.from_user.id),
        action="category.create",
        entity_type="category",
        entity_id=name,
        entity_name=name,
        before=None,
        after={"name": name},
    )

    await save_data(d)
    await state.clear()
    await m.answer(f"✅ Категорію <b>{escape(name)}</b> додано.", parse_mode="HTML", reply_markup=panel_main_kb(m.from_user.id))


# =========================================================
# ADD SUBCATEGORY (FSM)
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
    await cb.message.answer(f"Введіть назву підкатегорії для <b>{escape(str(cat))}</b>:", parse_mode="HTML")
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

    audit_add(
        d,
        actor_id=m.from_user.id,
        actor_role=_role_of(d, m.from_user.id),
        action="subcategory.create",
        entity_type="subcategory",
        entity_id=f"{cat}::{name}",
        entity_name=f"{cat} / {name}",
        before=None,
        after={"category": cat, "sub": name},
    )

    await save_data(d)
    await state.clear()
    await m.answer(f"✅ Підкатегорію <b>{escape(name)}</b> додано в <b>{escape(str(cat))}</b>.", parse_mode="HTML", reply_markup=panel_main_kb(m.from_user.id))


# =========================================================
# ADD PRODUCT (FSM)
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
        f"Оберіть підкатегорію для <b>{escape(str(cat))}</b>:",
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
    await cb.message.answer(f"Введіть <b>назву</b> товару (категорія: <b>{escape(str(cat))}</b> / <b>{escape(str(sub_name))}</b>):", parse_mode="HTML")
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
    await m.answer("Надішліть <b>фото</b> товару (1+). Коли готово — напишіть <code>готово</code> або <code>-</code> (без фото).", parse_mode="HTML")


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
            "photos": photos,
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

        audit_add(
            d,
            actor_id=m.from_user.id,
            actor_role=_role_of(d, m.from_user.id),
            action="product.create",
            entity_type="product",
            entity_id=pid,
            entity_name=p.get("name", ""),
            before=None,
            after=pick_fields(p, ["id","name","sku","barcode","category","sub_category","price","base_price","promo_price","promo_until_ts"]),
        )

        await save_data(d)
        await state.clear()

        sub_name = "🧷 Утлет" if sub == NO_SUB else sub
        await m.answer(
            "✅ Товар створено!\n\n"
            f"<b>{escape(name)}</b>\n"
            f"ID: <code>{pid}</code>\n"
            f"SKU: <code>{escape(sku or '—')}</code>\n"
            f"BARCODE: <code>{escape(barcode)}</code>\n"
            f"Категорія: <b>{escape(str(cat))}</b> / <b>{escape(str(sub_name))}</b>\n",
            parse_mode="HTML",
            reply_markup=panel_main_kb(m.from_user.id)
        )
        await m.answer(product_card(p), parse_mode="HTML", reply_markup=await product_actions_kb(pid))
        return

    # створити без фото
    if (m.text or "").strip() == "-":
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

        audit_add(
            d,
            actor_id=m.from_user.id,
            actor_role=_role_of(d, m.from_user.id),
            action="product.create",
            entity_type="product",
            entity_id=pid,
            entity_name=p.get("name", ""),
            before=None,
            after=pick_fields(p, ["id","name","sku","barcode","category","sub_category","price","base_price","promo_price","promo_until_ts"]),
            note="no_photos",
        )

        await save_data(d)
        await state.clear()

        await m.answer("✅ Товар створено (без фото).", reply_markup=panel_main_kb(m.from_user.id))
        await m.answer(product_card(p), parse_mode="HTML", reply_markup=await product_actions_kb(pid))
        return

    if m.photo:
        file_id = m.photo[-1].file_id
        photos.append(file_id)
        await state.update_data(photos=photos)
        return await m.answer(f"📷 Додано фото ({len(photos)}). Напишіть <code>готово</code>, коли достатньо.", parse_mode="HTML")

    return await m.answer("Надішліть фото або напишіть <code>готово</code> / <code>-</code>.", parse_mode="HTML")


# =========================================================
# PICKLIST / НАКЛАДНА (SKU × QTY) — для складу
# =========================================================

def _order_delivery(o: dict) -> dict:
    dd = o.get("delivery") or {}
    return dd if isinstance(dd, dict) else {}

def _item_sku_name_qty(d: dict, it: dict) -> tuple[str, str, int]:
    # беремо зі снапшота (order.items), якщо нема — доберемо з products
    sku = (it.get("sku") or "").strip()
    name = (it.get("name") or "").strip()

    pid = it.get("pid")
    if (not sku or not name) and pid is not None:
        p = find_product(d, int(pid)) or {}
        if not sku:
            sku = (p.get("sku") or "").strip()
        if not name:
            name = (p.get("name") or "").strip()

    try:
        qty = int(it.get("qty", 0) or 0)
    except Exception:
        qty = 0

    return sku, name, qty

def picklist_order_text(d: dict, o: dict) -> str:
    oid = int(o.get("id", 0) or 0)
    deliv = _order_delivery(o)

    name = (deliv.get("name") or o.get("user_full_name") or "—").strip()
    phone = (deliv.get("phone") or "").strip()
    city = (deliv.get("city") or "").strip()
    branch = (deliv.get("np_branch") or "").strip()
    comment = (deliv.get("comment") or "").strip()

    lines = []
    lines.append(f"📄 <b>НАКЛАДНА · #{oid}</b>")
    lines.append(f"👤 {escape(name)}")
    if phone:
        lines.append(f"📞 <code>{escape(phone)}</code>")
    if city or branch:
        lines.append(f"📍 {escape(city)} · {escape(branch)}")

    lines.append("")
    lines.append("🧾 <b>Позиції:</b>")

    for it in (o.get("items") or []):
        if not isinstance(it, dict):
            continue
        sku, pname, qty = _item_sku_name_qty(d, it)
        if qty <= 0:
            continue

        sku_txt = escape(sku) if sku else "—"
        pname_txt = escape(pname) if pname else "Товар"
        lines.append(f"• <code>{sku_txt}</code> — <b>{qty}</b> шт — {pname_txt}")

    if comment:
        lines.append("")
        lines.append(f"💬 {escape(comment)}")

    return "\n".join(lines).strip()

# =========================================================
# EDIT PRODUCT (FSM)
# =========================================================

@router.callback_query(F.data.startswith("adm:edit:"))
async def edit_product_router(cb: types.CallbackQuery, state: FSMContext):
    d = await load_data()
    if not is_staff(d, cb.from_user.id) or not can_edit_catalog(d, cb.from_user.id):
        return await cb.answer("⛔️ Немає доступу", show_alert=True)

    _, _, field, pid_str = cb.data.split(":")
    pid = int(pid_str)

    p = _find_product_by_id(d, pid)
    if not p:
        return await cb.answer("Товар не знайдено", show_alert=True)

    _ensure_product_schema(p)

    if field == "name":
        await state.set_state(EditProductFSM.name)
        await state.update_data(pid=pid, _edit_field="name")
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
        before = pick_fields(p, ["promo_price","promo_until_ts","price","base_price"])
        p["promo_price"] = 0
        p["promo_until_ts"] = None
        p["price"] = int(p.get("base_price", 0) or 0)
        after = pick_fields(p, ["promo_price","promo_until_ts","price","base_price"])

        audit_add(
            d,
            actor_id=cb.from_user.id,
            actor_role=_role_of(d, cb.from_user.id),
            action="product.promo.clear",
            entity_type="product",
            entity_id=pid,
            entity_name=p.get("name", ""),
            before=before,
            after=after,
        )

        await save_data(d)
        await cb.message.answer("✅ Акцію прибрано.")
        await cb.message.answer(product_card(p), parse_mode="HTML", reply_markup=edit_menu_kb(pid))
        return await cb.answer()

    if field == "sku":
        await state.set_state(EditProductFSM.name)
        await state.update_data(pid=pid, _edit_field="sku")
        await cb.message.answer("Введіть <b>SKU</b> (або <code>-</code> щоб очистити):", parse_mode="HTML")
        return await cb.answer()

    if field == "barcode":
        await state.set_state(EditProductFSM.name)
        await state.update_data(pid=pid, _edit_field="barcode")
        await cb.message.answer("Введіть <b>BARCODE</b> або <code>-</code> щоб згенерувати автоматично:", parse_mode="HTML")
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
    before = pick_fields(p, ["name","sku","barcode"])
    txt = (m.text or "").strip()
    meta_field = st.get("_edit_field") or "name"

    if meta_field == "sku":
        p["sku"] = "" if txt == "-" else _normalize_sku(txt)
        after = pick_fields(p, ["name","sku","barcode"])
        audit_add(d, actor_id=m.from_user.id, actor_role=_role_of(d, m.from_user.id),
                  action="product.edit.sku", entity_type="product", entity_id=pid, entity_name=p.get("name",""),
                  before=before, after=after)
        await save_data(d)
        await state.clear()
        await m.answer("✅ SKU оновлено.")
        return await m.answer(product_card(p), parse_mode="HTML", reply_markup=edit_menu_kb(pid))

    if meta_field == "barcode":
        if txt == "-":
            p["barcode"] = _ensure_unique_barcode(d, "")
        else:
            p["barcode"] = _ensure_unique_barcode(d, txt)
        after = pick_fields(p, ["name","sku","barcode"])
        audit_add(d, actor_id=m.from_user.id, actor_role=_role_of(d, m.from_user.id),
                  action="product.edit.barcode", entity_type="product", entity_id=pid, entity_name=p.get("name",""),
                  before=before, after=after)
        await save_data(d)
        await state.clear()
        await m.answer("✅ BARCODE оновлено.")
        return await m.answer(product_card(p), parse_mode="HTML", reply_markup=edit_menu_kb(pid))

    # name
    if not txt:
        return await m.answer("Введіть назву текстом.")
    p["name"] = txt
    after = pick_fields(p, ["name","sku","barcode"])
    audit_add(d, actor_id=m.from_user.id, actor_role=_role_of(d, m.from_user.id),
              action="product.edit.name", entity_type="product", entity_id=pid, entity_name=p.get("name",""),
              before=before, after=after)
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
    before = pick_fields(p, ["price","base_price","promo_price","promo_until_ts"])

    p["base_price"] = price
    if int(p.get("promo_price", 0) or 0) <= 0:
        p["price"] = price

    after = pick_fields(p, ["price","base_price","promo_price","promo_until_ts"])
    audit_add(d, actor_id=m.from_user.id, actor_role=_role_of(d, m.from_user.id),
              action="product.edit.price", entity_type="product", entity_id=pid, entity_name=p.get("name",""),
              before=before, after=after)

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

    old = p.get("desc", "")
    txt = (m.text or "").strip()
    p["desc"] = "" if txt == "-" else txt

    audit_add(
        d,
        actor_id=m.from_user.id,
        actor_role=_role_of(d, m.from_user.id),
        action="product.edit.desc",
        entity_type="product",
        entity_id=pid,
        entity_name=p.get("name",""),
        before={"desc": old},
        after={"desc": p["desc"]},
    )

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
    before = pick_fields(p, ["promo_price","promo_until_ts","price","base_price"])

    if promo <= 0:
        p["promo_price"] = 0
        p["promo_until_ts"] = None
        p["price"] = int(p.get("base_price", 0) or 0)
        after = pick_fields(p, ["promo_price","promo_until_ts","price","base_price"])

        audit_add(d, actor_id=m.from_user.id, actor_role=_role_of(d, m.from_user.id),
                  action="product.promo.clear", entity_type="product", entity_id=pid, entity_name=p.get("name",""),
                  before=before, after=after)

        await save_data(d)
        await state.clear()
        await m.answer("✅ Акцію прибрано.")
        return await m.answer(product_card(p), parse_mode="HTML", reply_markup=edit_menu_kb(pid))

    p["promo_price"] = promo
    p["price"] = promo
    await state.set_state(EditProductFSM.promo_until)
    await state.update_data(pid=pid)
    await m.answer("Введіть дату до якої діє акція <code>YYYY-MM-DD</code> або <code>-</code> (без дати):", parse_mode="HTML")


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

    _ensure_product_schema(p)
    txt = (m.text or "").strip()

    before = pick_fields(p, ["promo_price","promo_until_ts","price","base_price"])

    if txt == "-":
        p["promo_until_ts"] = None
        after = pick_fields(p, ["promo_price","promo_until_ts","price","base_price"])
        audit_add(d, actor_id=m.from_user.id, actor_role=_role_of(d, m.from_user.id),
                  action="product.promo.set", entity_type="product", entity_id=pid, entity_name=p.get("name",""),
                  before=before, after=after, note="no_end_date")

        await save_data(d)
        await state.clear()
        await m.answer("✅ Акцію встановлено (без дати завершення).")
        return await m.answer(product_card(p), parse_mode="HTML", reply_markup=edit_menu_kb(pid))

    try:
        dt = datetime.strptime(txt, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        p["promo_until_ts"] = int(dt.timestamp())
    except Exception:
        return await m.answer("Невірний формат. Приклад: 2026-02-01 або '-'")

    after = pick_fields(p, ["promo_price","promo_until_ts","price","base_price"])
    audit_add(d, actor_id=m.from_user.id, actor_role=_role_of(d, m.from_user.id),
              action="product.promo.set", entity_type="product", entity_id=pid, entity_name=p.get("name",""),
              before=before, after=after)

    await save_data(d)
    await state.clear()
    await m.answer("✅ Дату завершення акції збережено.")
    await m.answer(product_card(p), parse_mode="HTML", reply_markup=edit_menu_kb(pid))


# =========================================================
# STAFF / ROLES (AdminFSM.add_manager) + roles list
# =========================================================

@router.message(AdminFSM.add_manager)
async def add_manager(m: types.Message, state: FSMContext):
    d = await load_data()
    if not is_staff(d, m.from_user.id) or not can_manage_staff(d, m.from_user.id):
        await state.clear()
        return await m.answer("⛔️ Тільки адмін")

    txt = (m.text or "").strip()

    # формат "-123" => зняти доступ/роль
    if txt.startswith("-"):
        try:
            uid = int(txt[1:])
        except Exception:
            return await m.answer("Формат: <code>-123456789</code>", parse_mode="HTML")

        roles = d.get("roles", {}) or {}
        before = {"role": roles.get(str(uid)), "in_managers": uid in [int(x) for x in (d.get("managers", []) or [])]}

        roles.pop(str(uid), None)
        d["roles"] = roles
        d["managers"] = [x for x in (d.get("managers", []) or []) if int(x) != uid]

        audit_add(d, actor_id=m.from_user.id, actor_role=_role_of(d, m.from_user.id),
                  action="staff.remove", entity_type="staff", entity_id=uid, entity_name=str(uid),
                  before=before, after=None)

        await save_data(d)
        await state.clear()
        return await m.answer(f"✅ Доступ для <code>{uid}</code> видалено", parse_mode="HTML")

    # додати/призначити роль
    try:
        uid = int(txt)
    except Exception:
        return await m.answer("ID має бути числом.")

    d.setdefault("managers", [])
    if uid not in [int(x) for x in (d.get("managers", []) or [])]:
        d["managers"].append(uid)

    kb = InlineKeyboardBuilder()
    kb.button(text="👨‍💼 Менеджер", callback_data=f"adm:role:set:{uid}:manager")
    kb.button(text="📦 Пакувальник", callback_data=f"adm:role:set:{uid}:packer")
    kb.button(text="🛡 Адмін", callback_data=f"adm:role:set:{uid}:admin")
    kb.button(text="⬅️ Скасувати", callback_data="adm:cancel")
    kb.adjust(1)

    await save_data(d)
    await state.clear()
    await m.answer(f"✅ Додано ID <code>{uid}</code>.\nОберіть роль:", parse_mode="HTML", reply_markup=kb.as_markup())


@router.callback_query(F.data.startswith("adm:role:set:"))
async def set_role(cb: types.CallbackQuery):
    d = await load_data()
    if not is_staff(d, cb.from_user.id) or not can_manage_staff(d, cb.from_user.id):
        return await cb.answer("⛔️ Тільки адмін", show_alert=True)

    parts = cb.data.split(":")
    uid = int(parts[3])
    role = (parts[4] or "").strip().lower()
    if role not in (ROLE_ADMIN, ROLE_MANAGER, ROLE_PACKER):
        role = ROLE_MANAGER

    before = {"role": (d.get("roles", {}) or {}).get(str(uid))}
    d.setdefault("roles", {})
    d["roles"][str(uid)] = role
    after = {"role": role}

    audit_add(d, actor_id=cb.from_user.id, actor_role=_role_of(d, cb.from_user.id),
              action="staff.role.set", entity_type="staff", entity_id=uid, entity_name=str(uid),
              before=before, after=after)

    await save_data(d)
    await cb.message.answer(f"✅ Роль для <code>{uid}</code> встановлено: <b>{escape(role)}</b>", parse_mode="HTML")
    await cb.answer()


@router.callback_query(F.data == "adm:roles:list")
async def roles_list(cb: types.CallbackQuery):
    d = await load_data()
    if not is_staff(d, cb.from_user.id) or not can_manage_staff(d, cb.from_user.id):
        return await cb.answer("⛔️ Тільки адмін", show_alert=True)

    roles = d.get("roles", {}) or {}
    managers = set(int(x) for x in (d.get("managers", []) or []))

    lines = ["👥 <b>Ролі персоналу</b>\n"]
    if not roles and not managers:
        lines.append("— персонал ще не доданий —")
    else:
        used = set()
        for uid_str, role in roles.items():
            try:
                uid = int(uid_str)
            except Exception:
                continue
            used.add(uid)
            lines.append(f"• <code>{uid}</code> — <b>{escape(str(role))}</b>")

        for uid in managers:
            if uid not in used:
                lines.append(f"• <code>{uid}</code> — <b>manager</b>")

    kb = InlineKeyboardBuilder()
    kb.button(text="➖ Зняти роль/доступ", callback_data="adm:panel:add_manager")
    kb.button(text="⬅️ Назад", callback_data="adm:panel:settings")
    kb.adjust(1)

    await cb.message.answer("\n".join(lines), parse_mode="HTML", reply_markup=kb.as_markup())
    await cb.answer()


# =========================================================
# BUYER SEARCH (beautiful карточка + останні замовлення)
# =========================================================

def _norm_username(s: str) -> str:
    s = (s or "").strip()
    if s.startswith("@"):
        s = s[1:]
    return s.lower()


def _norm_text(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip()).lower()


def _pick_phone_from_order(o: dict) -> str:
    for k in ("phone", "user_phone", "tel", "telephone", "contact_phone", "buyer_phone"):
        v = (o.get(k) or "").strip()
        if v:
            return v
    ship = o.get("shipping") or o.get("delivery") or {}
    if isinstance(ship, dict):
        for k in ("phone", "tel"):
            v = (ship.get(k) or "").strip()
            if v:
                return v
    return ""


def _last_orders_of_user(d: dict, uid: int) -> list[dict]:
    orders = d.get("orders", []) or []
    arr = []
    for o in orders:
        try:
            if int(o.get("user_id", -1)) == int(uid):
                arr.append(o)
        except Exception:
            pass
    arr.sort(key=lambda x: int(x.get("created_ts", 0) or 0), reverse=True)
    return arr


def buyer_card_text(uid: int, u: dict, last_order: dict | None, total_orders: int) -> str:
    name = (u.get("full_name") or "—").strip()
    username = (u.get("username") or "").strip()
    phone = _pick_phone_from_order(last_order or {}) if last_order else ""
    phone_txt = f"<code>{escape(phone)}</code>" if phone else "—"
    uname_txt = f"@{escape(username)}" if username else "—"

    return (
        f"👤 <b>Покупець</b>: <a href=\"tg://user?id={uid}\">{escape(name)}</a>\n"
        f"ID: <code>{uid}</code>\n"
        f"Username: <code>{uname_txt}</code>\n"
        f"Телефон (з останнього замовлення): {phone_txt}\n"
        f"Замовлень всього: <b>{total_orders}</b>"
    )


def buyer_open_kb(uid: int) -> types.InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="📦 Показати 5 замовлень", callback_data=f"adm:buyer:orders:{uid}:5")
    kb.button(text="📦 Показати 15 замовлень", callback_data=f"adm:buyer:orders:{uid}:15")
    kb.button(text="⬅️ Назад", callback_data="adm:cancel")
    kb.adjust(1)
    return kb.as_markup()


@router.message(AdminFSM.search_buyer)
async def search_buyer_input(m: types.Message, state: FSMContext):
    d = await load_data()

    q_raw = (m.text or "").strip()
    q = _norm_text(q_raw)
    q_user = _norm_username(q_raw)

    uid_as_int = None
    if q_raw.isdigit():
        try:
            uid_as_int = int(q_raw)
        except Exception:
            uid_as_int = None

    users = d.get("users", {}) or {}
    orders = d.get("orders", []) or []

    found: dict[int, dict] = {}

    # 1) users
    for uid_str, u in users.items():
        if not isinstance(u, dict):
            continue
        try:
            uid_i = int(u.get("id") or uid_str)
        except Exception:
            continue

        username = (u.get("username") or "")
        full_name = (u.get("full_name") or "")
        username_n = _norm_username(username)
        full_name_n = _norm_text(full_name)

        ok = False
        if uid_as_int is not None and uid_i == uid_as_int:
            ok = True
        elif q_user and username_n and q_user == username_n:
            ok = True
        elif q and (q in full_name_n or q in username_n):
            ok = True

        if ok:
            found[uid_i] = {
                "id": uid_i,
                "username": username,
                "full_name": full_name,
                "first_seen_ts": int(u.get("first_seen_ts", 0) or 0),
                "last_seen_ts": int(u.get("last_seen_ts", 0) or 0),
            }

    # 2) fallback orders
    for o in orders:
        if not isinstance(o, dict):
            continue
        try:
            uid_i = int(o.get("user_id", -1))
        except Exception:
            continue
        if uid_i <= 0:
            continue

        username = o.get("user_username") or o.get("username") or o.get("from_username") or ""
        full_name = o.get("user_full_name") or o.get("full_name") or o.get("name") or ""

        username_n = _norm_username(username)
        full_name_n = _norm_text(full_name)

        ok = False
        if uid_as_int is not None and uid_i == uid_as_int:
            ok = True
        elif q_user and username_n and q_user == username_n:
            ok = True
        elif q and (q in full_name_n or q in username_n):
            ok = True

        if ok and uid_i not in found:
            found[uid_i] = {
                "id": uid_i,
                "username": username,
                "full_name": full_name,
                "first_seen_ts": 0,
                "last_seen_ts": int(o.get("created_ts", 0) or 0),
            }

    def orders_count(uid: int) -> int:
        c = 0
        for o in orders:
            try:
                if int(o.get("user_id", -1)) == int(uid):
                    c += 1
            except Exception:
                pass
        return c

    found_users = list(found.values())

    if not found_users:
        await m.answer(
            "❌ Нічого не знайшов.\n\n"
            f"У базі зараз:\n"
            f"• users: <b>{len(users)}</b>\n"
            f"• orders: <b>{len(orders)}</b>\n\n"
            "Спробуй ввести:\n"
            "• ID (число)\n"
            "• @username\n"
            "• частину імені\n\n"
            "Якщо users = 0 — зайди в бота як юзер і натисни /start.",
            parse_mode="HTML",
        )
        await state.clear()
        return

    found_users.sort(key=lambda x: int(x.get("last_seen_ts", 0) or 0), reverse=True)

    # якщо 1 збіг — повна карточка + останнє замовлення
    if len(found_users) == 1:
        u = found_users[0]
        uid = int(u["id"])

        arr = _last_orders_of_user(d, uid)
        last_order = arr[0] if arr else None
        total = len(arr)

        await m.answer(
            buyer_card_text(uid, u, last_order, total),
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=buyer_open_kb(uid),
        )

        if last_order:
            products = _order_products(d, last_order)
            kb = order_actions_kb(
                int(last_order.get("id", 0)),
                str(last_order.get("status", "")),
                d=d,
                uid=m.from_user.id
            )
            await m.answer(order_premium_text(d, last_order, products), parse_mode="HTML", reply_markup=kb)
        else:
            await m.answer("📭 У цього покупця ще немає замовлень.")

        await state.clear()
        return

    # 2+ збігів — список
    lines = ["✅ <b>Знайдені користувачі:</b>", ""]
    for u in found_users[:10]:
        uid = int(u["id"])
        uname = u.get("username") or ""
        name = u.get("full_name") or "—"
        cnt = orders_count(uid)

        user_link = f'<a href="tg://user?id={uid}">{escape(name)}</a>'
        uname_txt = f"@{escape(uname)}" if uname else "—"

        lines.append(f"• {user_link}")
        lines.append(f"  ID: <code>{uid}</code> | username: <code>{uname_txt}</code> | замовлень: <b>{cnt}</b>")
        lines.append("")

    await m.answer("\n".join(lines).strip(), parse_mode="HTML", disable_web_page_preview=True)
    await state.clear()


@router.callback_query(F.data.startswith("adm:buyer:orders:"))
async def buyer_orders_cb(cb: types.CallbackQuery):
    d = await load_data()
    if not is_staff(d, cb.from_user.id) or not can_manage_orders(d, cb.from_user.id):
        return await cb.answer("⛔️ Немає доступу", show_alert=True)

    parts = cb.data.split(":")
    uid = int(parts[3])
    limit = int(parts[4])

    arr = _last_orders_of_user(d, uid)
    if not arr:
        await cb.message.answer("📭 Замовлень немає.")
        return await cb.answer()

    await cb.message.answer(
        f"📦 <b>Останні замовлення покупця</b> (показую {min(limit, len(arr))}):",
        parse_mode="HTML"
    )

    for o in arr[:limit]:
        products = _order_products(d, o)
        kb = order_actions_kb(int(o.get("id", 0)), str(o.get("status", "")), d=d, uid=cb.from_user.id)
        await cb.message.answer(order_premium_text(d, o, products), parse_mode="HTML", reply_markup=kb)

    await cb.answer()

@router.message(Command("reset_shop"))
async def admin_reset_shop(m: types.Message):
    d = await load_data()
    if not is_admin(m.from_user.id):
        return await m.answer("⛔️ Тільки адмін")

    # зберігаємо мінімум що треба НЕ губити (опційно):
    keep_roles = d.get("roles", {})
    keep_managers = d.get("managers", [])

    nd = default_data()
    nd["roles"] = keep_roles
    nd["managers"] = keep_managers

    await save_data(nd)

    await m.answer(
        "✅ Базу магазину очищено.\n\n"
        "Залишив:\n"
        f"• roles: {len(keep_roles)}\n"
        f"• managers: {len(keep_managers)}\n\n"
        "Каталог/кошики/замовлення/обране — скинуто.",
        parse_mode="HTML"
    )