from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder

from utils import is_admin
from data import load_data, save_data, next_product_id
from states import AdminFSM

router = Router()

# ---------- KEYBOARDS ----------

def admin_menu() -> types.ReplyKeyboardMarkup:
    return types.ReplyKeyboardMarkup(
        keyboard=[
            [
                types.KeyboardButton(text="➕ Додати категорію"),
                types.KeyboardButton(text="➕ Додати підкатегорію"),
            ],
            [
                types.KeyboardButton(text="➕ Додати товар"),
                types.KeyboardButton(text="🛠 Товари"),
            ],
            [
                types.KeyboardButton(text="👤 Додати менеджера"),
            ],
        ],
        resize_keyboard=True
    )


def cats_inline_kb(prefix: str):
    """prefix например: 'subcat_cat' или 'prod_cat'"""
    d = load_data()
    kb = InlineKeyboardBuilder()
    for cat in d["categories"].keys():
        kb.button(text=str(cat), callback_data=f"admin:{prefix}:{cat}")
    kb.adjust(2)
    return kb.as_markup()


def subs_inline_kb(cat: str, prefix: str):
    d = load_data()
    subs = d["categories"].get(cat, {})
    kb = InlineKeyboardBuilder()
    for sub in subs.keys():
        kb.button(text=str(sub), callback_data=f"admin:{prefix}:{cat}:{sub}")
    kb.adjust(2)
    return kb.as_markup()


def products_inline_kb(cat: str, sub: str):
    d = load_data()
    kb = InlineKeyboardBuilder()
    for p in d["categories"][cat][sub]:
        kb.button(text=f"🗑 {p['name']}", callback_data=f"admin:delprod:{p['id']}")
    kb.adjust(1)
    return kb.as_markup()


# ---------- COMMAND ----------

@router.message(Command("admin"))
async def admin_cmd(m: types.Message):
    if not is_admin(m.from_user.id):
        return await m.answer("⛔️ Немає доступу")
    await m.answer("🔧 Адмін-панель", reply_markup=admin_menu())


# ---------- ADD CATEGORY ----------

@router.message(F.text == "➕ Додати категорію")
async def add_cat_btn(m: types.Message, state: FSMContext):
    if not is_admin(m.from_user.id):
        return await m.answer("⛔️ Немає доступу")
    await state.clear()
    await state.set_state(AdminFSM.add_cat)
    await m.answer("Введіть назву категорії:")


@router.message(AdminFSM.add_cat)
async def add_cat_name(m: types.Message, state: FSMContext):
    if not is_admin(m.from_user.id):
        return await m.answer("⛔️ Немає доступу")

    name = (m.text or "").strip()
    if not name:
        return await m.answer("Введіть назву текстом.")

    d = load_data()
    d["categories"].setdefault(name, {})
    save_data(d)

    await state.clear()
    await m.answer(f"✅ Категорію «{name}» додано.", reply_markup=admin_menu())


# ---------- ADD SUBCATEGORY ----------

@router.message(F.text == "➕ Додати підкатегорію")
async def add_sub_btn(m: types.Message, state: FSMContext):
    if not is_admin(m.from_user.id):
        return await m.answer("⛔️ Немає доступу")
    d = load_data()
    if not d["categories"]:
        return await m.answer("Спочатку додайте категорію.")
    await state.clear()
    await state.set_state(AdminFSM.add_sub_cat)
    await m.answer("Оберіть категорію:", reply_markup=cats_inline_kb("subcat_cat"))


