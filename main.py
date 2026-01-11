import asyncio
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from config import BOT_TOKEN
from handlers import user_router, admin_router

from sync_github import pull_data_if_possible, start_periodic_sync
from data import load_data, save_data


async def main():
    # 1) Підтягуємо data.json з GitHub на старті (якщо є)
    remote = pull_data_if_possible()
    if remote:
        save_data(remote)

    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())

    dp.include_router(user_router)
    dp.include_router(admin_router)

    # 2) Запускаємо періодичний пуш в GitHub
    start_periodic_sync(load_data)

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())