from .user import router as user_router
from .admin import router as admin_router
from .admin_orders import router as admin_orders_router

__all__ = ("user_router", "admin_router", "admin_orders_router")

# новий модуль замовлень (додасться коли файл точно буде на місці)
try:
    from .admin_orders import router as admin_orders_router
except Exception:
    admin_orders_router = None

__all__ = ["user_router", "admin_router", "admin_orders_router"]