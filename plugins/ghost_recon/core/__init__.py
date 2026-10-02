"""Ghost Recon core — framework-independent logic (no Hermes imports).

Modules:
    db          SQLite schema + Store (cases, audits, evidence, findings, criteria, reports, runs, timeline, research)
    ids         id generation (case / audit / review / finding series)
    casefolder  case folder layout, inventory + hashes (incl. ZIP members), dedupe, sealing, case.json mirror
    swarm       deterministic swarm plans (extraction / validation / review) -> manifests + delegate_task tasks
    research    Tavily REST client (search / extract / crawl / map / research)
    review      consolidated case chronology + role plan for /review-case
    reports     md / pdf / xlsx builders + pack orchestration

Everything here is testable with plain pytest; the Hermes-facing layer lives one directory up.
"""

__version__ = "0.1.0"
SIGNATURE = "Ghost Recon · Sistema de auditoría forense asistida por IA · https://www.ghostrecon.ai/"
SIGNATURE_SHORT = "Generado por Ghost Recon · www.ghostrecon.ai"
ENGINE = "Ghost Recon Audit Engine"
