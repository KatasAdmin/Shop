# handlers/admin.py
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Dict, Any, List

from orders_timeline import (
    _evt,
    order_set_status,
    order_set_ttn,
    render_timeline_text,
)
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
# EVENTS / TIMELINE (як у user.py, але локально, без циклів)
# =========================================================

def _evt(order: dict, code: str, title: str, details: str = "") -> None:
    """
    Події замовлення:
    order["events"] = [{ts, code, title, details}]
    """
    order.setdefault("events", [])
    order["events"].append({
        "ts": int(time.time()),
        "code": str(code),
        "title": str(title),
        "details": str(details or ""),
    })


def _ensure_events(order: dict) -> None:
    """
    Для старих замовлень без events — створимо базову подію “створено”.
    """
    order.setdefault("events", [])
    if order["events"]:
        return
    created_ts = int(order.get("created_ts", 0) or 0)
    if created_ts:
        _evt(order, "created", "Замовлення створено", "")


def order_set_status(order: dict, new_status: str, who: str = "", details: str = "") -> None:
    """
    ЄДИНИЙ правильний спосіб міняти статус в адмінці:
    - виставляє order["status"]
    - пише подію в events
    """
    old = (order.get("status") or "").strip().lower()
    ns = (new_status or "").strip().lower()
    if not ns or old == ns:
        return

    order["status"] = ns
    _ensure_events(order)

    who_line = f"Хто: {who}\n" if who else ""
    body = f"{old or '—'} → {ns}"
    if details:
        body = body + "\n" + details.strip()

    _evt(order, "status", "Статус змінено", (who_line + body).strip())


def order_set_ttn(order: dict, ttn: str, who: str = "", details: str = "") -> None:
    """
    Фіксуємо ТТН:
    - пишемо в order["ttn"] і order["np_ttn"] (сумісність)
    - пишемо подію в events
    """
    ttn = (ttn or "").strip()

    prev = (order.get("np_ttn") or order.get("ttn") or "").strip()
    order["ttn"] = ttn
    order["np_ttn"] = ttn  # ✅ важливо для правила “Відправлено тільки якщо є ТТН”

    _ensure_events(order)

    who_line = f"Хто: {who}\n" if who else ""
    if not ttn and prev:
        _evt(order, "ttn", "ТТН очищено", (who_line + prev).strip())
        return

    if ttn and prev and prev != ttn:
        extra = (details or "").strip()
        msg = f"{prev} → {ttn}" + (f"\n{extra}" if extra else "")
        _evt(order, "ttn", "ТТН змінено", (who_line + msg).strip())
        return

    if ttn and not prev:
        extra = (details or "").strip()
        msg = f"{ttn}" + (f"\n{extra}" if extra else "")
        _evt(order, "ttn", "ТТН додано", (who_line + msg).strip())
        return


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
# handlers/admin.py  (PART 2/8)
# ПРОДОВЖЕННЯ ФАЙЛУ — встав після Part 1

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

    # ✅ Акції
    kb.button(text="🏷 Акційна ціна", callback_data=f"adm:edit:promo:{pid}")
    kb.button(text="🧹 Прибрати акцію", callback_data=f"adm:edit:promo_clear:{pid}")

    # ✅ SKU / BARCODE (на майбутнє інтеграції)
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


def order_actions_kb(oid: int, status: str) -> types.InlineKeyboardMarkup:
    """
    Статуси (технічні):
    pending / paid / prepay / in_work / packed / shipped / arrived / received / not_picked / returned / done / canceled
    """
    s = (status or "").strip().lower()
    kb = InlineKeyboardBuilder()

    # 1) Взяти в роботу
    if s in ("paid", "prepay"):
        kb.button(text="🟡 В роботу", callback_data=f"adm:order:in_work:{oid}")

    # 2) Пакування (для пакувальника теж буде)
    if s in ("in_work", "paid", "prepay"):
        kb.button(text="📦 Запаковано", callback_data=f"adm:order:packed:{oid}")

    # 3) Відправлено (просимо ТТН)
    if s in ("paid", "prepay", "in_work", "packed", "shipped"):
        kb.button(text="🚚 Відправлено", callback_data=f"adm:order:shipped:{oid}")

    # 4) Логістика / фінал
    if s == "shipped":
        kb.button(text="📍 Прибуло у відділення", callback_data=f"adm:order:arrived:{oid}")
        kb.button(text="✅ Отримано (забрав)", callback_data=f"adm:order:received:{oid}")
        kb.button(text="❌ Не забрав", callback_data=f"adm:order:not_picked:{oid}")
        kb.button(text="🔁 Повернуто", callback_data=f"adm:order:returned:{oid}")

    if s in ("arrived",):
        kb.button(text="✅ Отримано (забрав)", callback_data=f"adm:order:received:{oid}")
        kb.button(text="❌ Не забрав", callback_data=f"adm:order:not_picked:{oid}")
        kb.button(text="🔁 Повернуто", callback_data=f"adm:order:returned:{oid}")

    if s in ("not_picked",):
        kb.button(text="🔁 Повернуто", callback_data=f"adm:order:returned:{oid}")

    # 5) Завершити (закрити)
    if s in ("received", "returned", "not_picked"):
        kb.button(text="✅ Закрити (done)", callback_data=f"adm:order:done:{oid}")

    # 6) ТТН окремо (якщо треба змінити/додати)
    kb.button(text="🧾 Встановити ТТН", callback_data=f"adm:order:set_ttn:{oid}")

    # 7) Історія покупця + хронологія
    kb.button(text="👤 Історія покупця", callback_data=f"adm:order:history:{oid}")
    kb.button(text="📜 Хронологія", callback_data=f"adm:order:timeline:{oid}")

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
# PANEL NAV
# =========================================================

