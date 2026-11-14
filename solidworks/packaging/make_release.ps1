# Builds the release zip that end users download: the install folder plus Install / Uninstall scripts.
#
# Usage:  .\make_release.ps1 -Version v0.1.0 [-Out dist\release] [-PythonZip path\to\python-3.11.9-embed-amd64.zip]
# Without -PythonZip the embeddable Python is downloaded from python.org and checked against a pinned SHA-256.
param(
    [Parameter(Mandatory)] [string] $Version,
    [string] $Out = (Join-Path $PSScriptRoot "..\dist\release"),
    [string] $PythonZip
)
$ErrorActionPreference = "Stop"
$PyUrl = "https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip"
$PySha256 = "009D6BF7E3B2DDCA3D784FA09F90FE54336D5B60F0E0F305C37F400BF83CFD3B"

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

$stage = Join-Path $work "FormlabsSw-$Version"
$install = Join-Path $stage "FormlabsSw"
& (Join-Path $PSScriptRoot "build_install.ps1") -Out $install -PythonZip $PythonZip
if ($LASTEXITCODE -ne 0) { throw "build_install.ps1 failed" }

# Drop build leftovers that users do not need.
Get-ChildItem $install -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force
Get-ChildItem $install -Recurse -File -Include *.pdb | Remove-Item -Force

Copy-Item (Join-Path $PSScriptRoot "Install-FormlabsSw.ps1") $stage
Copy-Item (Join-Path $PSScriptRoot "Uninstall-FormlabsSw.ps1") $stage
Copy-Item (Join-Path $PSScriptRoot "..\docs\INSTALL.md") (Join-Path $stage "INSTALL.md")
Copy-Item (Join-Path $PSScriptRoot "..\docs\USER_GUIDE.md") (Join-Path $stage "USER_GUIDE.md")
@"
Formlabs for SOLIDWORKS $Version

Requirements: Windows 10/11 64-bit, SOLIDWORKS 2025, PreForm 3.66.0.1146 with its server started.

Install:
  1. Close SOLIDWORKS.
  2. Right-click Install-FormlabsSw.ps1 > Run with PowerShell (it asks for administrator rights),
     or run it from an elevated PowerShell.
  3. Start PreForm and its server, open SOLIDWORKS, then tick Tools > Add-Ins > Formlabs for SOLIDWORKS.

Uninstall: run Uninstall-FormlabsSw.ps1 the same way.
See INSTALL.md and USER_GUIDE.md for details.
"@ | Set-Content (Join-Path $stage "README.txt") -Encoding UTF8
$Version | Set-Content (Join-Path $stage "VERSION.txt") -Encoding ASCII

$zip = Join-Path $Out "FormlabsSw-$Version-win64.zip"
if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive -Path (Join-Path $stage "*") -DestinationPath $zip
$hash = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLower()
"$hash  $(Split-Path $zip -Leaf)" | Set-Content (Join-Path $Out "SHA256SUMS.txt") -Encoding ASCII
Remove-Item -Recurse -Force $work
Write-Host "Release zip: $zip"
Write-Host "SHA-256:     $hash"
