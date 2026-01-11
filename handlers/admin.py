from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder

from data import load_data, save_data
from utils import is_staff, is_admin, format_order_text

router = Router()


def admin_menu(uid: int) -> types.ReplyKeyboardMarkup:
    keyboard = [
        ["➕ Категорія", "➕ Товар"],
        ["🛠 Товари"],
        ["📋 Нові", "📦 Усі"],
    ]

    if is_admin(uid):
        keyboard.append(["👤 Додати менеджера"])

    keyboard.append(["❌ Відміна"])

    return types.ReplyKeyboardMarkup(
        keyboard=[[types.KeyboardButton(text=b) for b in row] for row in keyboard],
        resize_keyboard=True
    )


@router.message(Command("admin"))
async def admin_cmd(m: types.Message, state: FSMContext):
    data = load_data()
    if not is_staff(data, m.from_user.id):
        return await m.answer("⛔️ Немає доступу")

    await state.clear()
    await m.answer("🔧 Панель керування", reply_markup=admin_menu(m.from_user.id))


@router.message(F.text == "📋 Нові")
async def new_orders(m: types.Message):
    data = load_data()
    if not is_staff(data, m.from_user.id):
        return

    orders = [o for o in data["orders"] if o["status"] == "paid"]
    if not orders:
        return await m.answer("Немає нових замовлень")

    for o in orders:
        kb = InlineKeyboardBuilder()
        kb.button(text="🔄 В роботу", callback_data=f"order:work:{o['id']}")
        await m.answer(format_order_text(data, o), reply_markup=kb.as_markup())


@router.callback_query(F.data.startswith("order:work:"))
async def take_order(cb: types.CallbackQuery):
    data = load_data()
    oid = int(cb.data.split(":")[2])

    for o in data["orders"]:
        if o["id"] == oid:
            o["status"] = "in_work"

    save_data(data)
    await cb.message.answer("🔄 Замовлення в роботі")
    await cb.answer()


@router.message(F.text == "📦 Усі")
async def all_orders(m: types.Message):
    data = load_data()
    if not is_staff(data, m.from_user.id):
        return

    for o in reversed(data["orders"]):
        kb = None
        if o["status"] != "done":
            kb = InlineKeyboardBuilder()
            kb.button(text="✅ Завершити", callback_data=f"order:done:{o['id']}")
            kb = kb.as_markup()

        await m.answer(format_order_text(data, o), reply_markup=kb)


@router.callback_query(F.data.startswith("order:done:"))
async def done_order(cb: types.CallbackQuery):
    data = load_data()
    oid = int(cb.data.split(":")[2])

    for o in data["orders"]:
        if o["id"] == oid:
            o["status"] = "done"

    save_data(data)
    await cb.message.answer("✅ Замовлення виконано")
    await cb.answer()