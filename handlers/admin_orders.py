# handlers/admin_orders.py
from aiogram import Router, types, F
from aiogram.filters import Command

router = Router()

@router.message(Command("admin_orders"))
async def admin_orders_ping(m: types.Message):
    await m.answer("✅ admin_orders router працює")