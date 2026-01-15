# handlers/user.py
import time
import re
import math
from typing import Tuple, List, Dict

from aiogram import Router, F, types, Bot
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

from data import load_data, save_data, find_product, cart_total, next_order_id
from states import OrderFSM
from utils import notify_staff, format_order_text
from text import product_card
from config import PREPAY_AMOUNT

router = Router()

NO_SUB = "_"
CART_PER_PAGE = 6  # ✅ 6 товари на сторінку


# ===================== USERS (TRACK) =====================

def upsert_user(d: dict, u: types.User) -> None:
    d.setdefault("users", {})
    uid = str(u.id)

    now = int(time.time())
    full_name = " ".join([x for x in [u.first_name, u.last_name] if x]) or ""
    username = (u.username or "")

    if uid not in d["users"]:
        d["users"][uid] = {
            "id": u.id,
            "username": username,
            "full_name": full_name,
            "first_seen_ts": now,
            "last_seen_ts": now,
        }
    else:
        d["users"][uid]["id"] = u.id
        d["users"][uid]["username"] = username
        d["users"][uid]["full_name"] = full_name
        d["users"][uid]["last_seen_ts"] = now


# ===================== PHONE HELPERS =====================

def phone_request_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📲 Поділитися номером", request_contact=True)],
            [KeyboardButton(text="❌ Відміна")],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def normalize_phone(text: str) -> str:
    if not text:
        return ""
    t = text.strip()
    has_plus = t.startswith("+")
    digits = re.sub(r"\D+", "", t)
    if has_plus and digits:
        return "+" + digits
    return digits


def is_valid_phone(text: str) -> bool:
    digits = re.sub(r"\D+", "", text or "")
    return len(digits) >= 10


# ===================== MENUS =====================

def main_menu() -> types.ReplyKeyboardMarkup:
    return types.ReplyKeyboardMarkup(
        keyboard=[
            [types.KeyboardButton(text="🛍 Каталог"), types.KeyboardButton(text="🧺 Кошик")],
            [types.KeyboardButton(text="🔥 Хіти/Акції"), types.KeyboardButton(text="⭐ Обране")],
            [types.KeyboardButton(text="📦 Історія замовлень"), types.KeyboardButton(text="🆘 Підтримка")],
        ],
        resize_keyboard=True
    )


def catalog_kb(cats):
    kb = InlineKeyboardBuilder()
    for c in cats:
        kb.button(text=str(c), callback_data=f"cat:{c}")
    kb.adjust(1)
    return kb.as_markup()


def subcat_kb(cat: str, subs):
    kb = InlineKeyboardBuilder()

    kb.button(text="⬅️ Назад", callback_data="catalog:back")
    kb.button(text="Утлет 🧷", callback_data=f"sub:{cat}:{NO_SUB}")

    for s in subs:
        if s == NO_SUB:
            continue
        kb.button(text=str(s), callback_data=f"sub:{cat}:{s}")

    kb.adjust(1)
    return kb.as_markup()


def product_kb(pid: int, fav: bool = False):
    kb = InlineKeyboardBuilder()
    kb.button(text="🛒 В кошик", callback_data=f"add:{pid}")
    kb.button(
        text=("❌ З обраного" if fav else "⭐ В обране"),
        callback_data=f"fav:{'off' if fav else 'on'}:{pid}"
    )
    kb.adjust(2)
    return kb.as_markup()


def payment_choice_kb(oid: int, total: float):
    kb = InlineKeyboardBuilder()
    kb.button(text=f"💳 Повна оплата ({total:.2f} ₴)", callback_data=f"pay_full:{oid}")
    kb.button(text=f"💵 Передплата {PREPAY_AMOUNT} ₴ (НП/наложка)", callback_data=f"pay_prepay:{oid}")
    kb.adjust(1)
    return kb.as_markup()


# ===================== FAVS =====================

def user_favs(d, uid: int):
    d.setdefault("favorites", {})
    return d["favorites"].setdefault(str(uid), [])


def is_fav(d, uid: int, pid: int) -> bool:
    favs = set(int(x) for x in user_favs(d, uid))
    return pid in favs


# ===================== SAFE DELETE =====================

async def _safe_delete(msg: types.Message):
    try:
        await msg.delete()
    except Exception:
        pass


# ===================== SEND PRODUCT (for hits/favs lists) =====================

async def send_product(message: types.Message, d, uid: int, p: dict):
    txt = product_card(p)
    kb = product_kb(int(p["id"]), fav=is_fav(d, uid, int(p["id"])))

    photos = p.get("photos", []) or []
    if photos:
        await message.answer_photo(photos[0], caption=txt, parse_mode="HTML", reply_markup=kb)
    else:
        await message.answer(txt, parse_mode="HTML", reply_markup=kb)


def find_order(d, oid: int):
    for o in d.get("orders", []):
        if int(o.get("id", -1)) == int(oid):
            return o
    return None


# ===================== START / CANCEL =====================

@router.message(CommandStart())
async def start(m: types.Message, state: FSMContext):
    await state.clear()

    d = await load_data()
    upsert_user(d, m.from_user)
    await save_data(d)

    await m.answer("🏠 Меню", reply_markup=main_menu())


@router.message(F.text == "❌ Відміна")
async def user_cancel(m: types.Message, state: FSMContext):
    await state.clear()
    await m.answer("Скасовано. 🏠", reply_markup=main_menu())


# ===================== CATALOG (1 product per page) =====================

@router.message(F.text == "🛍 Каталог")
async def catalog(m: types.Message):
    d = await load_data()
    if not d.get("categories"):
        return await m.answer("Каталог порожній")
    await m.answer("Оберіть категорію:", reply_markup=catalog_kb(d["categories"].keys()))


@router.callback_query(F.data.startswith("cat:"))
async def choose_cat(cb: types.CallbackQuery):
    d = await load_data()
    cat = cb.data.split(":", 1)[1]
    subs = d.get("categories", {}).get(cat, {}) or {}
    if not subs:
        await cb.message.answer("У цій категорії поки немає товарів.")
        return await cb.answer()

    await cb.message.answer(
        f"<b>{cat}</b>\nОберіть підкатегорію:",
        parse_mode="HTML",
        reply_markup=subcat_kb(cat, subs.keys())
    )
    await cb.answer()


