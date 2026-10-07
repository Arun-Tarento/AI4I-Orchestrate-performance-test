"""Host, service ID and API keys for chat_load.py, read from the environment (or a local .env)."""

import os

from dotenv import load_dotenv

load_dotenv()

HOST = os.environ.get("CHAT_HOST", "")
SERVICE_ID = os.environ.get("SERVICE_ID", "")

_RAW_KEYS = {
    "Admin": os.environ.get("API_KEY_ADMIN", ""),
    "Tenant Admin 1": os.environ.get("API_KEY_TENANT_ADMIN_1", ""),
    "Tenant Admin 2": os.environ.get("API_KEY_TENANT_ADMIN_2", ""),
}

_missing = [name for name, value in {"CHAT_HOST": HOST, "SERVICE_ID": SERVICE_ID}.items() if not value]
_missing += [name for name, key in _RAW_KEYS.items() if not key]
if _missing:
    raise RuntimeError(
        "Set CHAT_HOST, SERVICE_ID and the three API_KEY_* variables (see .env.example). "
        f"Missing: {', '.join(_missing)}"
    )

# Distributed runs: give each worker a different WORKER_INDEX (0, 1, ...) as an inline
# shell variable so their round-robin over the keys doesn't start on the same key.
# Plain OS env var only, not read from .env.
WORKER_INDEX = int(os.environ.get("WORKER_INDEX", 0))

_items = list(_RAW_KEYS.items())
_offset = WORKER_INDEX % len(_items)
API_KEYS = dict(_items[_offset:] + _items[:_offset])
