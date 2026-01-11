from aiogram import Router, types
from aiogram.filters import Command

from utils import is_admin

router = Router()

def admin_menu():
    return types.ReplyKeyboardMarkup(
        keyboard=[
            ["➕ Додати категорію", "➕ Додати підкатегорію"],
            ["➕ Додати товар", "🛠 Товари"],
            ["👤 Додати менеджера"]
        ],
        resize_keyboard=True
    )

@router.message(Command("admin"))
async def admin_cmd(m: types.Message):
    if not is_admin(m.from_user.id):
        return await m.answer("⛔️ Немає доступу")
    await m.answer("🔧 Адмін-панель", reply_markup=admin_menu())