def product_page_kb(cat: str, sub: str, i: int, total: int, pid: int, fav: bool):
    kb = InlineKeyboardBuilder()

    kb.button(text="🛒 В кошик", callback_data=f"add:{pid}")
    kb.button(
        text=("❌ З обраного" if fav else "⭐ В обране"),
        callback_data=f"fav:{'off' if fav else 'on'}:{pid}"
    )

    prev_cb = "noop" if i <= 0 else f"page:{cat}:{sub}:{i-1}"
    next_cb = "noop" if i >= total - 1 else f"page:{cat}:{sub}:{i+1}"

    kb.button(text="⬅️", callback_data=prev_cb)
    kb.button(text=f"{i+1}/{total}", callback_data="noop")
    kb.button(text="➡️", callback_data=next_cb)

    kb.button(text="⬅️ Назад", callback_data=f"sub_back:{cat}")

    kb.adjust(2, 3, 1)
    return kb.as_markup()


async def show_product_page(cb: types.CallbackQuery, cat: str, sub: str, i: int):
    d = await load_data()
    items = d.get("categories", {}).get(cat, {}).get(sub, []) or []
    total = len(items)
    if total == 0:
        await cb.message.answer("Товарів немає.")
        return

    i = max(0, min(i, total - 1))
    p = items[i]

    txt = product_card(p)
    pid = int(p["id"])
    fav = is_fav(d, cb.from_user.id, pid)
    kb = product_page_kb(cat, sub, i, total, pid, fav)

    photos = p.get("photos", []) or []
    if photos:
        media = types.InputMediaPhoto(media=photos[0], caption=txt, parse_mode="HTML")
        try:
            await cb.message.edit_media(media=media, reply_markup=kb)
        except Exception:
            await _safe_delete(cb.message)
            await cb.message.answer_photo(photos[0], caption=txt, parse_mode="HTML", reply_markup=kb)
    else:
        try:
            await cb.message.edit_text(txt, parse_mode="HTML", reply_markup=kb)
        except Exception:
            await _safe_delete(cb.message)
            await cb.message.answer(txt, parse_mode="HTML", reply_markup=kb)


@router.callback_query(F.data.startswith("sub:"))
async def choose_sub(cb: types.CallbackQuery):
    d = await load_data()
    _, cat, sub = cb.data.split(":", 2)

    items = d.get("categories", {}).get(cat, {}).get(sub, []) or []
    if not items:
        await cb.message.answer("Товарів немає.")
        return await cb.answer()

    await show_product_page(cb, cat, sub, 0)
    await cb.answer()


@router.callback_query(F.data.startswith("page:"))
async def page_nav(cb: types.CallbackQuery):
    _, cat, sub, i_str = cb.data.split(":", 3)
    await show_product_page(cb, cat, sub, int(i_str))
    await cb.answer()


@router.callback_query(F.data == "noop")
async def noop(cb: types.CallbackQuery):
    await cb.answer()


@router.callback_query(F.data == "catalog:back")
async def catalog_back(cb: types.CallbackQuery):
    d = await load_data()
    if not d.get("categories"):
        await cb.message.answer("Каталог порожній")
        return await cb.answer()

    await cb.message.answer("Оберіть категорію:", reply_markup=catalog_kb(d["categories"].keys()))
    await cb.answer()


@router.callback_query(F.data.startswith("sub_back:"))
async def sub_back(cb: types.CallbackQuery):
    d = await load_data()
    cat = cb.data.split(":", 1)[1]
    subs = d.get("categories", {}).get(cat, {}) or {}
    if not subs:
        await cb.message.answer("У цій категорії поки немає товарів.")
        return await cb.answer()

    await _safe_delete(cb.message)

    await cb.message.answer(
        f"<b>{cat}</b>\nОберіть підкатегорію:",
        parse_mode="HTML",
        reply_markup=subcat_kb(cat, subs.keys())
    )
    await cb.answer()


# ===================== HITS / FAVS =====================

FAVS_PER_PAGE = 6  # ✅ 2 товари в ряд / на сторінку (як кошик)


@router.message(F.text == "🔥 Хіти/Акції")
async def hits(m: types.Message):
    d = await load_data()
    hits_ids = set(int(x) for x in (d.get("hits", []) or []))
    if not hits_ids:
        return await m.answer("Поки що немає Хітів/Акцій.")

    shown = 0
    for pid in hits_ids:
        p = find_product(d, int(pid))
        if p:
            shown += 1
            await send_product(m, d, m.from_user.id, p)

    if shown == 0:
        await m.answer("Хіти є, але товари не знайдені.")


# ---------- FAVS PAGED (як кошик, але без +/- і без delete) ----------

def _favs_items_all(d: dict, uid: int) -> List[dict]:
    favs = set(int(x) for x in user_favs(d, uid))
    items: List[dict] = []
    for pid in sorted(favs):
        p = find_product(d, pid)
        if p:
            items.append(p)
    return items


def _favs_pages_count(items_count: int) -> int:
    return max(1, int(math.ceil(items_count / FAVS_PER_PAGE)))


def favs_paged_kb(page_items: List[dict], page: int, pages: int) -> types.InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()

    # кнопки товарів
    for p in page_items:
        pid = int(p["id"])
        name = str(p.get("name", "Товар"))
        if len(name) > 18:
            name = name[:18] + "…"

        kb.button(
            text=f"⭐ {name}",
            callback_data=f"favs:open:{pid}:{page}"
        )

    kb.adjust(2)

    # ✅ пейджер тільки якщо сторінок більше 1
    if pages > 1:
        prev_p = page - 1 if page > 0 else None
        next_p = page + 1 if page < pages - 1 else None

        kb.row(
            types.InlineKeyboardButton(
                text="⬅️",
                callback_data=f"favs:page:{prev_p}" if prev_p is not None else "noop"
            ),
            types.InlineKeyboardButton(
                text=f"{page+1}/{pages}",
                callback_data="noop"
            ),
            types.InlineKeyboardButton(
                text="➡️",
                callback_data=f"favs:page:{next_p}" if next_p is not None else "noop"
            ),
        )

    return kb.as_markup()


