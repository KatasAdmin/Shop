# handlers/manager.py

from aiogram import Router, types
from aiogram.filters import Command

from data import load_data
from utils import is_manager

router = Router()


def manager_menu() -> types.ReplyKeyboardMarkup:
    return types.ReplyKeyboardMarkup(
        keyboard=[
            [types.KeyboardButton(text="📋 Нові замовлення")],
            [types.KeyboardButton(text="📦 Усі замовлення")],
        ],
        resize_keyboard=True
    )


@router.message(Command("manager"))
async def manager_cmd(m: types.Message):
    if not is_manager(load_data(), m.from_user.id):
        return await m.answer("⛔️ Немає доступу")
    await m.answer("👔 Менеджер", reply_markup=manager_menu())