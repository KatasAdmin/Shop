# middlewares/debug.py
from __future__ import annotations

import time
import traceback
from typing import Any, Dict

from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery


def _mask(text: str) -> str:
    """
    Мінімальна маска: ховаємо довгі послідовності цифр (телефони/ТТН)
    щоб не світити приватні дані в логах.
    """
    if not text:
        return ""
    out = []
    digits_run = 0
    for ch in text:
        if ch.isdigit():
            digits_run += 1
            # показуємо тільки перші 2 цифри, решту маскуємо
            out.append(ch if digits_run <= 2 else "•")
        else:
            digits_run = 0
            out.append(ch)
    return "".join(out)


class DebugMiddleware(BaseMiddleware):
    def __init__(self, enabled: bool = True):
        self.enabled = enabled

    async def __call__(self, handler, event, data: Dict[str, Any]):
        if not self.enabled:
            return await handler(event, data)

        t0 = time.time()

        try:
            # --- INPUT LOG ---
            if isinstance(event, CallbackQuery):
                uid = event.from_user.id if event.from_user else None
                cd = event.data or ""
                print(f"[DBG] CB  uid={uid} data={_mask(cd)}")

            elif isinstance(event, Message):
                uid = event.from_user.id if event.from_user else None
                txt = event.text or event.caption or ""
                # маскуємо
                txt_m = _mask(txt)
                if txt_m:
                    print(f"[DBG] MSG uid={uid} text={txt_m[:200]}")
                else:
                    print(f"[DBG] MSG uid={uid} (non-text msg)")

            # --- RUN HANDLER ---
            res = await handler(event, data)

            # --- OK LOG ---
            dt = int((time.time() - t0) * 1000)
            print(f"[DBG] OK  {dt}ms")
            return res

        except Exception as e:
            dt = int((time.time() - t0) * 1000)
            print(f"[DBG] ERR {dt}ms {type(e).__name__}: {e}")
            print(traceback.format_exc())
            raise