def _render_favs_page(d: dict, uid: int, page: int) -> Tuple[str, List[dict], int, int]:
    all_items = _favs_items_all(d, uid)

    if not all_items:
        return "⭐ <b>Обране</b>\n\nОбране порожнє.", [], 0, 1

    pages = _favs_pages_count(len(all_items))
    page = max(0, min(page, pages - 1))

    start = page * FAVS_PER_PAGE
    end = start + FAVS_PER_PAGE
    page_items = all_items[start:end]

    lines: List[str] = []
    lines.append("⭐ <b>Обране</b>")

    # ✅ показуємо сторінку тільки якщо їх більше однієї
    if pages > 1:
        lines.append(f"<i>Позиції: {len(all_items)} · Сторінка: {page+1}/{pages}</i>")
    else:
        lines.append(f"<i>Позиції: {len(all_items)}</i>")

    lines.append("")
    lines.append("Натисніть на товар, щоб відкрити картку 👇")

    return "\n".join(lines), page_items, page, pages


async def _edit_favs(cb: types.CallbackQuery, page: int):
    d = await load_data()
    txt, page_items, page, pages = _render_favs_page(d, cb.from_user.id, page)

    # якщо обране порожнє
    if not page_items:
        # якщо ми зараз на фото-картці — краще видалити і надіслати текстом
        if cb.message and cb.message.photo:
            await _safe_delete(cb.message)
            await cb.message.answer(txt, parse_mode="HTML")
            return

        try:
            await cb.message.edit_text(txt, parse_mode="HTML", reply_markup=None)
        except Exception:
            pass
        return

    # ✅ якщо зараз відкрита картка товару з фото — повертаємось новим повідомленням
    if cb.message and cb.message.photo:
        await _safe_delete(cb.message)
        await cb.message.answer(
            txt,
            parse_mode="HTML",
            reply_markup=favs_paged_kb(page_items, page, pages)
        )
        return

    # звичайний режим (коли ми в текстовому повідомленні списку)
    await cb.message.edit_text(
        txt,
        parse_mode="HTML",
        reply_markup=favs_paged_kb(page_items, page, pages)
    )


@router.message(F.text == "⭐ Обране")
async def show_favs(m: types.Message):
    d = await load_data()
    txt, page_items, page, pages = _render_favs_page(d, m.from_user.id, 0)

    if not page_items:
        return await m.answer(txt, parse_mode="HTML")

    await m.answer(txt, parse_mode="HTML", reply_markup=favs_paged_kb(page_items, page, pages))


@router.callback_query(F.data.startswith("favs:page:"))
async def favs_page(cb: types.CallbackQuery):
    try:
        page = int(cb.data.split(":")[2])
    except Exception:
        page = 0
    await _edit_favs(cb, page)
    await cb.answer()


@router.callback_query(F.data.startswith("favs:open:"))
async def favs_open(cb: types.CallbackQuery):
    # favs:open:PID:PAGE
    try:
        _, _, pid_str, page_str = cb.data.split(":")
        pid = int(pid_str)
        page = int(page_str)
    except Exception:
        return await cb.answer("Некоректна дія", show_alert=True)

    d = await load_data()
    p = find_product(d, pid)
    if not p:
        return await cb.answer("Товар не знайдено", show_alert=True)

    cart = _cart_dict(d, cb.from_user.id)
    qty = int(cart.get(str(pid), 0) or 0)
    txt = product_card(p) + f"\n\n🧺 <b>В кошику</b>: <b>{qty}</b> шт"

    # ✅ визначаємо чи вже в обраному
    fav_now = is_fav(d, cb.from_user.id, pid)

    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ Назад в обране", callback_data=f"favs:page:{page}")
    kb.button(text="🛒 В кошик", callback_data=f"favs:add:{pid}:{page}")

    if fav_now:
        kb.button(text="❌ З обраного", callback_data=f"favp:off:{pid}:{page}")
    else:
        kb.button(text="⭐ В обране", callback_data=f"favp:on:{pid}:{page}")

    kb.adjust(1, 1, 1)

    photos = p.get("photos", []) or []
    if photos:
        media = types.InputMediaPhoto(media=photos[0], caption=txt, parse_mode="HTML")
        try:
            await cb.message.edit_media(media=media, reply_markup=kb.as_markup())
        except Exception:
            try:
                await cb.message.delete()
            except Exception:
                pass
            await cb.message.answer_photo(photos[0], caption=txt, parse_mode="HTML", reply_markup=kb.as_markup())
    else:
        try:
            await cb.message.edit_text(txt, parse_mode="HTML", reply_markup=kb.as_markup())
        except Exception:
            try:
                await cb.message.delete()
            except Exception:
                pass
            await cb.message.answer(txt, parse_mode="HTML", reply_markup=kb.as_markup())

    await cb.answer()


@router.callback_query(F.data.startswith("favs:add:"))
async def favs_add_to_cart(cb: types.CallbackQuery):
    # favs:add:PID:PAGE
    try:
        _, _, pid_str, page_str = cb.data.split(":")
        pid = int(pid_str)
        page = int(page_str)
    except Exception:
        return await cb.answer("Некоректна дія", show_alert=True)

    d = await load_data()
    uid = cb.from_user.id

    cart = _cart_dict(d, uid)
    cart[str(pid)] = int(cart.get(str(pid), 0) or 0) + 1
    await save_data(d)

    # перемальовуємо цю ж картку (оновиться qty)
    p = find_product(d, pid)
    if not p:
        return await cb.answer("Товар не знайдено", show_alert=True)

    qty = int(cart.get(str(pid), 0) or 0)
    txt = product_card(p) + f"\n\n🧺 <b>В кошику</b>: <b>{qty}</b> шт"

    fav_now = is_fav(d, uid, pid)

    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ Назад в обране", callback_data=f"favs:page:{page}")
    kb.button(text="🛒 В кошик", callback_data=f"favs:add:{pid}:{page}")

    if fav_now:
        kb.button(text="❌ З обраного", callback_data=f"favp:off:{pid}:{page}")
    else:
        kb.button(text="⭐ В обране", callback_data=f"favp:on:{pid}:{page}")

    kb.adjust(1, 1, 1)

    photos = p.get("photos", []) or []
    if photos:
        media = types.InputMediaPhoto(media=photos[0], caption=txt, parse_mode="HTML")
        try:
            await cb.message.edit_media(media=media, reply_markup=kb.as_markup())
        except Exception:
            try:
                await cb.message.edit_reply_markup(reply_markup=kb.as_markup())
            except Exception:
                pass
    else:
        try:
            await cb.message.edit_text(txt, parse_mode="HTML", reply_markup=kb.as_markup())
        except Exception:
            try:
                await cb.message.edit_reply_markup(reply_markup=kb.as_markup())
            except Exception:
                pass

    await cb.answer("Додано 🛒")


