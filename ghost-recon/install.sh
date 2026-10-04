#!/usr/bin/env bash
# ============================================================================
# Ghost Recon on Hermes — installer for the autonomous machine (Linux / macOS / WSL2)
#
# What it does (idempotent):
#   1. Verifies the `hermes` CLI is installed from THIS checkout (fork). If not, prints how.
#   2. Syncs bundled skills (skills/ghost-recon/* -> HERMES_HOME/skills/ghost-recon/*).
#   3. Enables the ghost-recon plugin (python deps consent: openpyxl, reportlab).
#   4. Applies config: web.backend=tavily, delegation limits, plugin settings.
#   5. Installs SOUL.md (Ghost Recon identity) if the home has none.
#   6. Writes TAVILY_API_KEY to .env when passed via --tavily-key or env.
#   7. Initializes the case database and runs the doctor.
#
# Usage:  bash ghost-recon/install.sh [--tavily-key KEY] [--yes] [--no-soul] [--profile NAME]
# ============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TAVILY_KEY="${TAVILY_API_KEY:-}"
ASSUME_YES=false
INSTALL_SOUL=true
PROFILE_ARGS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --tavily-key) TAVILY_KEY="$2"; shift 2 ;;
    --yes|-y) ASSUME_YES=true; shift ;;
    --no-soul) INSTALL_SOUL=false; shift ;;
    --profile|-p) PROFILE_ARGS=(-p "$2"); shift 2 ;;
    -h|--help) sed -n 2,16p "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

say() { printf '\033[0;36m[ghost-recon]\033[0m %s\n' "$*"; }
warn() { printf '\033[0;33m[ghost-recon]\033[0m %s\n' "$*"; }

# 1. hermes CLI --------------------------------------------------------------
if ! command -v hermes >/dev/null 2>&1; then
  if [[ -f "$REPO_ROOT/activate" ]]; then
    warn "hermes not on PATH; activating the checkout's PM environment (source ./activate)"
    # shellcheck disable=SC1091
    source "$REPO_ROOT/activate" || true
  fi
fi
if ! command -v hermes >/dev/null 2>&1; then
  cat >&2 <<EOF
hermes CLI not found. Install Hermes FROM THIS FORK first:
  cd "$REPO_ROOT" && ./setup-hermes.sh && source ./activate
(or follow README.md "Quick Install" and point the installer at this checkout), then re-run this script.
EOF
  exit 1
fi
HERMES=(hermes ${PROFILE_ARGS[@]+"${PROFILE_ARGS[@]}"})   # bash 3.2 (macOS) safe with set -u
HOME_DIR="$("${HERMES[@]}" config path 2>/dev/null | xargs dirname 2>/dev/null || echo "${HERMES_HOME:-$HOME/.hermes}")"
say "Hermes home: $HOME_DIR"

# 2. skills sync -------------------------------------------------------------
say "Seeding bundled skills (skills/ghost-recon) into the home…"
"${HERMES[@]}" skills opt-in --sync || warn "skill seeding reported an error; run: hermes skills opt-in --sync"

# 3. plugin enable -----------------------------------------------------------
say "Enabling plugin ghost-recon (python deps: openpyxl, reportlab)…"
if $ASSUME_YES; then
  printf 'y\ny\ny\n' | "${HERMES[@]}" plugins enable ghost-recon || warn "plugin enable returned non-zero; check: hermes plugins list"
else
  "${HERMES[@]}" plugins enable ghost-recon || warn "plugin enable returned non-zero; check: hermes plugins list"
fi

# 4. config ------------------------------------------------------------------
say "Applying configuration…"
"${HERMES[@]}" config set web.backend tavily >/dev/null || warn "could not set web.backend"
"${HERMES[@]}" config set delegation.max_concurrent_children 10 >/dev/null || true
"${HERMES[@]}" config set delegation.oneshot_max_children 100 >/dev/null || true
"${HERMES[@]}" config set plugins.entries.ghost-recon.settings.audits_dirname GhostRecon_Audits >/dev/null || true
"${HERMES[@]}" config set plugins.entries.ghost-recon.settings.language es >/dev/null || true
"${HERMES[@]}" config set plugins.entries.ghost-recon.settings.base_currency USD >/dev/null || true
"${HERMES[@]}" config set plugins.entries.ghost-recon.settings.swarm_max_parallel 6 >/dev/null || true
"${HERMES[@]}" config set skills.auto_load '[]' >/dev/null 2>&1 || true

# 5. SOUL.md -----------------------------------------------------------------
if $INSTALL_SOUL; then
  if [[ -f "$HOME_DIR/SOUL.md" ]] && ! grep -q "Ghost Recon" "$HOME_DIR/SOUL.md"; then
    cp "$HOME_DIR/SOUL.md" "$HOME_DIR/SOUL.md.bak.$(date +%Y%m%d%H%M%S)"
    warn "existing SOUL.md backed up"
  fi
  cp "$REPO_ROOT/ghost-recon/config/SOUL.md" "$HOME_DIR/SOUL.md"
  say "SOUL.md installed (Ghost Recon identity)"
fi

# 6. secrets -----------------------------------------------------------------
if [[ -n "$TAVILY_KEY" ]]; then
  "${HERMES[@]}" config set TAVILY_API_KEY "$TAVILY_KEY" >/dev/null && say "TAVILY_API_KEY written to .env"
else
  warn "no TAVILY_API_KEY given; research tools stay disabled until you run: hermes config set TAVILY_API_KEY <key>"
fi

# 7. db + doctor -------------------------------------------------------------
say "Initializing case database and running doctor…"
"${HERMES[@]}" ghostrecon init || warn "hermes ghostrecon init failed — is the plugin enabled? (hermes plugins list)"

cat <<EOF

Ghost Recon is ready. Next:
  hermes                                  # start the agent
  /gr-doctor                              # environment check
  /new-open-case <evidence folder> [context.md]
  /rerun-case <evidence folder>
  /review-case <evidence folder>
Docs: ghost-recon/COMMANDS.md · ghost-recon/ARCHITECTURE.md
EOF
