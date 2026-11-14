# Installation

## Requirements

- Windows 10 or 11, 64-bit.
- SOLIDWORKS 2025.
- PreForm **3.66.0.1146** with its server started. The service refuses any other build (`PREFORM_SERVER_VERSION_UNSUPPORTED`). Installed copies live under `C:\Program Files\Formlabs\PreForm-beta\3.66.0.1146\`.
- To build: .NET SDK (the add-in targets .NET Framework 4.8), Python 3.11 or newer on the build machine, and the python.org **3.11 embeddable** zip (download it yourself; the script does not fetch executables).

The install folder carries its own Python and libraries. The target machine needs no system Python.

## 1. Build the install folder

```powershell
.\packaging\build_install.ps1 -Out D:\FormlabsSw -PythonZip C:\dl\python-3.11.9-embed-amd64.zip
```

The script:

1. unpacks the embedded Python and enables `site-packages`;
2. vendors the pinned `formlabs-sdk`, its generated client and the service into the install folder with `pip --target`;
3. builds the add-in into the same folder;
4. runs a smoke test with the embedded interpreter and prints `install OK`.

The folder then holds `FormlabsSw.AddIn.dll`, `FormlabsSw.Core.dll`, the SOLIDWORKS interop DLLs (copied beside the add-in so registration finds them), `Icons\`, `python\` and the vendored packages.

## 2. Register the add-in

In an **elevated** PowerShell:

```powershell
& "$env:WINDIR\Microsoft.NET\Framework64\v4.0.30319\regasm.exe" /codebase D:\FormlabsSw\FormlabsSw.AddIn.dll
```

This registers the COM class (GUID `6D1C7F0E-3B7A-4C55-9E55-2F1B0B7A4A10`) and the SOLIDWORKS add-in entry under `HKLM\SOFTWARE\SolidWorks\Addins`. The registration stores the folder path, so keep the folder where it is, or register again after moving it.

## 3. Turn it on in SOLIDWORKS

Open SOLIDWORKS, *Tools > Add-Ins*, and tick **Formlabs for SOLIDWORKS** under *Other Add-ins*. Tick the second box too if you want it to load at every start. You should see the purple butterfly tab in the Task Pane.

## 4. Start PreForm

Start PreForm 3.66.0.1146 and start its server. The default address is `http://localhost:44388`. The add-in attaches to it ("connect" mode) and does not start PreForm itself.

To make the add-in launch a PreForm Server executable instead, set the registry value `HKCU\Software\Formlabs\SolidWorks\PreformExe` (or the environment variable `FL_PREFORM_EXE`) to the executable path. The value `connect` (the default) means attach.

## Settings

Stored per user in `HKCU\Software\Formlabs\SolidWorks`. The pane writes most of them; you rarely edit them by hand.

| Value | Meaning | Default |
|---|---|---|
| `ProjectDir` | Current project folder. A folder from an earlier day rolls over to today's. | `Documents\Formlabs Projects\<today>` |
| `PreformExe` | `connect` or the path of a PreForm Server executable | `connect` |
| `Material` | Material code (one of the five supported) | `FLTO2002` |
| `Layer` | Layer thickness in mm | `0.1` |
| `Printer` | Printer name last chosen | `Form 4B` |
| `Orientation` | `view`, `same` or `yup` | `view` |
| `LockMode` | Lock set on imported models | keep orientation, allow translation |
| `ExportFormat` | `STEP` or `STL` | `STEP` |
| `WriteBack` | `1` writes `FL_*` into the part on send | `0` |

Environment variables: `FL_INSTALL_DIR` (use another install folder), `FL_PREFORM_EXE` (see above).

## Updating

SOLIDWORKS locks the add-in DLL while it runs, so an update needs it closed.

1. Build the new add-in into a staging folder (`dotnet build addin\FormlabsSw.AddIn -c Release -o <stage>`), or rebuild the install folder.
2. **Close SOLIDWORKS.**
3. Stop any leftover service process (`python.exe` whose command line contains `formlabs_sw_service`).
4. Copy the new `FormlabsSw.AddIn.dll`, and any changed files from `formlabs_sw_service\` and `Icons\`, into the install folder.
5. Reopen SOLIDWORKS.

Python-only changes need only steps 2 to 5 with the `.py` files, because the service is started fresh with each SOLIDWORKS session.

## Uninstalling

In an elevated PowerShell:

```powershell
& "$env:WINDIR\Microsoft.NET\Framework64\v4.0.30319\regasm.exe" /unregister D:\FormlabsSw\FormlabsSw.AddIn.dll
```

Then delete the install folder, `HKCU\Software\Formlabs`, and `%LOCALAPPDATA%\FormlabsSw` (the log). Your projects in `Documents\Formlabs Projects` are your files and are left alone.
