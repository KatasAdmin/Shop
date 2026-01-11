# states.py

from aiogram.fsm.state import StatesGroup, State


class AdminFSM(StatesGroup):
    add_category = State()

    add_subcat_category = State()
    add_subcat_name = State()

    add_product_category = State()
    add_product_subcategory = State()
    add_product_name = State()
    add_product_price = State()
    add_product_description = State()
    add_product_photos = State()

    add_manager = State()


class EditProductFSM(StatesGroup):
    name = State()
    price = State()
    description = State()
