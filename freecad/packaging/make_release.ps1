# Builds the release zip for Formlabs for FreeCAD: the workbench folder, a private runtime (embedded Python,
# the pinned SDK and the Integration Service) and Install / Uninstall scripts. No .NET and no CAD install needed.
#
# Usage: .\make_release.ps1 -Version v0.1.0 [-Out dist\release] [-PythonZip path\to\python-3.11.9-embed-amd64.zip]
param(
    [Parameter(Mandatory)] [string] $Version,
    [string] $Out = (Join-Path $PSScriptRoot "..\dist\release"),
    [string] $PythonZip
)
$ErrorActionPreference = "Stop"
$PyUrl = "https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip"
$PySha256 = "009D6BF7E3B2DDCA3D784FA09F90FE54336D5B60F0E0F305C37F400BF83CFD3B"
$fc = Resolve-Path (Join-Path $PSScriptRoot "..")
$repo = Resolve-Path (Join-Path $fc "..")

New-Item -ItemType Directory -Force $Out | Out-Null
$Out = (Resolve-Path $Out).Path
$work = Join-Path $Out "work"
if (Test-Path $work) { Remove-Item -Recurse -Force $work }
New-Item -ItemType Directory -Force $work | Out-Null

if (-not $PythonZip) {
    $PythonZip = Join-Path $work "python-embed.zip"
    Invoke-WebRequest $PyUrl -OutFile $PythonZip -UseBasicParsing
}
$actual = (Get-FileHash $PythonZip -Algorithm SHA256).Hash
if ($actual -ne $PySha256) { throw "Embedded Python checksum mismatch: expected $PySha256, got $actual" }

$stage = Join-Path $work "FormlabsFreeCAD-$Version"
$runtime = Join-Path $stage "Runtime"
$py = Join-Path $runtime "python"
New-Item -ItemType Directory -Force $runtime | Out-Null
Expand-Archive -Force $PythonZip $py
$pth = Get-ChildItem $py -Filter "python3*._pth" | Select-Object -First 1
(Get-Content $pth.FullName | ForEach-Object { $_ -replace '^#import site', 'import site' }) + ".." | Set-Content $pth.FullName

python -m pip install --target $runtime --upgrade $repo (Join-Path $repo "solidworks\service") --no-warn-script-location
if ($LASTEXITCODE -ne 0) { throw "pip vendoring failed" }
foreach ($junk in @((Join-Path $repo "build"), (Join-Path $repo "formlabs_sdk.egg-info"),
                    (Join-Path $repo "solidworks\service\build"), (Join-Path $repo "solidworks\service\formlabs_sw_service.egg-info"))) {
    if (Test-Path $junk) { Remove-Item -Recurse -Force $junk }
}
$env:PYTHONPATH = $runtime
& (Join-Path $py "python.exe") -I -c "import formlabs_sw_service.core, formlabs_sw_service.sdk_adapter, formlabs_sdk; print('runtime OK')"
if ($LASTEXITCODE -ne 0) { throw "vendored runtime smoke test failed" }

Copy-Item (Join-Path $fc "Formlabs") (Join-Path $stage "Formlabs") -Recurse
Get-ChildItem $stage -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force
Copy-Item (Join-Path $PSScriptRoot "Install-FormlabsFreeCAD.ps1") $stage
Copy-Item (Join-Path $PSScriptRoot "Uninstall-FormlabsFreeCAD.ps1") $stage
Copy-Item (Join-Path $fc "docs\USER_GUIDE.md") (Join-Path $stage "USER_GUIDE.md")
@"
Formlabs for FreeCAD $Version

Requirements: Windows 10/11 64-bit, FreeCAD 1.0 or newer, PreForm 3.66.0.1146 with its server started.

Install: close FreeCAD, then right-click Install-FormlabsFreeCAD.ps1 > Run with PowerShell. No administrator rights needed.
Then start FreeCAD and choose the Formlabs workbench.
Uninstall: run Uninstall-FormlabsFreeCAD.ps1. See USER_GUIDE.md.
"@ | Set-Content (Join-Path $stage "README.txt") -Encoding UTF8
$Version | Set-Content (Join-Path $stage "VERSION.txt") -Encoding ASCII

$zip = Join-Path $Out "FormlabsFreeCAD-$Version-win64.zip"
if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive -Path (Join-Path $stage "*") -DestinationPath $zip
$hash = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLower()
"$hash  $(Split-Path $zip -Leaf)" | Set-Content (Join-Path $Out "SHA256SUMS-freecad.txt") -Encoding ASCII
Remove-Item -Recurse -Force $work
Write-Host "Release zip: $zip"
Write-Host "SHA-256:     $hash"