# ✅ апгрейд: якщо тиснуть "❌ З обраного" прямо в картці — одразу повертаємо в список "Обране"
@router.callback_query(F.data.startswith("fav:"))
async def fav_toggle(cb: types.CallbackQuery):
    """
    Загальний toggle для:
    - каталогу (product_page_kb)
    - хітів/акцій (send_product)
    НЕ чіпає "картку обраного" — там використовується favp:...
    """
    d = await load_data()
    uid = cb.from_user.id

    try:
        _, mode, pid_str = cb.data.split(":")
        pid = int(pid_str)
    except Exception:
        return await cb.answer("Некоректна дія", show_alert=True)

    favs = user_favs(d, uid)
    sset = set(int(x) for x in favs)

    if mode == "on":
        sset.add(pid)
        await cb.answer("⭐ Додано в обране")
    else:
        sset.discard(pid)
        await cb.answer("❌ Прибрано з обраного")

    d["favorites"][str(uid)] = list(sset)
    await save_data(d)

    # ✅ Оновлюємо КНОПКИ на поточному повідомленні (без переходів)
    # Якщо це сторінка каталогу (page:cat:sub:i) — просто перемальовуємо її
    try:
        if cb.message and cb.message.reply_markup:
            # якщо callback прийшов з каталогу (там є page:...)
            if cb.message.reply_markup.inline_keyboard:
                # намагаємось визначити контекст по callback кнопок (page:)
                all_cb = []
                for row in cb.message.reply_markup.inline_keyboard:
                    for b in row:
                        if b.callback_data:
                            all_cb.append(b.callback_data)

                # якщо є кнопка page:... — це каталог з посторінковим переглядом
                page_btn = next((x for x in all_cb if x.startswith("page:")), None)
                if page_btn:
                    # page:cat:sub:i
                    _, cat, sub, i_str = page_btn.split(":", 3)
                    await show_product_page(cb, cat, sub, int(i_str))
                    return

            # інакше (хіти/акції або надіслана картка) — просто міняємо клавіатуру
            # Витягаємо товар і ставимо правильну кнопку (⭐/❌)
            p = find_product(d, pid)
            if p:
                kb = product_kb(pid, fav=is_fav(d, uid, pid))
                await cb.message.edit_reply_markup(reply_markup=kb)
    except Exception:
        # якщо Telegram не дав edit — нічого страшного
        pass

# ===================== CART (PAGED, 2 ITEMS) =====================

def _money_uah(x) -> str:
    try:
        v = float(x)
    except Exception:
        v = 0.0
    if v.is_integer():
        return f"{int(v)} ₴"
    return f"{v:.2f} ₴"


def _promo_active(p: dict, now_ts: int) -> bool:
    try:
        promo_price = float(p.get("promo_price") or 0)
    except Exception:
        promo_price = 0.0
    if promo_price <= 0:
        return False

    until = p.get("promo_until_ts")
    if until is None:
        return True
    try:
        until_i = int(until)
    except Exception:
        return True
    return now_ts <= until_i


def _unit_price_str(p: dict, now_ts: int) -> str:
    base = float(p.get("base_price", p.get("price", 0)) or 0)
    if _promo_active(p, now_ts):
        promo = float(p.get("promo_price") or 0)
        return f"<s>{_money_uah(base)}</s> → <b>{_money_uah(promo)}</b>"
    return f"<b>{_money_uah(base)}</b>"


def _cart_dict(d: dict, uid: int) -> dict:
    d.setdefault("carts", {})
    key = str(uid)
    raw = d["carts"].get(key, {})

    # міграція зі старого list
    if isinstance(raw, list):
        out: dict[str, int] = {}
        for x in raw:
            try:
                pid = str(int(x))
            except Exception:
                continue
            out[pid] = out.get(pid, 0) + 1
        d["carts"][key] = out
        return out

    if isinstance(raw, dict):
        out: dict[str, int] = {}
        for k, v in raw.items():
            try:
                pid = str(int(k))
                qty = int(v)
            except Exception:
                continue
            if qty > 0:
                out[pid] = qty
        d["carts"][key] = out
        return out

    d["carts"][key] = {}
    return d["carts"][key]


def _cart_items_all(d: dict, cart: dict) -> List[dict]:
    items: List[dict] = []
    for pid_str in sorted(cart.keys(), key=lambda x: int(x) if str(x).isdigit() else 10**9):
        qty = int(cart.get(pid_str, 0) or 0)
        if qty <= 0:
            continue
        p = find_product(d, int(pid_str))
        if p:
            items.append(p)
    return items


def _cart_pages_count(items_count: int) -> int:
    return max(1, int(math.ceil(items_count / CART_PER_PAGE)))


