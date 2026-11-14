# Builds the install folder for the add-in (spec D-03): embedded CPython + vendored service + pinned SDK.
# The add-in expects <install>\python\python.exe and <install>\formlabs_sw_service on PYTHONPATH.
#
# Usage: .\build_install.ps1 -Out C:\build\FormlabsSw [-PythonZip C:\dl\python-3.11.9-embed-amd64.zip]
# Download the embeddable zip yourself from python.org first (this script does not fetch executables).
param(
    [Parameter(Mandatory)] [string] $Out,
    [Parameter(Mandatory)] [string] $PythonZip,
    [string] $Config = "Release"
)
$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$repo = Resolve-Path (Join-Path $root "..")

New-Item -ItemType Directory -Force $Out | Out-Null
$py = Join-Path $Out "python"
Expand-Archive -Force $PythonZip $py

# Allow site-packages / vendored path in the embeddable distribution.
$pth = Get-ChildItem $py -Filter "python3*._pth" | Select-Object -First 1
$content = Get-Content $pth.FullName | ForEach-Object { $_ -replace '^#import site', 'import site' }
$content + ".." | Set-Content $pth.FullName

# Vendor dependencies (pinned SDK + the wheel it pins) and the service into the install folder.
python -m pip install --target $Out --upgrade `
    (Join-Path $repo "") `
    (Join-Path $root "service") --no-warn-script-location
if ($LASTEXITCODE -ne 0) { throw "pip vendoring failed" }
# pip leaves build folders next to the sources; remove them so the working tree stays clean.
foreach ($junk in @((Join-Path $repo "build"), (Join-Path $repo "formlabs_sdk.egg-info"), (Join-Path (Join-Path $root "service") "build"), (Join-Path (Join-Path $root "service") "formlabs_sw_service.egg-info"))) {
    if (Test-Path $junk) { Remove-Item -Recurse -Force $junk }
}

# Add-in binaries.
dotnet build (Join-Path $root "addin\FormlabsSw.AddIn") -c $Config -o $Out --nologo -v q
if ($LASTEXITCODE -ne 0) { throw "add-in build failed" }

# The interop DLLs must sit beside the add-in so COM registration and loading find them.
Copy-Item (Join-Path $root "addin\third_party\solidworks\*.dll") $Out -Force

# Smoke test: the vendored runtime can import the service and the SDK adapter, with no system Python.
$env:PYTHONPATH = $Out
& (Join-Path $py "python.exe") -I -c "import formlabs_sw_service.core, formlabs_sw_service.sdk_adapter, formlabs_sdk; print('install OK')"
if ($LASTEXITCODE -ne 0) { throw "vendored runtime smoke test failed" }

Write-Host "Install folder ready: $Out"
Write-Host "Register the add-in (elevated): regasm /codebase `"$Out\FormlabsSw.AddIn.dll`""
