# keyboards.py

from aiogram import types
from aiogram.utils.keyboard import InlineKeyboardBuilder


def main_menu():
    return types.ReplyKeyboardMarkup(
        keyboard=[
            ["🛍 Каталог", "🧺 Кошик"],
            ["📦 Історія замовлень"]
        ],
        resize_keyboard=True
    )


def admin_menu():
    return types.ReplyKeyboardMarkup(
        keyboard=[
            ["➕ Додати категорію", "➕ Додати підкатегорію"],
            ["➕ Додати товар", "🛠 Товари"],
            ["👤 Додати менеджера"]
        ],
        resize_keyboard=True
    )


def manager_menu():
    return types.ReplyKeyboardMarkup(
        keyboard=[
            ["📋 Нові/оплачені замовлення"],
            ["📦 Усі замовлення"]
        ],
        resize_keyboard=True
    )


def catalog_kb(categories):
    kb = InlineKeyboardBuilder()
    for c in categories:
        kb.button(text=c, callback_data=f"cat:{c}")
    kb.adjust(2)
    return kb.as_markup()


def subcat_kb(cat, subs):
    kb = InlineKeyboardBuilder()
    for s in subs:
        kb.button(text=s, callback_data=f"sub:{cat}:{s}")
    kb.adjust(2)
    return kb.as_markup()


def add_to_cart_kb(pid):
    kb = InlineKeyboardBuilder()
    kb.button(text="🛒 В кошик", callback_data=f"add:{pid}")
    return kb.as_markup()


def cart_kb(total):
    kb = InlineKeyboardBuilder()
    kb.button(text=f"💳 Оформити ({total:.2f} ₴)", callback_data="checkout")
    kb.button(text="🗑 Очистити", callback_data="clear")
    return kb.as_markup()


def pay_kb(oid):
    kb = InlineKeyboardBuilder()
    kb.button(text="💳 Оплатити", callback_data=f"pay:{oid}")
    return kb.as_markup()


def done_kb(oid):
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Виконано", callback_data=f"done:{oid}")
    return kb.as_markup()