@router.callback_query(F.data.startswith("adm:panel:"))
async def panel_nav(cb: types.CallbackQuery, state: FSMContext):
    d = await load_data()
    if not is_staff(d, cb.from_user.id):
        return await cb.answer("Немає доступу", show_alert=True)

    await state.clear()
    action = cb.data.split(":")[2]

    # головна
    if action in ("back", "main"):
        await cb.message.answer("🔧 Панель (Адмін/Персонал)", reply_markup=panel_main_kb(cb.from_user.id))
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

    # дії (перекидання в існуючі сценарії)
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

    if action == "orders_paid":
        paid = [o for o in (d.get("orders", []) or []) if (o.get("status") or "") in ("paid", "prepay")]
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
            "Приклад: <code>123456789</code> або <code>@katas</code> або <code>Віктор</code>",
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
# handlers/admin.py  (PART 3/8)
# ПРОДОВЖЕННЯ ФАЙЛУ — встав після Part 2/8

# =========================================================
# ORDERS: CHANGE STATUS + TIMELINE + TTN
# =========================================================

def _fmt_dt(ts: int) -> str:
    try:
        dt = datetime.fromtimestamp(int(ts), tz=timezone.utc).astimezone()
        return dt.strftime("%d.%m.%Y %H:%M")
    except Exception:
        return "-"


def _evt(order: dict, code: str, title: str, details: str = "") -> None:
    order.setdefault("events", [])
    order["events"].append({
        "ts": int(datetime.now(tz=timezone.utc).timestamp()),
        "code": str(code),
        "title": str(title),
        "details": str(details or ""),
    })


def _ensure_events(order: dict) -> None:
    order.setdefault("events", [])
    if order["events"]:
        return
    created_ts = int(order.get("created_ts", 0) or 0)
    if created_ts:
        order["events"].append({
            "ts": created_ts,
            "code": "created",
            "title": "Замовлення створено",
            "details": "",
        })


def order_set_status(order: dict, new_status: str, details: str = "") -> None:
    """
    ЄДИНИЙ правильний спосіб міняти статус в адмінці.
    - міняє order["status"]
    - пише подію в order["events"]
    """
    old = (order.get("status") or "").strip().lower()
    ns = (new_status or "").strip().lower()
    if not ns or ns == old:
        return

    order["status"] = ns
    _ensure_events(order)
    _evt(order, "status", "Статус змінено", f"{old or '—'} → {ns}\n{details}".strip())


def order_set_ttn(order: dict, ttn: str, details: str = "") -> None:
    """
    ЄДИНИЙ правильний спосіб ставити/міняти ТТН.
    Тримаємо і np_ttn і ttn (сумісність).
    """
    ttn = (ttn or "").strip()
    prev = (order.get("np_ttn") or order.get("ttn") or "").strip()

    order["np_ttn"] = ttn
    order["ttn"] = ttn

    _ensure_events(order)
    if prev and prev != ttn:
        _evt(order, "ttn", "ТТН змінено", f"{prev} → {ttn}\n{details}".strip())
    elif (not prev) and ttn:
        _evt(order, "ttn", "ТТН додано", ttn)
    elif prev and not ttn:
        _evt(order, "ttn", "ТТН очищено", prev)


def _render_timeline_admin(order: dict) -> str:
    _ensure_events(order)
    evs = order.get("events", []) or []
    if not evs:
        return "📜 <b>Хронологія</b>\n\nПодій поки немає."

    evs_sorted = sorted(evs, key=lambda x: int(x.get("ts", 0) or 0))
    lines = ["📜 <b>Хронологія</b>", ""]
    for e in evs_sorted:
        ts = _fmt_dt(int(e.get("ts", 0) or 0))
        title = str(e.get("title", "") or "")
        details = str(e.get("details", "") or "")
        if details:
            lines.append(f"• <b>{title}</b> — <i>{ts}</i>\n  {details}")
        else:
            lines.append(f"• <b>{title}</b> — <i>{ts}</i>")

    ttn = (order.get("np_ttn") or order.get("ttn") or "").strip()
    if ttn:
        lines.append("")
        lines.append(f"📦 ТТН: <code>{ttn}</code>")

    return "\n".join(lines)


