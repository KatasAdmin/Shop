from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder

from data import load_data, save_data
from utils import is_manager, format_order_text

router = Router()


def manager_menu() -> types.ReplyKeyboardMarkup:
    return types.ReplyKeyboardMarkup(
        keyboard=[
            [types.KeyboardButton(text="📋 Нові (оплачені)")],
            [types.KeyboardButton(text="📦 Усі замовлення")],
        ],
        resize_keyboard=True
    )


def order_actions_kb(order_id: int):
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Завершити", callback_data=f"mgr:done:{order_id}")
    return kb.as_markup()


@router.message(Command("manager"))
async def manager_cmd(m: types.Message):
    if not is_manager(load_data(), m.from_user.id):
        return await m.answer("⛔️ Немає доступу")
    await m.answer("👔 Менеджер", reply_markup=manager_menu())


@router.message(F.text == "📋 Нові (оплачені)")
async def new_orders(m: types.Message):
    d = load_data()
    if not is_manager(d, m.from_user.id):
        return await m.answer("⛔️ Немає доступу")

    orders = [o for o in d["orders"] if o.get("status") == "paid"]
    if not orders:
        return await m.answer("Немає нових оплачених замовлень.")

    for o in orders:
        await m.answer(
            format_order_text(d, o),
            reply_markup=order_actions_kb(o["id"])
        )


@router.message(F.text == "📦 Усі замовлення")
async def all_orders(m: types.Message):
    d = load_data()
    if not is_manager(d, m.from_user.id):
        return await m.answer("⛔️ Немає доступу")

    if not d["orders"]:
        return await m.answer("Замовлень ще немає.")

    for o in reversed(d["orders"]):
        await m.answer(
            format_order_text(d, o),
            reply_markup=order_actions_kb(o["id"]) if o.get("status") != "done" else None
        )


@router.callback_query(F.data.startswith("mgr:done:"))
async def mark_done(cb: types.CallbackQuery):
    d = load_data()
    if not is_manager(d, cb.from_user.id):
        return await cb.answer("Немає доступу", show_alert=True)

    oid = int(cb.data.split(":")[2])
    found = False
    for o in d["orders"]:
        if o["id"] == oid:
            o["status"] = "done"
            found = True
            break

    if found:
        save_data(d)
        await cb.message.answer(f"✅ Замовлення #{oid} завершено.")
    else:
        await cb.message.answer("❌ Замовлення не знайдено.")

    await cb.answer()