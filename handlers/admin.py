# handlers/admin.py

from aiogram import Router, types, F
from aiogram.filters import Command

from utils import is_admin

router = Router()


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


@router.message(Command("admin"))
async def admin_cmd(m: types.Message):
    if not is_admin(m.from_user.id):
        return await m.answer("⛔️ Немає доступу")
    await m.answer("🔧 Адмін-панель", reply_markup=admin_menu())


# ====== handlers for кнопок (чтобы реагировали) ======

@router.message(F.text == "➕ Додати категорію")
async def add_category_btn(m: types.Message):
    if not is_admin(m.from_user.id):
        return await m.answer("⛔️ Немає доступу")
    await m.answer("ОК: натиснуто «Додати категорію». (Тут буде логіка додавання)")


@router.message(F.text == "➕ Додати підкатегорію")
async def add_subcategory_btn(m: types.Message):
    if not is_admin(m.from_user.id):
        return await m.answer("⛔️ Немає доступу")
    await m.answer("ОК: натиснуто «Додати підкатегорію». (Тут буде логіка додавання)")


@router.message(F.text == "➕ Додати товар")
async def add_product_btn(m: types.Message):
    if not is_admin(m.from_user.id):
        return await m.answer("⛔️ Немає доступу")
    await m.answer("ОК: натиснуто «Додати товар». (Тут буде логіка додавання)")


@router.message(F.text == "🛠 Товари")
async def products_btn(m: types.Message):
    if not is_admin(m.from_user.id):
        return await m.answer("⛔️ Немає доступу")
    await m.answer("ОК: натиснуто «Товари». (Тут буде список/редагування)")


@router.message(F.text == "👤 Додати менеджера")
async def add_manager_btn(m: types.Message):
    if not is_admin(m.from_user.id):
        return await m.answer("⛔️ Немає доступу")
    await m.answer("ОК: натиснуто «Додати менеджера». (Тут буде логіка додавання)")