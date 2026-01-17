import asyncio
from db import session_scope
from models import KVStore
from config import SHOP_STATE_KEY
from data import default_data


async def reset():
    async with session_scope() as session:
        row = await session.get(KVStore, SHOP_STATE_KEY)
        if row:
            row.value = default_data()
            await session.commit()
            print("✅ Дані магазину ПОВНІСТЮ очищено")


if __name__ == "__main__":
    asyncio.run(reset())