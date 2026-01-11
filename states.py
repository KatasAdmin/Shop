# states.py
from aiogram.fsm.state import StatesGroup, State


class AdminFSM(StatesGroup):
    add_cat = State()
    add_sub_cat = State()
    add_sub_name = State()

    prod_cat = State()
    prod_sub = State()
    prod_name = State()
    prod_price = State()
    prod_desc = State()
    prod_photos = State()

    add_manager = State()


class EditProductFSM(StatesGroup):
    name = State()
    price = State()
    desc = State()


class OrderFSM(StatesGroup):
    name = State()
    phone = State()
    city = State()
    np_branch = State()
    comment = State()