def _find_order(d: dict, oid: int) -> dict | None:
    for o in (d.get("orders", []) or []):
        try:
            if int(o.get("id", -1)) == int(oid):
                return o
        except Exception:
            continue
    return None


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

    async def _reply_updated(prefix_text: str):
        products = _order_products(d, order)
        await cb.message.answer(
            prefix_text + "\n\n" + order_premium_text(d, order, products),
            parse_mode="HTML",
            reply_markup=order_actions_kb(oid, str(order.get("status", "")))
        )

    # ---- В РОБОТУ ----
    if action == "in_work":
        if (order.get("status") or "") not in ("paid", "prepay"):
            return await cb.answer("Тільки paid/prepay можна взяти в роботу", show_alert=True)

        order_set_status(order, "in_work")
        _evt(order, "in_work", "Прийнято в роботу", f"Менеджер: {cb.from_user.id}")
        await save_data(d)

        await _reply_updated(f"🟡 Замовлення #{oid} взято в роботу.")
        await _notify_buyer(bot, d, order, f"🟡 Ваше замовлення #{oid} взято в роботу ✅")
        return await cb.answer()

    # ---- ЗАПАКОВАНО ----
    if action == "packed":
        if (order.get("status") or "") not in ("paid", "prepay", "in_work"):
            return await cb.answer("Запакувати можна після paid/prepay/in_work", show_alert=True)

        order_set_status(order, "packed")
        _evt(order, "packed", "Запаковано", f"Пакувальник: {cb.from_user.id}")
        await save_data(d)

        await _reply_updated(f"📦 Замовлення #{oid} запаковано.")
        await _notify_buyer(bot, d, order, f"📦 Ваше замовлення #{oid} запаковано ✅")
        return await cb.answer()

    # ---- ВІДПРАВЛЕНО (потім просимо ТТН) ----
    if action == "shipped":
        if (order.get("status") or "") not in ("paid", "prepay", "in_work", "packed", "shipped"):
            return await cb.answer("Неможливо позначити як відправлено", show_alert=True)

        # ставимо статус shipped, але для клієнта він стане “Відправлено” ТІЛЬКИ якщо є ТТН (це правило у user.py)
        order_set_status(order, "shipped")
        _evt(order, "shipped", "Відправлено", f"Менеджер: {cb.from_user.id}")
        await save_data(d)

        await _reply_updated(f"🚚 Замовлення #{oid} позначено як ВІДПРАВЛЕНО.")
        await state.clear()
        await state.set_state(AdminFSM.order_ttn)
        await state.update_data(oid=oid)

        await cb.message.answer("📮 Введіть ТТН для цього замовлення (або '-' щоб без ТТН):")
        return await cb.answer()

    # ---- ПРИБУЛО ----
    if action == "arrived":
        if (order.get("status") or "") not in ("shipped", "arrived"):
            return await cb.answer("Прибуло доречно тільки після 'Відправлено'", show_alert=True)

        order_set_status(order, "arrived")
        _evt(order, "arrived", "Прибуло у відділення", "")
        await save_data(d)

        await _reply_updated(f"📍 Замовлення #{oid}: прибуло у відділення.")
        await _notify_buyer(bot, d, order, f"📍 Замовлення #{oid}: прибуло у відділення ✅")
        return await cb.answer()

    # ---- ОТРИМАНО ----
    if action == "received":
        if (order.get("status") or "") not in ("shipped", "arrived", "received"):
            return await cb.answer("Отримано доречно після shipped/arrived", show_alert=True)

        order_set_status(order, "received")
        _evt(order, "received", "Отримано (забрав)", "")
        await save_data(d)

        await _reply_updated(f"✅ Замовлення #{oid}: клієнт ОТРИМАВ (забрав).")
        await _notify_buyer(bot, d, order, f"✅ Замовлення #{oid}: отримано. Дякуємо! 🙌")
        return await cb.answer()

    # ---- НЕ ЗАБРАВ ----
    if action == "not_picked":
        if (order.get("status") or "") not in ("shipped", "arrived", "not_picked"):
            return await cb.answer("Не забрав доречно після shipped/arrived", show_alert=True)

        order_set_status(order, "not_picked")
        _evt(order, "not_picked", "Не забрав", "")
        await save_data(d)

        await _reply_updated(f"❌ Замовлення #{oid}: НЕ ЗАБРАВ.")
        await _notify_buyer(bot, d, order, f"❌ Замовлення #{oid}: не забрано. Напишіть нам — допоможемо 🤝")
        return await cb.answer()

    # ---- ПОВЕРНУТО ----
    if action == "returned":
        if (order.get("status") or "") not in ("shipped", "arrived", "not_picked", "returned"):
            return await cb.answer("Повернення ставимо після логістики", show_alert=True)

        order_set_status(order, "returned")
        _evt(order, "returned", "Повернуто", "")
        await save_data(d)

        await _reply_updated(f"🔁 Замовлення #{oid}: ПОВЕРНУТО.")
        await _notify_buyer(bot, d, order, f"🔁 Замовлення #{oid}: повернено. Якщо є питання — пишіть 🙏")
        return await cb.answer()

    # ---- DONE (закрити) ----
    if action == "done":
        if (order.get("status") or "") in ("done", "canceled"):
            return await cb.answer("Вже закрито", show_alert=True)

        order_set_status(order, "done")
        _evt(order, "done", "Закрито (done)", "")
        await save_data(d)

        await _reply_updated(f"✅ Замовлення #{oid} закрито.")
        await _notify_buyer(bot, d, order, f"✅ Замовлення #{oid} завершено 🎉")
        return await cb.answer()

    # ---- SET TTN (ручна) ----
    if action == "set_ttn":
        await state.clear()
        await state.set_state(AdminFSM.order_ttn)
        await state.update_data(oid=oid)
        await cb.message.answer("📮 Введіть ТТН (або '-' щоб очистити):")
        return await cb.answer()

    # ---- TIMELINE (адмін) ----
    if action == "timeline":
        txt = _render_timeline_admin(order)
        kb = InlineKeyboardBuilder()
        kb.button(text="⬅️ Назад", callback_data="adm:cancel")
        kb.adjust(1)
        await cb.message.answer(txt, parse_mode="HTML", reply_markup=kb.as_markup())
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