def cart_paged_kb(cart: dict, page_items: List[dict], page: int, pages: int):
    kb = InlineKeyboardBuilder()

    # ✅ Кнопки товарів (2 колонки, до CART_PER_PAGE штук)
    for p in page_items:
        pid = int(p["id"])
        name = str(p.get("name", "Товар"))
        if len(name) > 18:
            name = name[:18] + "…"

        kb.button(
            text=f"🧾 {name}",
            callback_data=f"cart:open:{pid}:{page}"
        )

    kb.adjust(2)

    # ✅ pager показуємо ТІЛЬКИ якщо сторінок більше 1
    if pages > 1:
        prev_p = page - 1 if page > 0 else None
        next_p = page + 1 if page < pages - 1 else None

        kb.row(
            types.InlineKeyboardButton(
                text="⬅️",
                callback_data=f"cart:page:{prev_p}" if prev_p is not None else "noop"
            ),
            types.InlineKeyboardButton(
                text=f"{page+1}/{pages}",
                callback_data="noop"
            ),
            types.InlineKeyboardButton(
                text="➡️",
                callback_data=f"cart:page:{next_p}" if next_p is not None else "noop"
            ),
        )

    # --- actions ---
    kb.row(
        types.InlineKeyboardButton(text="🧾 Оформити замовлення", callback_data="checkout"),
        types.InlineKeyboardButton(text="🗑 Очистити", callback_data="clear"),
    )

    return kb.as_markup()


def _render_cart_page(d: dict, uid: int, page: int) -> Tuple[str, float, List[dict], dict, int, int]:
    cart = _cart_dict(d, uid)
    all_items = _cart_items_all(d, cart)

    if not all_items:
        return "Кошик порожній", 0.0, [], cart, 0, 1

    pages = _cart_pages_count(len(all_items))
    page = max(0, min(page, pages - 1))

    start = page * CART_PER_PAGE
    end = start + CART_PER_PAGE
    page_items = all_items[start:end]

    total = cart_total(d, cart)
    now_ts = int(time.time())

    lines: List[str] = []
    lines.append("🧺 <b>Кошик</b>")

    # ✅ показуємо "Сторінка: ..." тільки якщо сторінок більше 1
    if pages > 1:
        lines.append(f"<i>Позиції: {len(all_items)} · Сторінка: {page+1}/{pages}</i>")
    else:
        lines.append(f"<i>Позиції: {len(all_items)}</i>")

    lines.append("")

    for p in page_items:
        pid = int(p["id"])
        qty = int(cart.get(str(pid), 0) or 0)
        if qty <= 0:
            continue

        unit_is_promo = _promo_active(p, now_ts)
        unit_val = float(p.get("promo_price") or 0) if unit_is_promo else float(p.get("base_price", p.get("price", 0)) or 0)
        line_total = unit_val * qty

        name = str(p.get("name", "Товар"))
        price_str = _unit_price_str(p, now_ts)

        lines.append(f"• <b>{name}</b>")
        lines.append(f"  {price_str} × <b>{qty}</b> = <b>{_money_uah(line_total)}</b>")
        lines.append("")

    lines.append(f"💳 <b>Разом</b>: <b>{_money_uah(total)}</b>")
    return "\n".join(lines), float(total), page_items, cart, page, pages


async def _show_cart_page(cb: types.CallbackQuery, page: int):
    d = await load_data()
    txt, total, page_items, cart, page, pages = _render_cart_page(d, cb.from_user.id, page)

    if not page_items:
        # якщо ми були в “картці з фото” — краще видалити і відправити текст
        if cb.message and cb.message.photo:
            await _safe_delete(cb.message)
            await cb.message.answer("Кошик порожній", reply_markup=main_menu())
        else:
            try:
                await cb.message.edit_text("Кошик порожній", reply_markup=None)
            except Exception:
                pass
        return

    # якщо зараз відкрита картка товару з фото — кошик показуємо НОВИМ повідомленням (delete + send),
    # бо caption має ліміт і ми не хочемо перетворювати медіа у текст.
    if cb.message and cb.message.photo:
        await _safe_delete(cb.message)
        await cb.message.answer(txt, parse_mode="HTML", reply_markup=cart_paged_kb(cart, page_items, page, pages))
        return

    await cb.message.edit_text(txt, parse_mode="HTML", reply_markup=cart_paged_kb(cart, page_items, page, pages))


def cart_item_kb(pid: int, qty: int, page: int) -> types.InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()

    kb.row(
        types.InlineKeyboardButton(text="➖", callback_data=f"cart:dec:{pid}:{page}"),
        types.InlineKeyboardButton(text="➕", callback_data=f"cart:inc:{pid}:{page}"),
    )

    kb.row(types.InlineKeyboardButton(text="🗑 Прибрати", callback_data=f"cart:rm:{pid}:{page}"))
    kb.row(types.InlineKeyboardButton(text="🧺 Назад в кошик", callback_data=f"cart:page:{page}"))

    return kb.as_markup()


async def _show_cart_item(cb: types.CallbackQuery, pid: int, page: int):
    d = await load_data()
    p = find_product(d, pid)
    if not p:
        return await cb.answer("Товар не знайдено", show_alert=True)

    cart = _cart_dict(d, cb.from_user.id)
    qty = int(cart.get(str(pid), 0) or 0)
    if qty <= 0:
        return await cb.answer("Цього товару вже нема в кошику", show_alert=True)

    # ✅ додаємо у картку візуально “скільки в кошику”
    txt = product_card(p) + f"\n\n🧺 <b>В кошику</b>: <b>{qty}</b> шт"
    kb = cart_item_kb(pid, qty, page)

    photos = p.get("photos", []) or []
    if photos:
        media = types.InputMediaPhoto(media=photos[0], caption=txt, parse_mode="HTML")
        try:
            await cb.message.edit_media(media=media, reply_markup=kb)
        except Exception:
            await _safe_delete(cb.message)
            await cb.message.answer_photo(photos[0], caption=txt, parse_mode="HTML", reply_markup=kb)
    else:
        try:
            await cb.message.edit_text(txt, parse_mode="HTML", reply_markup=kb)
        except Exception:
            await _safe_delete(cb.message)
            await cb.message.answer(txt, parse_mode="HTML", reply_markup=kb)


# ===================== CART ACTIONS =====================

@router.callback_query(F.data.startswith("add:"))
async def add_cart(cb: types.CallbackQuery):
    d = await load_data()
    pid = int(cb.data.split(":")[1])

    cart = _cart_dict(d, cb.from_user.id)
    cart[str(pid)] = int(cart.get(str(pid), 0) or 0) + 1
    await save_data(d)

    await cb.answer("Додано 🛒")


