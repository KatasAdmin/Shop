# init_db.py
from db import engine, Base
import models  # важливо: щоб моделі підвантажились


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)