"""Console settings: ``plugins.entries.ghost-recon.settings.console`` in config.yaml, with safe defaults."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Mapping, Optional

LOOPBACK_HOSTS = ("localhost", "127.0.0.1", "::1")


@dataclass(frozen=True)
class ConsoleSettings:
    host: str = "127.0.0.1"
    port: int = 9230
    session_idle_hours: int = 12
    session_max_days: int = 7
    allowed_hosts: tuple = LOOPBACK_HOSTS

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

        extra = raw.get("allowed_hosts")
        hosts = tuple(str(h).strip().lower() for h in extra if str(h).strip()) if isinstance(extra, (list, tuple)) else ()
        return cls(host=str(raw.get("host") or d.host), port=positive_int("port", d.port),
                   session_idle_hours=positive_int("session_idle_hours", d.session_idle_hours),
                   session_max_days=positive_int("session_max_days", d.session_max_days),
                   allowed_hosts=tuple(dict.fromkeys(LOOPBACK_HOSTS + hosts)))


def load_settings(*, host: Optional[str] = None, port: Optional[int] = None) -> ConsoleSettings:
    """The plugin's ``console`` settings (inside Hermes) with CLI overrides applied."""
    from .. import runtime
    settings = ConsoleSettings.from_mapping(runtime.setting("console", {}))
    if host:
        settings = replace(settings, host=host)
    if port:
        settings = replace(settings, port=int(port))
    return settings
