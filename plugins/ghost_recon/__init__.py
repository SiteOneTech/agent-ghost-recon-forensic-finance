"""ghost-recon plugin — Ghost Recon forensic-audit agent on Hermes.

``register(ctx)`` wires: 14 ``gr_*`` tools (toolset ``ghost_recon``), four ``/gr-*`` slash commands, the
``hermes ghostrecon`` CLI, a system-prompt section with the Ghost Recon identity/protocol, and an
``on_session_start`` hook that logs open audits. The orchestration orders (/new-open-case, /rerun-case,
/review-case) are skills under ``skills/ghost-recon/``. Framework-free logic lives in ``core/``.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

__version__ = "0.1.0"


def register(ctx) -> None:
    from . import runtime
    from .commands import COMMANDS
    from .prompts import SYSTEM_SECTION
    from .tools import TOOLS
    from .cli import main as cli_main, register_cli

    runtime.bind_context(ctx)
    for name, schema, handler, emoji in TOOLS:
        ctx.register_tool(name=name, toolset="ghost_recon", schema=schema, handler=handler, emoji=emoji,
                          description=schema.get("description", ""))
    for name, handler, description, hint in COMMANDS:
        ctx.register_command(name, handler, description=description, args_hint=hint)
    ctx.register_cli_command(name="ghostrecon", help="Ghost Recon forensic-audit case administration",
                             setup_fn=register_cli, handler_fn=cli_main,
                             description="Cases, audits, seals and deliverable packs of the Ghost Recon agent.")
    try:
        ctx.register_system_prompt_section("ghost-recon-identity", SYSTEM_SECTION, position="after_memory", max_chars=4000)
    except TypeError:  # older ctx signature without keyword-only args
        ctx.register_system_prompt_section("ghost-recon-identity", SYSTEM_SECTION)
    ctx.register_hook("on_session_start", _on_session_start)
    logger.info("ghost-recon plugin registered (%d tools, %d commands)", len(TOOLS), len(COMMANDS))


def _on_session_start(**kwargs) -> None:
    """Log open (unsealed) audits so an operator reading agent.log sees unfinished work. Never raises."""
    try:
        from . import runtime
        if not runtime.setting("session_reminder", True):
            return
        st = runtime.store()
        open_audits = [a for c in st.list_cases() for a in st.list_audits(c["id"]) if a["status"] != "sealed"]
        if open_audits:
            logger.info("ghost-recon: %d auditoría(s) abierta(s): %s", len(open_audits),
                        ", ".join(f"{a['id']} ({a['folder']})" for a in open_audits[:5]))
    except Exception as exc:  # hooks must never break a session
        logger.debug("ghost-recon on_session_start skipped: %s", exc)
