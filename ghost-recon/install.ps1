# ============================================================================
# Ghost Recon on Hermes — installer for native Windows (PowerShell)
# Mirrors install.sh: skills sync, plugin enable, config, SOUL.md, TAVILY key, DB init, doctor.
# Usage:  powershell -ExecutionPolicy Bypass -File ghost-recon\install.ps1 [-TavilyKey KEY] [-Yes] [-NoSoul] [-Profile NAME]
# ============================================================================
param(
  [string]$TavilyKey = $env:TAVILY_API_KEY,
  [switch]$Yes,
  [switch]$NoSoul,
  [string]$Profile = ""
)
$ErrorActionPreference = "Continue"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
function Say($m) { Write-Host "[ghost-recon] $m" -ForegroundColor Cyan }
function Warn($m) { Write-Host "[ghost-recon] $m" -ForegroundColor Yellow }

$hermes = Get-Command hermes -ErrorAction SilentlyContinue
if (-not $hermes) {
  if (Test-Path (Join-Path $RepoRoot "activate.ps1")) {
    Warn "hermes not on PATH; activating the checkout's PM environment"
    . (Join-Path $RepoRoot "activate.ps1")
    $hermes = Get-Command hermes -ErrorAction SilentlyContinue
  }
}
if (-not $hermes) {
  Write-Error "hermes CLI not found. Install Hermes from this fork first: cd $RepoRoot; .\setup-hermes.ps1; . .\activate.ps1 — then re-run."
  exit 1
}
$P = @(); if ($Profile) { $P = @("-p", $Profile) }
$HomeDir = (& hermes @P config path 2>$null | Split-Path -Parent)
if (-not $HomeDir) { $HomeDir = if ($env:HERMES_HOME) { $env:HERMES_HOME } else { Join-Path $env:LOCALAPPDATA "hermes" } }
Say "Hermes home: $HomeDir"

Say "Seeding bundled skills (skills\ghost-recon) into the home…"
& hermes @P skills opt-in --sync

Say "Enabling plugin ghost-recon (python deps: openpyxl, reportlab)…"
if ($Yes) { "y`ny`ny`n" | & hermes @P plugins enable ghost-recon } else { & hermes @P plugins enable ghost-recon }

Say "Applying configuration…"
& hermes @P config set web.backend tavily | Out-Null
& hermes @P config set delegation.max_concurrent_children 10 | Out-Null
& hermes @P config set delegation.max_concurrent_children 10 | Out-Null hermes @P config set delegation.oneshot_max_children 100 | Out-Null
& hermes @P config set plugins.entries.ghost-recon.settings.audits_dirname GhostRecon_Audits | Out-Null
& hermes @P config set plugins.entries.ghost-recon.settings.language es | Out-Null
& hermes @P config set plugins.entries.ghost-recon.settings.base_currency USD | Out-Null
& hermes @P config set plugins.entries.ghost-recon.settings.swarm_max_parallel 6 | Out-Null

if (-not $NoSoul) {
  $soul = Join-Path $HomeDir "SOUL.md"
  if ((Test-Path $soul) -and -not (Select-String -Path $soul -Pattern "Ghost Recon" -Quiet)) {
    Copy-Item $soul "$soul.bak.$(Get-Date -Format yyyyMMddHHmmss)"; Warn "existing SOUL.md backed up"
  }
  Copy-Item (Join-Path $RepoRoot "ghost-recon\config\SOUL.md") $soul -Force
  Say "SOUL.md installed (Ghost Recon identity)"
}

if ($TavilyKey) { & hermes @P config set TAVILY_API_KEY $TavilyKey | Out-Null; Say "TAVILY_API_KEY written to .env" }
else { Warn "no TAVILY_API_KEY given; run: hermes config set TAVILY_API_KEY <key>" }

Say "Initializing case database and running doctor…"
& hermes @P ghostrecon init

Write-Host ""
Write-Host "Ghost Recon is ready. Next: hermes  ->  /gr-doctor  ->  /new-open-case <evidence folder> [context.md]"
Write-Host "Docs: ghost-recon\COMMANDS.md · ghost-recon\ARCHITECTURE.md"
