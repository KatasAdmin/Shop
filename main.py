# main.py
import asyncio

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from config import BOT_TOKEN
from handlers import user_router, admin_router
from init_db import init_db


async def main():
    # 1) Ініціалізація БД (створить таблиці, якщо їх ще нема)
    await init_db()

    # 2) Запуск бота
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())

    dp.include_router(user_router)
    dp.include_router(admin_router)

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())