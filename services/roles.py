# services/roles.py

from typing import Dict, Any, Set

ROLE_ADMIN = "admin"
ROLE_MANAGER = "manager"
ROLE_PACKER = "packer"

ALL_ROLES = {ROLE_ADMIN, ROLE_MANAGER, ROLE_PACKER}

# які дії дозволені пакувальнику (мінімально необхідне)
PACKER_STATUSES = {"picked", "packing", "packed"}

# менеджер може все по замовленню (крім додавання менеджерів)
MANAGER_STATUSES = {
    "in_work", "picked", "packing", "packed",
    "shipped", "sent",
    "received", "done",
    "returned", "not_picked", "canceled",
}


def get_user_role(data: Dict[str, Any], uid: int) -> str:
    """
    Поки що: admin = ADMIN_ID, manager = в managers, packer = в packers
    """
    admin_id = int(data.get("ADMIN_ID", 0) or 0)  # запасний, якщо захочеш
    # ТИ використовуєш config.ADMIN_ID у utils — тому тут просто “логіка”
    # реальну перевірку admin краще робити через utils.is_admin()

    # packers
    packers: Set[int] = set(int(x) for x in (data.get("packers", []) or []))
    managers: Set[int] = set(int(x) for x in (data.get("managers", []) or []))

    if uid in packers:
        return ROLE_PACKER
    if uid in managers:
        return ROLE_MANAGER
    return "guest"