# handlers/__init__.py
from .user import router as user_router
from .admin import router as admin_router

__all__ = ("user_router", "admin_router")