# middlewares/debug.py
import traceback
import logging

from aiogram import BaseMiddleware
from aiogram.types import Update


log = logging.getLogger(__name__)


class DebugMiddleware(BaseMiddleware):
    def __init__(self, enabled: bool = True):
        self.enabled = enabled

    async def __call__(self, handler, event: Update, data):
        try:
            return await handler(event, data)

        except Exception as e:
            tb = traceback.format_exc()

            log.error("🔥 BOT ERROR:\n%s", tb)

            if not self.enabled:
                raise

            # --- Людське пояснення ---
            human = self._human_message(e)

            # якщо є message — відповімо користувачу
            msg = data.get("event_message") or getattr(event, "message", None)
            if msg:
                try:
                    await msg.answer(
                        "⚠️ Сталася внутрішня помилка.\n\n"
                        f"{human}\n\n"
                        "Ми вже знаємо про проблему 👨‍💻"
                    )
                except Exception:
                    pass

            # ❗ НЕ валимо бота
            return None

    def _human_message(self, e: Exception) -> str:
        text = str(e)

        if isinstance(e, AttributeError):
            return "Система очікувала обʼєкт, але отримала інше значення."

        if isinstance(e, KeyError):
            return "Відсутні необхідні дані. Можливо, старий формат збережених даних."

        if isinstance(e, TypeError):
            return "Неправильний тип даних. Дані виглядають пошкодженими."

        if "int has no attribute get" in text:
            return "В одному з місць товар або замовлення збережене в старому форматі."

        return "Технічна помилка. Деталі вже зафіксовано."