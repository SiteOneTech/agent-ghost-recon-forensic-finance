"""Console settings: ``plugins.entries.ghost-recon.settings.console`` in config.yaml, with safe defaults."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Mapping, Optional, Tuple

LOOPBACK_HOSTS = ("localhost", "127.0.0.1", "::1")


def _str_list(value: Any) -> Tuple[str, ...]:
    """Non-empty, stripped, de-duplicated strings of a YAML list; anything else is an empty tuple."""
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(dict.fromkeys(str(v).strip() for v in value if str(v).strip()))


def _http_url(value: Any) -> str:
    """An http(s) base URL without its trailing slash, or "" (the console only ever links http(s))."""
    text = str(value or "").strip()
    return text.rstrip("/") if text.lower().startswith(("http://", "https://")) else ""


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

    @classmethod
    def from_mapping(cls, raw: Any) -> "ConsoleSettings":
        """Tolerant parse: unknown keys are ignored, invalid or non-positive numbers fall back to the default."""
        raw = raw if isinstance(raw, Mapping) else {}
        d = cls()

        def positive_int(key: str, default: int) -> int:
            try:
                value = int(raw.get(key, default))
            except (TypeError, ValueError):
                return default
            return value if value > 0 else default

        hosts = tuple(h.lower() for h in _str_list(raw.get("allowed_hosts")))
        return cls(host=str(raw.get("host") or d.host), port=positive_int("port", d.port),
                   session_idle_hours=positive_int("session_idle_hours", d.session_idle_hours),
                   session_max_days=positive_int("session_max_days", d.session_max_days),
                   allowed_hosts=tuple(dict.fromkeys(LOOPBACK_HOSTS + hosts)),
                   case_roots=_str_list(raw.get("case_roots")),
                   max_parallel_jobs=positive_int("max_parallel_jobs", d.max_parallel_jobs),
                   dashboard_url=_http_url(raw.get("dashboard_url")))


def load_settings(*, host: Optional[str] = None, port: Optional[int] = None) -> ConsoleSettings:
    """The plugin's ``console`` settings (inside Hermes) with CLI overrides applied."""
    from .. import runtime
    settings = ConsoleSettings.from_mapping(runtime.setting("console", {}))
    if host:
        settings = replace(settings, host=host)
    if port:
        settings = replace(settings, port=int(port))
    return settings
