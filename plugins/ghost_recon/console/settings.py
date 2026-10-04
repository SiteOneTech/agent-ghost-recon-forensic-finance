"""Console settings: ``plugins.entries.ghost-recon.settings.console`` in config.yaml, with safe defaults."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Any, Mapping, Optional, Tuple

LOOPBACK_HOSTS = ("localhost", "127.0.0.1", "::1")
# ``hermes send --to`` targets: a platform name, then optional ``:chat[:thread]`` / ``:#channel`` parts. A leading
# letter keeps the value from ever reading as a flag on the send command line.
NOTIFY_TARGET_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]*(?::\S+)?")
NOTIFY_TARGET_MAX = 200
_TRUE = ("true", "yes", "on", "1")
_FALSE = ("false", "no", "off", "0")


def _str_list(value: Any) -> Tuple[str, ...]:
    """Non-empty, stripped, de-duplicated strings of a YAML list; anything else is an empty tuple."""
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(dict.fromkeys(str(v).strip() for v in value if str(v).strip()))


def _http_url(value: Any) -> str:
    """An http(s) base URL without its trailing slash, or "" (the console only ever links http(s))."""
    text = str(value or "").strip()
    return text.rstrip("/") if text.lower().startswith(("http://", "https://")) else ""


def _positive(value: Any, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return number if number > 0 else default


def _flag(value: Any, default: bool) -> bool:
    """A YAML boolean, or its usual spellings as text (``hermes config set`` may store "true")."""
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower() if value is not None else ""
    return True if text in _TRUE else False if text in _FALSE else default


def _notify_target(value: Any) -> str:
    """A ``hermes send --to`` target, or "" (no notice) when absent or malformed."""
    text = str(value or "").strip()
    return text if len(text) <= NOTIFY_TARGET_MAX and NOTIFY_TARGET_RE.fullmatch(text) else ""


@dataclass(frozen=True)
class ConsoleSettings:
    host: str = "127.0.0.1"
    port: int = 9230
    session_idle_hours: int = 12
    session_max_days: int = 7
    allowed_hosts: tuple = LOOPBACK_HOSTS
    case_roots: tuple = ()
    max_parallel_jobs: int = 2
    dashboard_url: str = ""
    notify_target: str = ""
    export_include_unsealed: bool = False
    export_retention_count: int = 20
    export_retention_days: int = 30

    @classmethod
    def from_mapping(cls, raw: Any) -> "ConsoleSettings":
        """Tolerant parse: unknown keys are ignored, invalid or non-positive numbers fall back to the default."""
        raw = raw if isinstance(raw, Mapping) else {}
        d = cls()
        retention = raw.get("export_retention")
        retention = retention if isinstance(retention, Mapping) else {}
        hosts = tuple(h.lower() for h in _str_list(raw.get("allowed_hosts")))
        return cls(host=str(raw.get("host") or d.host), port=_positive(raw.get("port", d.port), d.port),
                   session_idle_hours=_positive(raw.get("session_idle_hours", d.session_idle_hours),
                                                d.session_idle_hours),
                   session_max_days=_positive(raw.get("session_max_days", d.session_max_days), d.session_max_days),
                   allowed_hosts=tuple(dict.fromkeys(LOOPBACK_HOSTS + hosts)),
                   case_roots=_str_list(raw.get("case_roots")),
                   max_parallel_jobs=_positive(raw.get("max_parallel_jobs", d.max_parallel_jobs),
                                               d.max_parallel_jobs),
                   dashboard_url=_http_url(raw.get("dashboard_url")),
                   notify_target=_notify_target(raw.get("notify_target")),
                   export_include_unsealed=_flag(raw.get("export_include_unsealed"), d.export_include_unsealed),
                   export_retention_count=_positive(retention.get("count", d.export_retention_count),
                                                    d.export_retention_count),
                   export_retention_days=_positive(retention.get("days", d.export_retention_days),
                                                   d.export_retention_days))


def load_settings(*, host: Optional[str] = None, port: Optional[int] = None) -> ConsoleSettings:
    """The plugin's ``console`` settings (inside Hermes) with CLI overrides applied."""
    from .. import runtime
    settings = ConsoleSettings.from_mapping(runtime.setting("console", {}))
    if host:
        settings = replace(settings, host=host)
    if port:
        settings = replace(settings, port=int(port))
    return settings