@router.message(F.text == "🧺 Кошик")
async def show_cart(m: types.Message):
    d = await load_data()
    txt, total, page_items, cart, page, pages = _render_cart_page(d, m.from_user.id, 0)

    if not page_items:
        return await m.answer("Кошик порожній", reply_markup=main_menu())

    await m.answer(txt, parse_mode="HTML", reply_markup=cart_paged_kb(cart, page_items, page, pages))


@router.callback_query(F.data == "clear")
async def clear_cart(cb: types.CallbackQuery):
    d = await load_data()
    d.setdefault("carts", {})
    d["carts"][str(cb.from_user.id)] = {}
    await save_data(d)
    await cb.answer("Очищено 🗑")

    # якщо було фото — видалити і відправити текст
    if cb.message and cb.message.photo:
        await _safe_delete(cb.message)
        await cb.message.answer("Кошик порожній", reply_markup=main_menu())
        return

    try:
        await cb.message.edit_text("Кошик порожній", reply_markup=None)
    except Exception:
        pass


@router.callback_query(F.data.startswith("cart:page:"))
async def cart_page(cb: types.CallbackQuery):
    try:
        page = int(cb.data.split(":")[2])
    except Exception:
        page = 0

    await _show_cart_page(cb, page)
    await cb.answer()


@router.callback_query(F.data.startswith("cart:open:"))
async def cart_open_product(cb: types.CallbackQuery):
    # cart:open:{pid}:{page}
    try:
        _, _, pid_str, page_str = cb.data.split(":", 3)
        pid = int(pid_str)
        page = int(page_str)
    except Exception:
        return await cb.answer("Некоректна дія", show_alert=True)

    await _show_cart_item(cb, pid, page)
    await cb.answer()


@router.callback_query(F.data.startswith("cart:inc:"))
async def cart_inc(cb: types.CallbackQuery):
    # cart:inc:{pid}:{page}
    try:
        _, _, pid_str, page_str = cb.data.split(":", 3)
        pid = int(pid_str)
        page = int(page_str)
    except Exception:
        return await cb.answer()

    d = await load_data()
    cart = _cart_dict(d, cb.from_user.id)
    cart[str(pid)] = int(cart.get(str(pid), 0) or 0) + 1
    await save_data(d)

    # ✅ якщо в картці (фото або текст із "В кошику") — оновлюємо картку
    is_card = bool(cb.message and (
        cb.message.photo or ("🧺 <b>В кошику</b>:" in (cb.message.text or cb.message.caption or ""))
    ))

    if is_card:
        await _show_cart_item(cb, pid, page)
    else:
        await _show_cart_page(cb, page)

    await cb.answer()


@router.callback_query(F.data.startswith("cart:dec:"))
async def cart_dec(cb: types.CallbackQuery):
    # cart:dec:{pid}:{page}
    try:
        _, _, pid_str, page_str = cb.data.split(":", 3)
        pid = int(pid_str)
        page = int(page_str)
    except Exception:
        return await cb.answer()

    d = await load_data()
    cart = _cart_dict(d, cb.from_user.id)
    cur = int(cart.get(str(pid), 0) or 0)
    if cur <= 1:
        cart.pop(str(pid), None)
    else:
        cart[str(pid)] = cur - 1
    await save_data(d)

    # якщо товар видалився — вертаємось у кошик
    if int(_cart_dict(d, cb.from_user.id).get(str(pid), 0) or 0) <= 0:
        await _show_cart_page(cb, page)
        return await cb.answer()

    if cb.message and cb.message.photo:
        await _show_cart_item(cb, pid, page)
    else:
        await _show_cart_page(cb, page)

    await cb.answer()


@router.callback_query(F.data.startswith("cart:rm:"))
async def cart_rm(cb: types.CallbackQuery):
    # cart:rm:{pid}:{page}
    try:
        _, _, pid_str, page_str = cb.data.split(":", 3)
        pid = int(pid_str)
        page = int(page_str)
    except Exception:
        return await cb.answer()

    d = await load_data()
    cart = _cart_dict(d, cb.from_user.id)
    cart.pop(str(pid), None)
    await save_data(d)

    await _show_cart_page(cb, page)
    await cb.answer("Прибрано 🗑")


# ===================== CHECKOUT FLOW =====================

@router.callback_query(F.data == "checkout")
async def checkout(cb: types.CallbackQuery, state: FSMContext):
    d = await load_data()
    cart = _cart_dict(d, cb.from_user.id)
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
    await m.answer(
        "📞 Надішліть номер телефону кнопкою або введіть вручну (мінімум 10 цифр):",
        reply_markup=phone_request_kb()
    )


@router.message(OrderFSM.phone)
async def order_phone(m: types.Message, state: FSMContext):
    phone_raw = ""
    if m.contact and m.contact.phone_number:
        phone_raw = m.contact.phone_number
    if not phone_raw:
        phone_raw = (m.text or "").strip()

    if not phone_raw:
        return await m.answer(
            "📞 Надішліть номер телефону кнопкою або введіть вручну.\nМінімум 10 цифр.",
            reply_markup=phone_request_kb()
        )

    if not is_valid_phone(phone_raw):
        return await m.answer(
            "❌ Номер виглядає некоректно.\nВведіть ще раз (мінімум 10 цифр) або натисніть кнопку 👇",
            reply_markup=phone_request_kb()
        )

    await state.update_data(phone=normalize_phone(phone_raw))
    await state.set_state(OrderFSM.city)
    await m.answer("🏙 Введіть місто:", reply_markup=main_menu())


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

    d = await load_data()

    cart = _cart_dict(d, m.from_user.id)
    if not cart:
        await state.clear()
        return await m.answer("Кошик порожній. Почніть знову.", reply_markup=main_menu())

    total = cart_total(d, cart)
    oid = next_order_id(d)

    items_pack = []
    for pid_str, qty in (cart or {}).items():
        try:
            pid_i = int(pid_str)
            qty_i = int(qty)
        except Exception:
            continue
        if qty_i > 0:
            items_pack.append({"pid": pid_i, "qty": qty_i})

    d.setdefault("orders", [])
    d["orders"].append({
        "id": oid,
        "user_id": m.from_user.id,
        "user_username": (m.from_user.username or ""),
        "user_full_name": (m.from_user.full_name or ""),

        "items": items_pack,
        "total": float(total),

        "status": "pending",
        "created_ts": int(time.time()),

        "payment_method": None,
        "paid_ts": None,
        "prepay_amount": 0,
        "prepay_ts": None,

        "delivery": {
            "name": st.get("name", ""),
            "phone": st.get("phone", ""),
            "city": st.get("city", ""),
            "np_branch": st.get("np_branch", ""),
            "comment": st.get("comment", ""),
        }
    })

    await save_data(d)
    await state.clear()

    await m.answer(
        f"✅ Замовлення створено #{oid}\n"
        f"Сума: {total:.2f} ₴\n\n"
        f"Оберіть спосіб оплати:",
        reply_markup=payment_choice_kb(oid, total)
    )


