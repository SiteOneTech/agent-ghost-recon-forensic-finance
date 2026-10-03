"""Ghost Recon console: a standalone web console (``hermes ghostrecon serve``) over the case DB.

Spec: ghost-recon/specs/2026-10-02-ghost-recon-console-design.md. The console reads case data through ``core`` and
writes only its own ``console_*`` tables; it never edits findings, criteria or sealed audits.
"""

CONSOLE_VERSION = "0.1.0"
