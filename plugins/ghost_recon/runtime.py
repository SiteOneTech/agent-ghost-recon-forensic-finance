"""Hermes-facing runtime glue: DB connection (plugin storage), config, secrets.

Everything here is the ONLY place that touches Hermes internals, and it degrades gracefully when imported
outside Hermes (tests / standalone CLI): the DB falls back to ``GHOSTRECON_DB`` or ``~/.ghostrecon/ghostrecon.db``.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any, Dict, Optional

from .core.db import Store, connect

PLUGIN_NAME = "ghost-recon"
DB_FILENAME = "ghostrecon.db"
_lock = threading.Lock()
_stores: Dict[str, Store] = {}
_ctx = None  # PluginContext when loaded by Hermes

DEFAULTS: Dict[str, Any] = {
    "audits_dirname": "GhostRecon_Audits", "base_currency": "USD", "language": "es",
    "swarm_max_parallel": 6, "swarm_max_files_per_task": 60, "report_formats": ["md", "pdf", "xlsx"],
    "tavily_base_url": "https://api.tavily.com", "session_reminder": True,
}


def bind_context(ctx) -> None:
    global _ctx
    _ctx = ctx


def setting(key: str, default: Any = None) -> Any:
    if _ctx is not None:
        try:
            v = _ctx.get_config(key, None)
            if v is not None:
                return v
        except Exception:
            pass
    env = os.environ.get(f"GHOSTRECON_{key.upper()}")
    if env is not None:
        return env
    return DEFAULTS.get(key, default)


def db_path() -> Path:
    """Where the DB lives: ``GHOSTRECON_DB`` (explicit override, tests) > Hermes plugin-data dir > ~/.ghostrecon."""
    env = os.environ.get("GHOSTRECON_DB")
    if env:
        return Path(env).expanduser()
    try:
        from plugins.plugin_storage import plugin_data_dir
        return plugin_data_dir(PLUGIN_NAME) / DB_FILENAME
    except Exception:
        return Path.home() / ".ghostrecon" / DB_FILENAME


def open_connection():
    """New connection to the profile's Ghost Recon DB: Hermes' ``plugin_db`` inside Hermes (WAL with its
    network-filesystem fallbacks), ``GHOSTRECON_DB`` / the fallback path outside Hermes (tests, standalone)."""
    if not os.environ.get("GHOSTRECON_DB"):
        try:
            from plugins.plugin_storage import plugin_db
            return plugin_db(PLUGIN_NAME, DB_FILENAME)
        except Exception:  # outside Hermes: plugin storage unavailable, use the plain file
            pass
    return connect(db_path())


def store() -> Store:
    """Process-wide Store keyed by DB path (profiles switch the path, so key by it)."""
    path = db_path()
    key = str(path)
    with _lock:
        st = _stores.get(key)
        if st is None:
            st = Store(open_connection())
            _stores[key] = st
        return st


def secret(name: str) -> Optional[str]:
    """Profile-scoped secret. Inside Hermes the answer of ``get_secret`` is final (a miss under multiplexing must
    never fall through to another profile's process env); ``os.environ`` is only for standalone use."""
    try:
        from agent.secret_scope import get_secret
    except Exception:
        return os.environ.get(name) or None
    try:
        return get_secret(name, None) or None
    except Exception:  # UnscopedSecretError and friends: fail closed
        return None


def hermes_home_display() -> str:
    try:
        from hermes_constants import display_hermes_home
        return str(display_hermes_home())
    except Exception:
        return "~/.hermes"
