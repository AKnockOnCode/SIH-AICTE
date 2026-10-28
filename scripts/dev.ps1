# One-command local start for AgniDrishti (Windows PowerShell).
#
#   powershell -ExecutionPolicy Bypass -File scripts\dev.ps1
#
# First run: creates .venv, installs Python packages, builds the UI if Node.js is installed
# (otherwise serves the prebuilt frontend\dist), then starts http://localhost:8000.
# Safe by default: an existing database is reused; it is seeded only when empty.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$Port = if ($env:PORT) { $env:PORT } else { "8000" }
$Py = if ($env:PYTHON) { $env:PYTHON } else { "python" }
$VenvPy = Join-Path $Root ".venv\Scripts\python.exe"

if (-not (Test-Path $VenvPy)) {
    Write-Host "==> Creating Python virtual environment in .venv"
    & $Py -c "import sys; assert sys.version_info >= (3, 11), 'Python 3.11+ required'"
    & $Py -m venv .venv
}
& $VenvPy -c "import starlette, pydantic, uvicorn, multipart, sklearn, scipy, networkx, reportlab, openpyxl, xlsxwriter" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "==> Installing Python packages (backend\requirements.txt)"
    & $VenvPy -m pip install --upgrade pip
    & $VenvPy -m pip install -r backend\requirements.txt
}
if (-not (Test-Path ".env")) { Copy-Item ".env.example" ".env"; Write-Host "==> Created .env from .env.example" }

if (Get-Command npm -ErrorAction SilentlyContinue) {
    Push-Location frontend
    if (-not (Test-Path "node_modules")) { npm install --no-audit --no-fund }
    npm run build
    Pop-Location
} elseif (Test-Path "frontend\dist\index.html") {
    Write-Host "==> Node.js not found: serving the prebuilt UI in frontend\dist"
} else {
    Write-Host "!!  Node.js not found and frontend\dist is missing: only the API will be available"
}

Write-Host ""
Write-Host "    AgniDrishti  ->  http://localhost:$Port"
Write-Host "    API docs     ->  http://localhost:$Port/api/docs"
Write-Host "    First start seeds the synthetic dataset and trains the local models (about 10 s). Press Ctrl+C to stop."
Write-Host ""
Start-Job -ScriptBlock { param($p) Start-Sleep -Seconds 2; Start-Process "http://localhost:$p" } -ArgumentList $Port | Out-Null
Set-Location backend
& $VenvPy -m uvicorn app.main:app --host 127.0.0.1 --port $Port