# ===================== PAY (SIMULATION) =====================

@router.callback_query(F.data.startswith("pay_full:"))
async def pay_full(cb: types.CallbackQuery, bot: Bot):
    d = await load_data()
    oid = int(cb.data.split(":")[1])

    order = find_order(d, oid)
    if not order:
        await cb.message.answer("❌ Замовлення не знайдено.")
        return await cb.answer()

    if order.get("status") in ("paid", "prepay", "in_work", "done"):
        return await cb.answer("Це замовлення вже опрацьовується.", show_alert=True)

    order["payment_method"] = "full"
    order["status"] = "paid"
    order["paid_ts"] = int(time.time())

    d.setdefault("carts", {})
    d["carts"][str(order["user_id"])] = {}
    await save_data(d)

    await cb.message.answer(
        "✅ Оплачено (симуляція).\n\n"
        f"Дякуємо! Замовлення #{oid} прийнято.\n"
        "Менеджер зв’яжеться з вами найближчим часом.",
        reply_markup=main_menu()
    )
    await cb.answer()

    user_link = f'<a href="tg://user?id={order["user_id"]}">👤 Покупець</a>'
    txt = "🆕 НОВЕ ОПЛАЧЕНЕ ЗАМОВЛЕННЯ\n\n" + user_link + "\n\n" + format_order_text(d, order)
    await notify_staff(bot, txt, parse_mode="HTML")


@router.callback_query(F.data.startswith("pay_prepay:"))
async def pay_prepay(cb: types.CallbackQuery, bot: Bot):
    d = await load_data()
    oid = int(cb.data.split(":")[1])

    order = find_order(d, oid)
    if not order:
        await cb.message.answer("❌ Замовлення не знайдено.")
        return await cb.answer()

    if order.get("status") in ("paid", "prepay", "in_work", "done"):
        return await cb.answer("Це замовлення вже опрацьовується.", show_alert=True)

    total = float(order.get("total", 0) or 0)
    prepay = int(PREPAY_AMOUNT)
    rest = max(0.0, total - prepay)

    order["payment_method"] = "np_prepay_200"
    order["status"] = "prepay"
    order["prepay_amount"] = prepay
    order["prepay_ts"] = int(time.time())

    d.setdefault("carts", {})
    d["carts"][str(order["user_id"])] = {}
    await save_data(d)

    await cb.message.answer(
        "✅ Передплату зафіксовано (симуляція).\n\n"
        f"Передплата: {prepay} ₴\n"
        f"Залишок до сплати на НП: {rest:.2f} ₴\n\n"
        f"Замовлення #{oid} прийнято. Менеджер зв’яжеться з вами.",
        reply_markup=main_menu()
    )
    await cb.answer()

    user_link = f'<a href="tg://user?id={order["user_id"]}">👤 Покупець</a>'
    txt = "🆕 НОВЕ ЗАМОВЛЕННЯ (ПЕРЕДПЛАТА / НП)\n\n" + user_link + "\n\n" + format_order_text(d, order)
    await notify_staff(bot, txt, parse_mode="HTML")


# ===================== HISTORY / SUPPORT =====================

# ===================== HISTORY (PAGED, CLEAN) =====================

HISTORY_PER_PAGE = 8  # ✅ 6-8 як ти хотів (можеш поставити 6 або 10)

def _fmt_dt(ts: int) -> str:
    try:
        t = time.localtime(int(ts))
        return time.strftime("%d.%m.%Y %H:%M", t)
    except Exception:
        return "-"

def _status_emoji(s: str) -> str:
    s = (s or "").lower()
    if s in ("pending",):
        return "🕓"
    if s in ("paid", "prepay"):
        return "💰"
    if s in ("in_work",):
        return "🧑‍💼"
    if s in ("done",):
        return "✅"
    if s in ("canceled", "cancelled"):
        return "❌"
    return "📦"

def _ua_status(s: str) -> str:
    s = (s or "").lower()
    return {
        "pending": "Очікує",
        "paid": "Оплачено",
        "prepay": "Передплата",
        "in_work": "В роботі",
        "done": "Виконано",
        "returned": "Повернуто",
        "canceled": "Скасовано",
        "cancelled": "Скасовано",
    }.get(s, s)

def _orders_all_for_user(d: dict, uid: int) -> List[dict]:
    orders = [o for o in (d.get("orders", []) or []) if int(o.get("user_id", -1)) == int(uid)]
    # newest first
    orders.sort(key=lambda x: int(x.get("created_ts", 0) or 0), reverse=True)
    return orders

def _orders_pages_count(n: int) -> int:
    return max(1, int(math.ceil(n / HISTORY_PER_PAGE)))

