# main.py
import asyncio
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from config import BOT_TOKEN
from handlers import user_router, admin_router
from init_db import init_db

from middlewares.debug import DebugMiddleware


async def main():
    await init_db()

    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())

    # ✅ Ловимо помилки і показуємо їх “людською” (або шлемо в адмін-чат)
    dp.update.middleware(DebugMiddleware(enabled=True))

    dp.include_router(user_router)
    dp.include_router(admin_router)

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())