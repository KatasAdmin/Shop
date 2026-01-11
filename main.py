import asyncio
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from config import BOT_TOKEN
from handlers import user_router, admin_router
from github_sync import pull_data_if_possible, start_periodic_sync

async def main():
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())

    # 🔹 1. ЗАВАНТАЖУЄМО ДАНІ З GITHUB
    await pull_data_if_possible()

    dp.include_router(user_router)
    dp.include_router(admin_router)

    # 🔹 2. ФОНОВИЙ PUSH В GITHUB
    asyncio.create_task(start_periodic_sync())

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())