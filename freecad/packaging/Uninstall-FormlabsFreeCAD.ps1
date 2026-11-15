# Removes Formlabs for FreeCAD. Your projects in Documents\Formlabs Projects are your files and are kept.
$ErrorActionPreference = "Stop"
if (Get-Process FreeCAD -ErrorAction SilentlyContinue) { throw "Close FreeCAD first." }
$mod = Join-Path $env:APPDATA "FreeCAD\Mod\Formlabs"
$runtime = Join-Path $env:LOCALAPPDATA "Formlabs\Runtime"
$settings = Join-Path $env:APPDATA "Formlabs\FreeCAD"
foreach ($d in @($mod, $runtime, $settings)) { if (Test-Path $d) { Remove-Item -Recurse -Force $d; Write-Host "Removed $d" } }
if ($Host.Name -eq "ConsoleHost" -and -not $env:CI) { Read-Host "Press Enter to close" | Out-Null }
