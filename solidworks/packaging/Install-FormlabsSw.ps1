# Installs Formlabs for SOLIDWORKS from an unpacked release zip. Needs administrator rights (COM registration).
# Works in Windows PowerShell 5.1 and PowerShell 7.
param(
    [string] $Target = (Join-Path $env:ProgramFiles "Formlabs for SOLIDWORKS")
)
$ErrorActionPreference = "Stop"

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "Asking for administrator rights..."
    $exe = (Get-Process -Id $PID).Path
    Start-Process $exe -Verb RunAs -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$PSCommandPath`"", "-Target", "`"$Target`"")
    return
}

$source = Join-Path $PSScriptRoot "FormlabsSw"
if (-not (Test-Path (Join-Path $source "FormlabsSw.AddIn.dll"))) { throw "FormlabsSw\FormlabsSw.AddIn.dll not found next to this script. Unpack the whole zip first." }
if (Get-Process SLDWORKS -ErrorAction SilentlyContinue) { throw "SOLIDWORKS is running. Close it, then run this again." }

# A running service from an earlier install would keep files locked.
Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*formlabs_sw_service*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }

Write-Host "Copying files to $Target ..."
New-Item -ItemType Directory -Force $Target | Out-Null
Copy-Item -Path (Join-Path $source "*") -Destination $Target -Recurse -Force
Get-ChildItem $Target -Recurse -File | Unblock-File

$regasm = Join-Path $env:WINDIR "Microsoft.NET\Framework64\v4.0.30319\regasm.exe"
if (-not (Test-Path $regasm)) { throw "regasm.exe not found at $regasm (.NET Framework 4.x is required)." }
Write-Host "Registering the add-in ..."
& $regasm /codebase (Join-Path $Target "FormlabsSw.AddIn.dll") | Out-Null
if ($LASTEXITCODE -ne 0) { throw "regasm failed with exit code $LASTEXITCODE" }

Write-Host ""
Write-Host "Installed to $Target"
Write-Host "Next: start PreForm 3.66.0.1146 and its server, open SOLIDWORKS, then tick"
Write-Host "      Tools > Add-Ins > Formlabs for SOLIDWORKS."
if ($Host.Name -eq "ConsoleHost") { Read-Host "Press Enter to close" | Out-Null }