@router.message(AdminFSM.order_ttn)
async def admin_set_ttn(m: types.Message, state: FSMContext, bot: Bot):
    st = await state.get_data()
    oid = int(st.get("oid", 0) or 0)
    txt = (m.text or "").strip()

    d = await load_data()
    order = next((o for o in (d.get("orders", []) or []) if int(o.get("id", -1)) == oid), None)
    if not order:
        await state.clear()
        return await m.answer("❌ Замовлення не знайдено.")

    if txt == "-":
        # очищення ТТН
        order_set_ttn(order, "", details=f"Ким: {m.from_user.id}")
        await save_data(d)
        await state.clear()
        return await m.answer("✅ ТТН очищено.")

    # зберігаємо ТТН правильно (np_ttn + event)
    order_set_ttn(order, txt, details=f"Ким: {m.from_user.id}")

    # ✅ ВАЖЛИВО: якщо статус уже shipped — ок, якщо ні — не чіпаємо
    # але можемо додати подію, що "ТТН додано"
    await save_data(d)
    await state.clear()

    await m.answer("✅ ТТН збережено.")

    # клієнту — якщо замовлення відправлено (або ти хочеш завжди — можеш прибрати if)
    if (order.get("status") or "").strip().lower() in ("shipped", "sent"):
        await _notify_buyer(bot, d, order, f"🚚 Ваше замовлення #{oid} відправлено ✅")
# handlers/admin.py  (PART 4/8)
# ВСТАВ ПІСЛЯ Part 3/8

# =========================================================
# ORDER ACTIONS KB (оновлюємо кнопки під нові статуси)
# =========================================================

def order_actions_kb(oid: int, status: str) -> types.InlineKeyboardMarkup:
    """
    Кнопки під реальні робочі стани.
    Принцип:
    - paid/prepay -> in_work -> (опц.) packed -> shipped(+ТТН) -> arrived -> received
    - якщо не забрав -> not_picked -> returned
    - done закриває замовлення
    """
    st = (status or "").strip().lower()
    kb = InlineKeyboardBuilder()

    # 1) В роботу
    if st in ("paid", "prepay"):
        kb.button(text="🟡 В роботу", callback_data=f"adm:order:in_work:{oid}")

    # 2) Запаковано (для пакувальника / складу)
    if st in ("paid", "prepay", "in_work"):
        kb.button(text="📦 Запаковано", callback_data=f"adm:order:packed:{oid}")

    # 3) Відправлено (після packed або in_work) + ввід ТТН
    if st in ("paid", "prepay", "in_work", "packed"):
        kb.button(text="🚚 Відправлено + ТТН", callback_data=f"adm:order:shipped:{oid}")

    # 4) Прибуло / Отримано / Не забрав
    if st in ("shipped", "arrived"):
        kb.button(text="📍 Прибуло у відділення", callback_data=f"adm:order:arrived:{oid}")
        kb.button(text="✅ Отримано (забрав)", callback_data=f"adm:order:received:{oid}")
        kb.button(text="❌ Не забрав", callback_data=f"adm:order:not_picked:{oid}")

    # 5) Повернення (після не забрав, інколи й після shipped)
    if st in ("not_picked", "shipped"):
        kb.button(text="🔁 Повернуто", callback_data=f"adm:order:returned:{oid}")

    # 6) Завершити (закрити) — дозволено майже на всіх робочих етапах
    if st in ("paid", "prepay", "in_work", "packed", "shipped", "arrived", "received", "not_picked", "returned"):
        kb.button(text="✅ Завершити", callback_data=f"adm:order:done:{oid}")

    # 7) Інфо (завжди)
    kb.button(text="📜 Хронологія", callback_data=f"adm:order:timeline:{oid}")
    kb.button(text="📜 Історія покупця", callback_data=f"adm:order:history:{oid}")

    kb.adjust(1)
    return kb.as_markup()


