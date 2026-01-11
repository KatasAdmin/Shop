# states.py

from aiogram.fsm.state import StatesGroup, State


class AdminFSM(StatesGroup):
    # Категории / подкатегории
    add_cat = State()
    add_sub_cat = State()
    add_sub_name = State()

    # Товары (добавление)
    prod_cat = State()
    prod_sub = State()
    prod_name = State()
    prod_price = State()
    prod_desc = State()
    prod_photos = State()

    # Менеджеры
    add_manager = State()


class EditProductFSM(StatesGroup):
    # Редактирование товара
    name = State()
    price = State()
    desc = State()


class OrderFSM(StatesGroup):
    # Оформление заказа (после checkout)
    name = State()              # ФИО/имя
    phone = State()             # телефон (контакт или вручную)
    city = State()              # город
    delivery_method = State()   # способ доставки (НП/курьер)
    delivery_point = State()    # отделение/почтомат или адрес
    comment = State()           # комментарий/примечание