"""Report builders (md / pdf / xlsx) and the pack orchestrator.

The agent writes the narrative (Markdown) and the model (``model.json``); these modules turn them into the
signed, hashed, metadata-clean deliverable set. No number is typed here: tables come from the DB and the model.
"""

FORBIDDEN_TOOL_NAMES = ("claude", "anthropic", "openai", "reportlab", "openpyxl", "pikepdf", "libreoffice",
                        "python-docx", "matplotlib")
