# services/status_map.py

from typing import Dict, List

# --- Ролі ---
ROLE_ADMIN = "admin"
ROLE_MANAGER = "manager"
ROLE_PACKER = "packer"
ROLE_SYSTEM = "system"   # автоматика (НП, ТСД, вебхук)

# --- Статуси ---
STATUS_FLOW: Dict[str, Dict] = {
    "new": {
        "title": "Нове",
        "emoji": "🆕",
        "roles": [ROLE_SYSTEM],
    },

    "paid": {
        "title": "Оплачено",
        "emoji": "💰",
        "roles": [ROLE_SYSTEM, ROLE_ADMIN],
    },

    "prepay": {
        "title": "Передплата",
        "emoji": "💵",
        "roles": [ROLE_ADMIN],
    },

    "in_work": {
        "title": "В роботі",
        "emoji": "🧑‍💼",
        "roles": [ROLE_MANAGER, ROLE_ADMIN],
    },

    "picking": {
        "title": "Збирається",
        "emoji": "📦",
        "roles": [ROLE_PACKER, ROLE_MANAGER],
    },

    "packed": {
        "title": "Запаковано",
        "emoji": "📦",
        "roles": [ROLE_PACKER],
    },

    "shipped": {
        "title": "Відправлено",
        "emoji": "🚚",
        "roles": [ROLE_MANAGER, ROLE_ADMIN, ROLE_SYSTEM],
        "requires_ttn": True,
    },

    "arrived": {
        "title": "Прибуло у відділення",
        "emoji": "🏬",
        "roles": [ROLE_SYSTEM],
    },

    "picked": {
        "title": "Отримано",
        "emoji": "✅",
        "roles": [ROLE_MANAGER, ROLE_ADMIN],
    },

    "returned": {
        "title": "Повернуто",
        "emoji": "↩️",
        "roles": [ROLE_MANAGER, ROLE_ADMIN],
    },

    "canceled": {
        "title": "Скасовано",
        "emoji": "❌",
        "roles": [ROLE_ADMIN],
    },
}


# --- helpers ---

def status_exists(code: str) -> bool:
    return code in STATUS_FLOW


def can_set_status(code: str, role: str) -> bool:
    cfg = STATUS_FLOW.get(code)
    if not cfg:
        return False
    return role in cfg.get("roles", [])


def status_title(code: str) -> str:
    return STATUS_FLOW.get(code, {}).get("title", "В обробці")


def status_emoji(code: str) -> str:
    return STATUS_FLOW.get(code, {}).get("emoji", "📦")


def requires_ttn(code: str) -> bool:
    return STATUS_FLOW.get(code, {}).get("requires_ttn", False)