# =========================================================
# ВАЖЛИВО: якщо у тебе вище в файлі вже є order_actions_kb —
# заміни її повністю на цю версію (щоб не було "picked"/"зібрано").
# =========================================================


# =========================================================
# ADMIN: "ORDERS PAID" / "ORDERS ALL" — підтягуємо правильні кнопки
# (якщо у тебе ці блоки вже є — можна не чіпати, але тут версія з норм статусом)
# =========================================================

@router.message(F.text == "📋 Нові (оплачені)")
async def orders_paid(m: types.Message):
    d = await load_data()
    if not is_staff(d, m.from_user.id):
        return await m.answer("⛔️ Немає доступу")

    paid = [o for o in (d.get("orders", []) or []) if (o.get("status") in ("paid", "prepay"))]
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


# =========================================================
# NOTE по твоїй проблемі "в історії юзера зібрано"
# ---------------------------------------------------------
# Це стається, коли в order["status"] лежить "picked" або "packing"/"packed"
# і мапінг у user.py показує "Зібрано"/"Пакування".
#
# Ми тепер робимо:
# - "received" -> "Отримано"
# - "packed" -> "Запаковано" (це ОК)
# - shipped/sent -> "Відправлено" тільки якщо є ТТН (ваше правило)
# =========================================================
# handlers/admin.py  (PART 5/8)
# ВСТАВ ПІСЛЯ Part 4/8

# =========================================================
# TIMELINE / EVENTS для замовлень (як у user.py)
# щоб: адмін міняє статус -> пишеться хронологія
# і можна показати хронологію в адмінці кнопкою
# =========================================================

import time
import re

def _evt(order: dict, code: str, title: str, details: str = "") -> None:
    order.setdefault("events", [])
    order["events"].append({
        "ts": int(time.time()),
        "code": str(code),
        "title": str(title),
        "details": str(details or ""),
    })


def _fmt_dt(ts: int) -> str:
    try:
        t = time.localtime(int(ts))
        return time.strftime("%d.%m.%Y %H:%M", t)
    except Exception:
        return "-"


def _ensure_events(o: dict) -> None:
    o.setdefault("events", [])
    if o["events"]:
        return
    created_ts = int(o.get("created_ts", 0) or 0)
    if created_ts:
        o["events"].append({
            "ts": created_ts,
            "code": "created",
            "title": "Замовлення створено",
            "details": "",
        })


def order_set_status(o: dict, new_status: str, title: str = "", details: str = "") -> None:
    """
    ЄДИНИЙ правильний спосіб міняти статус в адмінці/інтеграції.
    """
    old = (o.get("status") or "").strip().lower()
    ns = (new_status or "").strip().lower()
    if not ns or old == ns:
        return

    o["status"] = ns
    _ensure_events(o)

    if not title:
        title = "Статус змінено"

    # дружній details + технічний перехід
    det = f"{old or '—'} → {ns}"
    if details:
        det = det + "\n" + details

    _evt(o, "status", title, det)


def order_set_ttn(o: dict, ttn: str, details: str = "") -> None:
    """
    Зберігаємо ТТН у np_ttn і ttn (сумісність),
    і додаємо подію.
    """
    ttn = (ttn or "").strip()
    if ttn == "-":
        ttn = ""

    prev = (o.get("np_ttn") or o.get("ttn") or "").strip()

    o["np_ttn"] = ttn
    o["ttn"] = ttn

    _ensure_events(o)

    if not prev and ttn:
        _evt(o, "ttn", "ТТН додано", ttn)
    elif prev and not ttn:
        _evt(o, "ttn", "ТТН видалено", prev)
    elif prev != ttn:
        _evt(o, "ttn", "ТТН змінено", f"{prev} → {ttn}\n{details}".strip())


