<#
.SYNOPSIS
  One-step setup and launch on Windows: installs uv and Grafana if missing,
  installs the SQLite data source plugin, builds the database from the PDFs in
  statements\, and starts Grafana with this project's dashboards.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\bootstrap.ps1
  powershell -ExecutionPolicy Bypass -File .\bootstrap.ps1 -Port 3001
  powershell -ExecutionPolicy Bypass -File .\bootstrap.ps1 -NoStart     # set up and rebuild data only

.NOTES
  Safe to re-run: every step is skipped when already done. Nothing is installed
  as a service; Grafana runs in this window until you press Ctrl+C.
#>
param(
    [int]$Port = 3000,
    [string]$GrafanaHome = $env:GRAFANA_HOME,   # folder that contains bin\ and conf\
    [switch]$NoStart
)

$ErrorActionPreference = 'Stop'
$Root = $PSScriptRoot
Set-Location $Root

function Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Refresh-Path {
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
                [Environment]::GetEnvironmentVariable('Path', 'User') + ';' +
                "$env:USERPROFILE\.local\bin"
}
function Has($cmd) { [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }

# ---------------------------------------------------------------- uv (Python)
Step 'Checking uv (Python package runner)'
if (-not (Has uv)) {
    if (Has winget) {
        winget install --id astral-sh.uv -e --accept-source-agreements --accept-package-agreements
    } else {
        Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
    }
    Refresh-Path
    if (-not (Has uv)) { throw 'uv was installed but is not on PATH yet. Open a new PowerShell window and run this script again.' }
}
uv --version

# ------------------------------------------------------------------- Grafana
Step 'Checking Grafana'
function Find-GrafanaHome {
    $candidates = @(
        $GrafanaHome,
        "$env:ProgramFiles\GrafanaLabs\grafana",
        "${env:ProgramFiles(x86)}\GrafanaLabs\grafana",
        "$env:LOCALAPPDATA\Programs\GrafanaLabs\grafana"
    ) | Where-Object { $_ }
    foreach ($c in $candidates) {
        if ((Test-Path "$c\bin\grafana.exe") -or (Test-Path "$c\bin\grafana-server.exe")) { return $c }
    }
    return $null
}
$GrafanaHome = Find-GrafanaHome
if (-not $GrafanaHome) {
    if (-not (Has winget)) {
        throw 'Grafana not found and winget is unavailable. Install Grafana OSS from https://grafana.com/grafana/download?platform=windows and re-run, or pass -GrafanaHome <folder>.'
    }
    Write-Host 'Installing Grafana OSS with winget (Windows may ask for permission)...'
    winget install --id GrafanaLabs.Grafana.OSS -e --accept-source-agreements --accept-package-agreements
    $GrafanaHome = Find-GrafanaHome
    if (-not $GrafanaHome) { throw 'Grafana was installed but could not be located. Re-run with -GrafanaHome <folder containing bin\ and conf\>.' }
}
Write-Host "Grafana home: $GrafanaHome"

# Newer builds ship one grafana.exe with subcommands; older ones ship separate tools.
if (Test-Path "$GrafanaHome\bin\grafana.exe") {
    $ServerExe = "$GrafanaHome\bin\grafana.exe"; $ServerArgs = @('server')
    $CliExe = "$GrafanaHome\bin\grafana.exe";    $CliArgs = @('cli')
} else {
    $ServerExe = "$GrafanaHome\bin\grafana-server.exe"; $ServerArgs = @()
    $CliExe = "$GrafanaHome\bin\grafana-cli.exe";       $CliArgs = @()
}

# --------------------------------------------------------- SQLite data source
$Runtime = Join-Path $Root 'grafana\runtime'
$Plugins = Join-Path $Runtime 'plugins'
New-Item -ItemType Directory -Force -Path "$Runtime\data", "$Runtime\logs", $Plugins | Out-Null
Step 'Checking SQLite data source plugin'
if (-not (Test-Path "$Plugins\frser-sqlite-datasource")) {
    & $CliExe @CliArgs --homepath $GrafanaHome --pluginsDir $Plugins plugins install frser-sqlite-datasource
    if ($LASTEXITCODE -ne 0) { throw 'Plugin install failed (is this machine online?).' }
} else {
    Write-Host 'already installed'
}

# ------------------------------------------------------------------ database
Step 'Building the portfolio database from statements\*.pdf'
uv run stockdistro refresh
if ($LASTEXITCODE -ne 0) { throw 'stockdistro refresh failed - see the messages above.' }

if ($NoStart) { Write-Host "`nSetup complete. Run this script again without -NoStart to launch Grafana."; exit 0 }

# -------------------------------------------------------------------- launch
# The Windows installer can register a "Grafana" service that already owns port 3000.
$inUse = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($inUse) {
    $free = $Port + 1
    while (Get-NetTCPConnection -LocalPort $free -State Listen -ErrorAction SilentlyContinue) { $free++ }
    Write-Host "Port $Port is already in use (possibly the Grafana Windows service); using $free instead." -ForegroundColor Yellow
    $Port = $free
}

# Forward slashes: these values are substituted into YAML provisioning files.
$Fwd = $Root -replace '\\', '/'
$env:STOCKDISTRO_DB         = "$Fwd/data/portfolio.db"
$env:STOCKDISTRO_DASHBOARDS = "$Fwd/grafana/dashboards"
$env:GF_PATHS_DATA          = "$Runtime\data"
$env:GF_PATHS_LOGS          = "$Runtime\logs"
$env:GF_PATHS_PLUGINS       = $Plugins
$env:GF_PATHS_PROVISIONING  = Join-Path $Root 'grafana\provisioning'
$env:GF_DASHBOARDS_DEFAULT_HOME_DASHBOARD_PATH = Join-Path $Root 'grafana\dashboards\portfolio.json'
$env:GF_SERVER_HTTP_PORT    = "$Port"

Step "Starting Grafana at http://127.0.0.1:$Port  (Ctrl+C to stop)"
Start-Job -ArgumentList $Port -ScriptBlock {
    param($p)
    foreach ($i in 1..60) {
        Start-Sleep -Seconds 1
        try { Invoke-WebRequest "http://127.0.0.1:$p/api/health" -UseBasicParsing | Out-Null; Start-Process "http://127.0.0.1:$p"; break } catch {}
    }
} | Out-Null
& $ServerExe @ServerArgs --homepath $GrafanaHome --config (Join-Path $Root 'grafana\grafana.ini')
