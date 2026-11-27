# Zoha one-step setup for Windows 10/11.
#   Right-click > Run with PowerShell, or:  powershell -ExecutionPolicy Bypass -File setup.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    Write-Host "Python 3.12 or newer was not found. Install it from https://www.python.org/downloads/ (tick 'Add python.exe to PATH'), then run this again." -ForegroundColor Yellow
    exit 1
}
$ok = & python -c "import sys; print(sys.version_info >= (3, 12))"
if ($ok -ne "True") {
    Write-Host "Zoha needs Python 3.12 or newer. You have:" -ForegroundColor Yellow
    & python --version
    exit 1
}

if (-not (Test-Path ".\venv\Scripts\python.exe")) {
    Write-Host "Creating the virtual environment..." -ForegroundColor Cyan
    & python -m venv venv
}
$py = ".\venv\Scripts\python.exe"

Write-Host "Installing Zoha's packages (a few minutes the first time)..." -ForegroundColor Cyan
& $py -m pip install --upgrade pip
& $py -m pip install -r requirements.txt

if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) {
    $answer = Read-Host "NVIDIA GPU found. Install the GPU add-on for faster speech recognition? (y/n)"
    if ($answer -match "^[yY]") { & $py -m pip install -r requirements-gpu.txt }
}

if (-not (Test-Path ".\.env")) {
    & $py setup_wizard.py
} else {
    Write-Host ".env already exists, skipping the setup wizard (run 'python setup_wizard.py' to change it)." -ForegroundColor DarkGray
}

Write-Host ""
Write-Host "Done. Start Zoha with:   .\venv\Scripts\python.exe gui.py" -ForegroundColor Green
Write-Host "Check your mic and voice: .\venv\Scripts\python.exe diagnostics.py --mic"