@router.callback_query(F.data.startswith("admin:subcat_cat:"))
async def pick_cat_for_sub(cb: types.CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return await cb.answer("Немає доступу", show_alert=True)

    cat = cb.data.split(":", 2)[2]
    await state.update_data(cat=cat)
    await state.set_state(AdminFSM.add_sub_name)
    await cb.message.answer(f"Введіть назву підкатегорії для «{cat}»:")
    await cb.answer()


@router.message(AdminFSM.add_sub_name)
async def add_sub_name(m: types.Message, state: FSMContext):
    if not is_admin(m.from_user.id):
        return await m.answer("⛔️ Немає доступу")

    sub = (m.text or "").strip()
    if not sub:
        return await m.answer("Введіть назву текстом.")

    data = await state.get_data()
    cat = data.get("cat")
    if not cat:
        await state.clear()
        return await m.answer("❌ Помилка стану. Спробуйте ще раз.")

    d = load_data()
    d["categories"].setdefault(cat, {})
    d["categories"][cat].setdefault(sub, [])
    save_data(d)

    await state.clear()
    await m.answer(f"✅ Підкатегорію «{sub}» додано в «{cat}».", reply_markup=admin_menu())


# ---------- ADD PRODUCT ----------

@router.message(F.text == "➕ Додати товар")
async def add_product_btn(m: types.Message, state: FSMContext):
    if not is_admin(m.from_user.id):
        return await m.answer("⛔️ Немає доступу")

    d = load_data()
    if not d["categories"]:
        return await m.answer("Спочатку додайте категорію.")

    await state.clear()
    await state.set_state(AdminFSM.prod_cat)
    await m.answer("Оберіть категорію для товару:", reply_markup=cats_inline_kb("prod_cat"))


@router.callback_query(F.data.startswith("admin:prod_cat:"))
async def prod_pick_cat(cb: types.CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return await cb.answer("Немає доступу", show_alert=True)

    cat = cb.data.split(":", 2)[2]
    d = load_data()
    if not d["categories"].get(cat):
        await cb.answer()
        return await cb.message.answer("У цій категорії нема підкатегорій. Спочатку додайте підкатегорію.")

    await state.update_data(cat=cat)
    await state.set_state(AdminFSM.prod_sub)
    await cb.message.answer("Оберіть підкатегорію:", reply_markup=subs_inline_kb(cat, "prod_sub"))
    await cb.answer()


@router.callback_query(F.data.startswith("admin:prod_sub:"))
async def prod_pick_sub(cb: types.CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return await cb.answer("Немає доступу", show_alert=True)

    _, _, cat, sub = cb.data.split(":")
    await state.update_data(cat=cat, sub=sub)
    await state.set_state(AdminFSM.prod_name)
    await cb.message.answer(f"Введіть назву товару (категорія: {cat} / {sub}):")
    await cb.answer()


@router.message(AdminFSM.prod_name)
async def prod_name(m: types.Message, state: FSMContext):
    if not is_admin(m.from_user.id):
        return await m.answer("⛔️ Немає доступу")

    name = (m.text or "").strip()
    if not name:
        return await m.answer("Введіть назву текстом.")

    await state.update_data(name=name)
    await state.set_state(AdminFSM.prod_price)
    await m.answer("Введіть ціну (число, наприклад 199.99):")


@router.message(AdminFSM.prod_price)
async def prod_price(m: types.Message, state: FSMContext):
    if not is_admin(m.from_user.id):
        return await m.answer("⛔️ Немає доступу")

    t = (m.text or "").replace(",", ".").strip()
    try:
        price = float(t)
    except Exception:
        return await m.answer("❌ Невірна ціна. Введіть число (наприклад 199.99).")

    await state.update_data(price=price)
    await state.set_state(AdminFSM.prod_desc)
    await m.answer("Введіть опис товару (або напишіть '-' щоб пропустити):")


@router.message(AdminFSM.prod_desc)
async def prod_desc(m: types.Message, state: FSMContext):
    if not is_admin(m.from_user.id):
        return await m.answer("⛔️ Немає доступу")

    desc = (m.text or "").strip()
    if desc == "-":
        desc = ""

    await state.update_data(description=desc, photos=[])
    await state.set_state(AdminFSM.prod_photos)
    await m.answer("Надішліть фото товару (можна кілька). Коли закінчите — напишіть: ГОТОВО")


@router.message(AdminFSM.prod_photos, F.photo)
async def prod_photo(m: types.Message, state: FSMContext):
    if not is_admin(m.from_user.id):
        return await m.answer("⛔️ Немає доступу")

    data = await state.get_data()
    photos = data.get("photos", [])
    file_id = m.photo[-1].file_id
    photos.append(file_id)
    await state.update_data(photos=photos)
    await m.answer(f"📸 Фото додано. Ще фото або напишіть: ГОТОВО")


@router.message(AdminFSM.prod_photos)
async def prod_photos_done(m: types.Message, state: FSMContext):
    if not is_admin(m.from_user.id):
        return await m.answer("⛔️ Немає доступу")

    if (m.text or "").strip().lower() not in ("готово", "готов", "done", "ok"):
        return await m.answer("Надішліть фото або напишіть: ГОТОВО")

    st = await state.get_data()
    cat = st["cat"]
    sub = st["sub"]

    d = load_data()
    pid = next_product_id(d)

    product = {
        "id": pid,
        "name": st["name"],
        "price": float(st["price"]),
        "description": st.get("description", ""),
        "photos": st.get("photos", []),
    }

    d["categories"].setdefault(cat, {})
    d["categories"][cat].setdefault(sub, [])
    d["categories"][cat][sub].append(product)
    save_data(d)

    await state.clear()
    await m.answer(f"✅ Товар додано: {product['name']} (ID: {pid})", reply_markup=admin_menu())


# ---------- PRODUCTS LIST / DELETE ----------

@router.message(F.text == "🛠 Товари")
async def products_btn(m: types.Message, state: FSMContext):
    if not is_admin(m.from_user.id):
        return await m.answer("⛔️ Немає доступу")

    d = load_data()
    if not d["categories"]:
        return await m.answer("Каталог порожній.")

    await state.clear()
    # шаг 1: выбрать категорию
    await m.answer("Оберіть категорію:", reply_markup=cats_inline_kb("plist_cat"))


@router.callback_query(F.data.startswith("admin:plist_cat:"))
async def plist_pick_cat(cb: types.CallbackQuery):
    if not is_admin(cb.from_user.id):
        return await cb.answer("Немає доступу", show_alert=True)

    cat = cb.data.split(":", 2)[2]
    d = load_data()
    if not d["categories"].get(cat):
        await cb.answer()
        return await cb.message.answer("У цій категорії немає підкатегорій/товарів.")

    await cb.message.answer("Оберіть підкатегорію:", reply_markup=subs_inline_kb(cat, "plist_sub"))
    await cb.answer()


@router.callback_query(F.data.startswith("admin:plist_sub:"))
async def plist_pick_sub(cb: types.CallbackQuery):
    if not is_admin(cb.from_user.id):
        return await cb.answer("Немає доступу", show_alert=True)

    _, _, cat, sub = cb.data.split(":")
    d = load_data()
    items = d["categories"].get(cat, {}).get(sub, [])
    if not items:
        await cb.answer()
        return await cb.message.answer("У цій підкатегорії немає товарів.")

    lines = [f"• {p['name']} — {p['price']} ₴ (ID {p['id']})" for p in items]
    await cb.message.answer(
        f"<b>{cat}</b> / <b>{sub}</b>\n\n" + "\n".join(lines) + "\n\nНатисніть, щоб видалити:",
        parse_mode="HTML",
        reply_markup=products_inline_kb(cat, sub)
    )
    await cb.answer()


@router.callback_query(F.data.startswith("admin:delprod:"))
async def delete_product(cb: types.CallbackQuery):
    if not is_admin(cb.from_user.id):
        return await cb.answer("Немає доступу", show_alert=True)

    pid = int(cb.data.split(":")[2])
    d = load_data()
    removed = False

    for cat, subs in d["categories"].items():
        for sub, arr in subs.items():
            new_arr = [p for p in arr if p["id"] != pid]
            if len(new_arr) != len(arr):
                d["categories"][cat][sub] = new_arr
                removed = True

    if removed:
        save_data(d)
        await cb.message.answer(f"✅ Товар ID {pid} видалено.")
    else:
        await cb.message.answer("❌ Товар не знайдено.")

    await cb.answer()


# ---------- ADD MANAGER ----------

@router.message(F.text == "👤 Додати менеджера")
async def add_manager_btn(m: types.Message, state: FSMContext):
    if not is_admin(m.from_user.id):
        return await m.answer("⛔️ Немає доступу")
    await state.clear()
    await state.set_state(AdminFSM.add_manager)
    await m.answer("Введіть Telegram ID менеджера (число):")


@router.message(AdminFSM.add_manager)
async def add_manager_id(m: types.Message, state: FSMContext):
    if not is_admin(m.from_user.id):
        return await m.answer("⛔️ Немає доступу")

    t = (m.text or "").strip()
    if not t.isdigit():
        return await m.answer("❌ Потрібно число. Введіть Telegram ID менеджера:")

    uid = int(t)
    d = load_data()
    d.setdefault("managers", [])
    if uid not in d["managers"]:
        d["managers"].append(uid)
        save_data(d)

    await state.clear()
    await m.answer(f"✅ Менеджера додано: {uid}", reply_markup=admin_menu())