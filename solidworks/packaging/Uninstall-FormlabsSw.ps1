# Removes Formlabs for SOLIDWORKS. Needs administrator rights. Your projects in Documents\Formlabs Projects are kept.
param(
    [string] $Target = (Join-Path $env:ProgramFiles "Formlabs for SOLIDWORKS")
)
$ErrorActionPreference = "Stop"

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    $exe = (Get-Process -Id $PID).Path
    Start-Process $exe -Verb RunAs -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$PSCommandPath`"", "-Target", "`"$Target`"")
    return
}
if (Get-Process SLDWORKS -ErrorAction SilentlyContinue) { throw "SOLIDWORKS is running. Close it, then run this again." }

Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*formlabs_sw_service*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }

$dll = Join-Path $Target "FormlabsSw.AddIn.dll"
if (Test-Path $dll) {
    $regasm = Join-Path $env:WINDIR "Microsoft.NET\Framework64\v4.0.30319\regasm.exe"
    & $regasm /unregister $dll | Out-Null
}
if (Test-Path $Target) { Remove-Item -Recurse -Force $Target }
Remove-Item -Recurse -Force (Join-Path $env:LOCALAPPDATA "FormlabsSw") -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force "HKCU:\Software\Formlabs" -ErrorAction SilentlyContinue

Write-Host "Removed. Your projects in Documents\Formlabs Projects were not touched."
if ($Host.Name -eq "ConsoleHost") { Read-Host "Press Enter to close" | Out-Null }
