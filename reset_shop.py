import asyncio

from sqlalchemy import delete, select

from db import session_scope
from models import KVStore
from config import SHOP_STATE_KEY
from data import default_data


async def reset():
    print("SHOP_STATE_KEY =", SHOP_STATE_KEY)

    async with session_scope() as session:
        # 1) перевіримо що є в базі
        row = await session.scalar(select(KVStore).where(KVStore.key == SHOP_STATE_KEY))
        if not row:
            print("⚠️ Рядок KVStore з таким ключем НЕ знайдено. Створюю новий.")
        else:
            try:
                keys = list((row.value or {}).keys())
            except Exception:
                keys = []
            print("✅ Знайшов рядок. Поточні ключі value:", keys)

        # 2) ЖОРСТКО: видалити по ключу
        await session.execute(delete(KVStore).where(KVStore.key == SHOP_STATE_KEY))

        # 3) створити заново з default_data()
        session.add(KVStore(key=SHOP_STATE_KEY, value=default_data()))

        # 4) commit (на всяк)
        await session.commit()

        # 5) контрольна перевірка
        row2 = await session.scalar(select(KVStore).where(KVStore.key == SHOP_STATE_KEY))
        if row2:
            try:
                keys2 = list((row2.value or {}).keys())
            except Exception:
                keys2 = []
            print("🎉 ГОТОВО. Нові ключі value:", keys2)
        else:
            print("❌ Після reset рядок не створився — значить проблема з БД/моделлю.")


if __name__ == "__main__":
    asyncio.run(reset())