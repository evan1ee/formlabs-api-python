# Installs Formlabs for FreeCAD for the current user (no administrator rights needed).
#   Workbench -> %APPDATA%\FreeCAD\Mod\Formlabs (FreeCAD 1.0) and every versioned %APPDATA%\FreeCAD\v*\Mod\Formlabs (1.1)
#   Runtime   -> %LOCALAPPDATA%\Formlabs\Runtime      (private Python, SDK, Integration Service)
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not (Test-Path (Join-Path $here "Formlabs\InitGui.py"))) { throw "Run this script from the unpacked release folder." }
if (Get-Process FreeCAD -ErrorAction SilentlyContinue) { throw "Close FreeCAD first, then run the installer again." }

$fcRoot = Join-Path $env:APPDATA "FreeCAD"
$mods = @((Join-Path $fcRoot "Mod\Formlabs")) + @(Get-ChildItem $fcRoot -Directory -Filter "v*" -ErrorAction SilentlyContinue | ForEach-Object { Join-Path $_.FullName "Mod\Formlabs" })
$runtime = Join-Path $env:LOCALAPPDATA "Formlabs\Runtime"
foreach ($d in $mods + @($runtime)) {
    if (Test-Path $d) { Remove-Item -Recurse -Force $d }
    New-Item -ItemType Directory -Force (Split-Path $d) | Out-Null
}
foreach ($m in $mods) { Copy-Item (Join-Path $here "Formlabs") $m -Recurse }
Copy-Item (Join-Path $here "Runtime") $runtime -Recurse
Write-Host "Installed."
$mods | ForEach-Object { Write-Host "  Workbench: $_" }
Write-Host "  Runtime:   $runtime"
Write-Host "Start PreForm and its server, start FreeCAD and choose the Formlabs workbench."
if ($Host.Name -eq "ConsoleHost" -and -not $env:CI) { Read-Host "Press Enter to close" | Out-Null }