def _render_timeline_admin(o: dict) -> str:
    _ensure_events(o)
    evs = o.get("events", []) or []
    if not evs:
        return "📜 <b>Хронологія</b>\n\nПодій ще немає."

    lines = ["📜 <b>Хронологія</b>", ""]
    evs_sorted = sorted(evs, key=lambda x: int(x.get("ts", 0) or 0))
    for e in evs_sorted:
        dt = _fmt_dt(int(e.get("ts", 0) or 0))
        title = str(e.get("title", "") or "")
        details = str(e.get("details", "") or "")
        if details:
            lines.append(f"• <b>{title}</b> — <i>{dt}</i>")
            lines.append(f"  {details}")
        else:
            lines.append(f"• <b>{title}</b> — <i>{dt}</i>")
        lines.append("")

    ttn = (o.get("np_ttn") or o.get("ttn") or "").strip()
    if ttn:
        lines.append(f"📦 ТТН: <code>{ttn}</code>")

    return "\n".join(lines).strip()


# =========================================================
# ADMIN FSM: окремий режим "ввести ТТН" (ми вже маємо AdminFSM.order_ttn)
# але тепер використовуємо його і для shipped, і для ручного set_ttn
# =========================================================

def _ttn_digits_only(s: str) -> str:
    return re.sub(r"\s+", "", (s or "").strip())


# =========================================================
# КНОПКА: 📜 Хронологія / 📮 Встановити ТТН
# =========================================================

@router.callback_query(F.data.startswith("adm:order:timeline:"))
async def adm_order_timeline(cb: types.CallbackQuery):
    d = await load_data()
    if not is_staff(d, cb.from_user.id):
        return await cb.answer("Немає доступу", show_alert=True)

    oid = int(cb.data.split(":")[3])
    order = next((o for o in (d.get("orders", []) or []) if int(o.get("id", -1)) == oid), None)
    if not order:
        return await cb.answer("Замовлення не знайдено", show_alert=True)

    txt = _render_timeline_admin(order)

    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ Назад", callback_data="adm:cancel")
    kb.adjust(1)

    await cb.message.answer(txt, parse_mode="HTML", reply_markup=kb.as_markup())
    await cb.answer()


@router.callback_query(F.data.startswith("adm:order:set_ttn:"))
async def adm_order_set_ttn(cb: types.CallbackQuery, state: FSMContext):
    d = await load_data()
    if not is_staff(d, cb.from_user.id):
        return await cb.answer("Немає доступу", show_alert=True)

    oid = int(cb.data.split(":")[3])
    order = next((o for o in (d.get("orders", []) or []) if int(o.get("id", -1)) == oid), None)
    if not order:
        return await cb.answer("Замовлення не знайдено", show_alert=True)

    await state.clear()
    await state.set_state(AdminFSM.order_ttn)
    await state.update_data(oid=oid)

    cur = (order.get("np_ttn") or order.get("ttn") or "").strip() or "—"
    await cb.message.answer(
        f"📮 Поточний ТТН: <code>{cur}</code>\n\n"
        "Введіть новий ТТН або <code>-</code> щоб видалити:",
        parse_mode="HTML"
    )
    await cb.answer()


# =========================================================
# ОБРОБНИК ВВОДУ ТТН (переписуємо твій, щоб:
# - записував np_ttn і подію
# - якщо статус shipped і ттн є -> юзеру в історії буде "Відправлено"
# =========================================================

@router.message(AdminFSM.order_ttn)
async def admin_set_ttn(m: types.Message, state: FSMContext, bot: Bot):
    st = await state.get_data()
    oid = int(st.get("oid", 0) or 0)

    raw = (m.text or "").strip()
    ttn = "" if raw == "-" else _ttn_digits_only(raw)

    d = await load_data()
    order = next((o for o in (d.get("orders", []) or []) if int(o.get("id", -1)) == oid), None)
    if not order:
        await state.clear()
        return await m.answer("❌ Замовлення не знайдено.")

    # зберегти ттн + подія
    order_set_ttn(order, ttn)

    await save_data(d)
    await state.clear()

    await m.answer("✅ ТТН збережено.")

    # якщо замовлення вже shipped — повідомимо покупця (опціонально, але круто)
    if (order.get("status") or "").strip().lower() in ("shipped", "sent"):
        await _notify_buyer(bot, d, order, f"🚚 Ваше замовлення #{oid} відправлено ✅")


# =========================================================
# ВАЖЛИВО:
# Якщо в тебе вище вже є @router.message(AdminFSM.order_ttn) — ЗАМІНИ на цей.
# =========================================================
# ===================== PART 6/8 (REPEAT) =====================
# РОЛІ + ПРАВА + ВИПРАВЛЕННЯ СТАТУСІВ (picked != received)

from typing import Optional

ROLE_ADMIN = "admin"
ROLE_MANAGER = "manager"
ROLE_PACKER = "packer"

