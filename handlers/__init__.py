# handlers/__init__.py
from .user import router as user_router
from .admin import router as admin_router
from .admin_orders import router as admin_orders_router

__all__ = ("user_router", "admin_router", "admin_orders_router")