from sqlalchemy import Integer, BigInteger, String
from sqlalchemy.orm import Mapped, mapped_column
from db import Base

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tg_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(64))
    bonus_balance: Mapped[int] = mapped_column(Integer, default=0)