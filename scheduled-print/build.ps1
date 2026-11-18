# Builds dist\FormlabsScheduledPrint\ (a folder with the .exe; zip it to move to another PC).
# Needs Python 3.11+ with the SDK installed:  pip install -e ..  pyinstaller
param([string]$Dist = "dist")  # output folder; use another one if the app is running from dist
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$py = if ($env:PYTHON) { $env:PYTHON } else { "python" }  # set PYTHON to a venv's python.exe if the SDK lives there
& $py -m PyInstaller app.py --name FormlabsScheduledPrint --onedir --windowed --noconfirm --clean `
    --collect-all formlabs_sdk --collect-all formlabs_preform_api `
    --distpath $Dist --workpath build --specpath build
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }
Write-Host "Built: $Dist\FormlabsScheduledPrint\FormlabsScheduledPrint.exe"