def history_kb(page_orders: List[dict], page: int, pages: int) -> types.InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()

    # ✅ кнопки замовлень
    for o in page_orders:
        oid = int(o.get("id", 0) or 0)
        ts = int(o.get("created_ts", 0) or 0)
        st = str(o.get("status", "") or "")
        total = float(o.get("total", 0) or 0)

        # короткий текст на кнопці
        # приклад: "✅ #12 · 1200 ₴ · 14.01"
        date_short = _fmt_dt(ts)[:5]  # "dd.mm"
        kb.button(
            text=f"{_status_emoji(st)} #{oid} · {int(total) if float(total).is_integer() else f'{total:.0f}'} ₴ · {date_short}",
            callback_data=f"hist:open:{oid}:{page}",
        )

    kb.adjust(1)  # 1 колонка, щоб читалось

    # ✅ пейджер тільки якщо сторінок > 1
    if pages > 1:
        prev_p = page - 1 if page > 0 else None
        next_p = page + 1 if page < pages - 1 else None

        kb.row(
            types.InlineKeyboardButton(
                text="⬅️",
                callback_data=f"hist:page:{prev_p}" if prev_p is not None else "noop"
            ),
            types.InlineKeyboardButton(
                text=f"{page+1}/{pages}",
                callback_data="noop"
            ),
            types.InlineKeyboardButton(
                text="➡️",
                callback_data=f"hist:page:{next_p}" if next_p is not None else "noop"
            ),
        )

    return kb.as_markup()

def _render_history_page(d: dict, uid: int, page: int) -> Tuple[str, List[dict], int, int]:
    orders = _orders_all_for_user(d, uid)
    if not orders:
        return "📦 <b>Історія замовлень</b>\n\nІсторія порожня.", [], 0, 1

    pages = _orders_pages_count(len(orders))
    page = max(0, min(page, pages - 1))

    start = page * HISTORY_PER_PAGE
    end = start + HISTORY_PER_PAGE
    page_orders = orders[start:end]

    lines = []
    lines.append("📦 <b>Історія замовлень</b>")

    # ✅ “сторінка” показуємо тільки якщо їх > 1
    if pages > 1:
        lines.append(f"<i>Замовлень: {len(orders)} · Сторінка: {page+1}/{pages}</i>")
    else:
        lines.append(f"<i>Замовлень: {len(orders)}</i>")

    lines.append("")
    lines.append("Натисніть на замовлення, щоб відкрити деталі 👇")

    return "\n".join(lines), page_orders, page, pages

async def _show_history_page_msg(msg: types.Message, page: int):
    d = await load_data()
    txt, page_orders, page, pages = _render_history_page(d, msg.from_user.id, page)

    if not page_orders:
        return await msg.answer(txt, parse_mode="HTML", reply_markup=main_menu())

    await msg.answer(txt, parse_mode="HTML", reply_markup=history_kb(page_orders, page, pages))

async def _edit_history(cb: types.CallbackQuery, page: int):
    d = await load_data()
    txt, page_orders, page, pages = _render_history_page(d, cb.from_user.id, page)

    if not page_orders:
        # якщо ми були на картці з фото — безпечно видалити
        if cb.message and cb.message.photo:
            await _safe_delete(cb.message)
            await cb.message.answer(txt, parse_mode="HTML", reply_markup=main_menu())
            return

        try:
            await cb.message.edit_text(txt, parse_mode="HTML", reply_markup=None)
        except Exception:
            pass
        return

    # якщо ми на фото/картці — краще delete + send
    if cb.message and cb.message.photo:
        await _safe_delete(cb.message)
        await cb.message.answer(txt, parse_mode="HTML", reply_markup=history_kb(page_orders, page, pages))
        return

    await cb.message.edit_text(txt, parse_mode="HTML", reply_markup=history_kb(page_orders, page, pages))

@router.message(F.text == "📦 Історія замовлень")
async def history(m: types.Message):
    await _show_history_page_msg(m, 0)

@router.callback_query(F.data.startswith("hist:page:"))
async def hist_page(cb: types.CallbackQuery):
    try:
        page = int(cb.data.split(":")[2])
    except Exception:
        page = 0
    await _edit_history(cb, page)
    await cb.answer()

@router.callback_query(F.data.startswith("hist:open:"))
async def hist_open(cb: types.CallbackQuery):
    # hist:open:OID:PAGE
    try:
        _, _, oid_str, page_str = cb.data.split(":")
        oid = int(oid_str)
        page = int(page_str)
    except Exception:
        return await cb.answer("Некоректна дія", show_alert=True)

    d = await load_data()
    o = find_order(d, oid)
    if not o or int(o.get("user_id", -1)) != int(cb.from_user.id):
        return await cb.answer("Замовлення не знайдено", show_alert=True)

    created = _fmt_dt(int(o.get("created_ts", 0) or 0))
    status_raw = str(o.get("status", "") or "")
    status_ua = _ua_status(status_raw)
    total = float(o.get("total", 0) or 0)
    username = o.get("user_full_name") or o.get("user_username") or "—"

    total_txt = f"{int(total)}" if float(total).is_integer() else f"{total:.2f}"

    header = (
        f"📦 <b>Замовлення #{int(o.get('id', 0) or 0)}</b>\n"
        f"🕒 {created}\n"
        f"💳 Сума: <b>{total_txt} ₴</b>\n"
        f"🔁 Статус: <b>{status_ua}</b>\n"
        f"👤 Покупець: <b>{username}</b>\n\n"
    )

    # ✅ важливо: тут прибираємо англійський технічний статус і дубль "Замовлення #..."
    # тому НЕ додаємо format_order_text як є. Замінимо на “тіло” без шапки:
    body = format_order_text(d, o)

    # якщо твій format_order_text дублює шапку — просто прибери перший блок до "🛍 Товари"
    # (швидкий, безпечний спосіб — відрізати все до "🛍 Товари", якщо воно є)
    marker = "🛍"
    if marker in body:
        body = body[body.index(marker):]

    full_txt = header + body

    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ Назад в історію", callback_data=f"hist:page:{page}")
    kb.adjust(1)

    try:
        await cb.message.edit_text(full_txt, parse_mode="HTML", reply_markup=kb.as_markup())
    except Exception:
        try:
            await _safe_delete(cb.message)
        except Exception:
            pass
        await cb.message.answer(full_txt, parse_mode="HTML", reply_markup=kb.as_markup())

    await cb.answer()


@router.message(F.text == "🆘 Підтримка")
async def support(m: types.Message):
    await m.answer(
        "🆘 Підтримка\n\n"
        "Напишіть нам:\n"
        "• Telegram: @katas_support\n"
        "• Або просто відповідайте на це повідомлення — ми передамо менеджеру.",
        reply_markup=main_menu()
    )