def _role_of(d: dict, uid: int) -> str:
    # адмін завжди адмін
    if is_admin(uid):
        return ROLE_ADMIN
    roles = d.get("roles", {}) or {}
    r = (roles.get(str(uid)) or "").strip().lower()
    # якщо ролі нема — вважаємо "manager"
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
    # пакувальник має право "зібрано/запаковано"
    return _role_of(d, uid) in (ROLE_ADMIN, ROLE_MANAGER, ROLE_PACKER)


def can_mark_logistics(d: dict, uid: int) -> bool:
    # відправка/отримано/повернення — тільки менеджер/адмін
    return _role_of(d, uid) in (ROLE_ADMIN, ROLE_MANAGER)


# -------------------------------------------------------------
# ✅ НОВИЙ order_actions_kb (з ролями + правильні кнопки)
# -------------------------------------------------------------
def order_actions_kb(
    oid: int,
    status: str,
    *,
    d: Optional[dict] = None,
    uid: Optional[int] = None,
) -> types.InlineKeyboardMarkup:
    """
    Якщо передати d та uid — увімкнемо рольові обмеження.
    Якщо не передати — буде як раніше (всі кнопки доступні).
    """
    kb = InlineKeyboardBuilder()
    st = (status or "").strip().lower()

    allow_any = (d is None or uid is None)

    def _allow(fn):
        return True if allow_any else fn(d, uid)

    # 1) В роботу
    if st in ("paid", "prepay") and _allow(can_manage_orders):
        kb.button(text="🟡 В роботу", callback_data=f"adm:order:in_work:{oid}")

    # 2) Склад/пакування
    # picked = "зібрано" (комплектація)
    # packed = "запаковано"
    if st in ("paid", "prepay", "in_work", "picked") and _allow(can_mark_packing):
        kb.button(text="📦 Зібрано", callback_data=f"adm:order:picked:{oid}")
    if st in ("paid", "prepay", "in_work", "picked", "packed") and _allow(can_mark_packing):
        kb.button(text="🎁 Запаковано", callback_data=f"adm:order:packed:{oid}")

    # 3) Відправлено
    if st in ("paid", "prepay", "in_work", "picked", "packed", "shipped") and _allow(can_mark_logistics):
        kb.button(text="🚚 Відправлено", callback_data=f"adm:order:shipped:{oid}")

    # 4) Після відправки
    if st == "shipped" and _allow(can_mark_logistics):
        kb.button(text="✅ Отримано (клієнт)", callback_data=f"adm:order:received:{oid}")
        kb.button(text="❌ Не забрав", callback_data=f"adm:order:not_picked:{oid}")
        kb.button(text="🔁 Повернуто", callback_data=f"adm:order:returned:{oid}")

    # 5) Закрити (done)
    if st in ("paid", "prepay", "in_work", "picked", "packed", "shipped", "received", "returned", "not_picked") and _allow(can_mark_logistics):
        kb.button(text="✅ Закрити (done)", callback_data=f"adm:order:done:{oid}")

    # 6) Додатково
    kb.button(text="📜 Хронологія", callback_data=f"adm:order:timeline:{oid}")

    if _allow(can_set_ttn):
        kb.button(text="📮 Встановити ТТН", callback_data=f"adm:order:set_ttn:{oid}")

    kb.button(text="👤 Історія покупця", callback_data=f"adm:order:history:{oid}")

    kb.adjust(1)
    return kb.as_markup()


# -------------------------------------------------------------
# ✅ НОВИЙ order_change_status
# -------------------------------------------------------------
@router.callback_query(F.data.startswith("adm:order:"))
async def order_change_status(cb: types.CallbackQuery, bot: Bot, state: FSMContext):
    d = await load_data()
    if not is_staff(d, cb.from_user.id):
        return await cb.answer("Немає доступу", show_alert=True)

    # adm:order:<action>:<oid>
    _, _, action, oid_str = cb.data.split(":")
    oid = int(oid_str)

    order = next((o for o in (d.get("orders", []) or []) if int(o.get("id", -1)) == oid), None)
    if not order:
        await cb.message.answer("❌ Замовлення не знайдено.")
        return await cb.answer()

    # -------- рольові обмеження --------
    if action in ("picked", "packed") and not can_mark_packing(d, cb.from_user.id):
        return await cb.answer("⛔️ Недостатньо прав", show_alert=True)

    if action in ("in_work", "shipped", "received", "not_picked", "returned", "done", "set_ttn") and not can_mark_logistics(d, cb.from_user.id):
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

    # ---- В РОБОТУ ----
    if action == "in_work":
        if st not in ("paid", "prepay"):
            return await cb.answer("Тільки paid/prepay можна взяти в роботу", show_alert=True)

        # ✅ ВАЖЛИВО: статус міняємо ТІЛЬКИ через order_set_status
        order_set_status(order, "in_work", details=f"Ким: {cb.from_user.id}")
        await save_data(d)

        await _reply_updated(f"🟡 Замовлення #{oid} взято в роботу.")
        await _notify_buyer(bot, d, order, f"🟡 Ваше замовлення #{oid} взято в роботу ✅")
        return await cb.answer()

    # ---- ЗІБРАНО (picked = склад/комплектація, НЕ клієнт) ----
    if action == "picked":
        if st not in ("paid", "prepay", "in_work", "picked"):
            return await cb.answer("Збирати можна після оплати/в роботі", show_alert=True)

        order_set_status(order, "picked", details=f"Зібрано (склад). Ким: {cb.from_user.id}")
        await save_data(d)

        await _reply_updated(f"📦 Замовлення #{oid}: ЗІБРАНО (склад).")
        return await cb.answer()

    # ---- ЗАПАКОВАНО ----
    if action == "packed":
        if st not in ("paid", "prepay", "in_work", "picked", "packed"):
            return await cb.answer("Пакувати можна після 'в роботі/зібрано'", show_alert=True)

        order_set_status(order, "packed", details=f"Запаковано. Ким: {cb.from_user.id}")
        await save_data(d)

        await _reply_updated(f"🎁 Замовлення #{oid}: ЗАПАКОВАНО.")
        return await cb.answer()

    # ---- ВІДПРАВЛЕНО ----
    if action == "shipped":
        if st not in ("paid", "prepay", "in_work", "picked", "packed", "shipped"):
            return await cb.answer("Неможливо позначити як відправлено", show_alert=True)

        order_set_status(order, "shipped", details=f"Відправлено. Ким: {cb.from_user.id}")
        await save_data(d)

        await _reply_updated(f"🚚 Замовлення #{oid} позначено як ВІДПРАВЛЕНО.")

        # ✅ після shipped просимо ТТН через FSM (як і в тебе)
        await state.clear()
        await state.set_state(AdminFSM.order_ttn)
        await state.update_data(oid=oid)
        await cb.message.answer("📮 Введіть ТТН для цього замовлення (або '-' якщо без ТТН):")
        return await cb.answer()

    # ---- ОТРИМАНО (received = клієнт забрав/отримав) ----
    if action == "received":
        if st != "shipped":
            return await cb.answer("Спочатку треба 'Відправлено'", show_alert=True)

        order_set_status(order, "received", details=f"Клієнт отримав. Ким: {cb.from_user.id}")
        await save_data(d)

        await _reply_updated(f"✅ Замовлення #{oid}: КЛІЄНТ ОТРИМАВ.")
        await _notify_buyer(bot, d, order, f"✅ Замовлення #{oid}: отримано. Дякуємо! 🙌")
        return await cb.answer()

    # ---- НЕ ЗАБРАВ ----
    if action == "not_picked":
        if st != "shipped":
            return await cb.answer("Це доречно тільки після 'Відправлено'", show_alert=True)

        order_set_status(order, "not_picked", details=f"Не забрав. Ким: {cb.from_user.id}")
        await save_data(d)

        await _reply_updated(f"❌ Замовлення #{oid}: НЕ ЗАБРАВ.")
        await _notify_buyer(bot, d, order, f"❌ Замовлення #{oid}: не забрано. Напишіть нам — допоможемо 🤝")
        return await cb.answer()

    # ---- ПОВЕРНУТО ----
    if action == "returned":
        if st not in ("shipped", "not_picked", "received"):
            return await cb.answer("Повернення ставимо після логістики", show_alert=True)

        order_set_status(order, "returned", details=f"Повернуто. Ким: {cb.from_user.id}")
        await save_data(d)

        await _reply_updated(f"🔁 Замовлення #{oid}: ПОВЕРНУТО.")
        await _notify_buyer(bot, d, order, f"🔁 Замовлення #{oid}: повернено. Якщо є питання — пишіть 🙏")
        return await cb.answer()

    # ---- DONE ----
    if action == "done":
        if st not in ("paid", "prepay", "in_work", "picked", "packed", "shipped", "received", "returned", "not_picked"):
            return await cb.answer("Неможливо завершити", show_alert=True)

        order_set_status(order, "done", details=f"Закрито (done). Ким: {cb.from_user.id}")
        await save_data(d)

        await _reply_updated(f"✅ Замовлення #{oid} закрито (done).")
        return await cb.answer()

    # ---- історія покупця (як було, але kb тепер рольовий) ----
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
            kb = order_actions_kb(int(o["id"]), str(o.get("status", "")), d=d, uid=cb.from_user.id)
            await cb.message.answer(
                order_premium_text(d, o, products),
                parse_mode="HTML",
                reply_markup=kb
            )
        return await cb.answer()

    # timeline / set_ttn (якщо в тебе окремі хендлери) — тут не ламаємо
    return await cb.answer("OK")
# =================== END PART 6/8 (REPEAT) ===================
