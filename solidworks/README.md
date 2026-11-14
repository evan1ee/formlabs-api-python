# Formlabs for SOLIDWORKS

A SOLIDWORKS add-in that sends parts and whole assemblies to **PreForm** with one click. It exports the geometry, places it the way you see it on screen, imports it into a build, generates supports and lays the build out. You then open the build in PreForm to check it and print.

It implements [the v1.1 specification](../docs/specs/2026-11-13-formlabs-for-solidworks-spec-v1.1.md) on top of the PreForm Server API, through the `formlabs-sdk` in this repository.

| | |
|---|---|
| SOLIDWORKS | 2025 (API revision 33.0) |
| PreForm | **3.66.0.1146** (beta). Any other build is refused on purpose. |
| SDK | `formlabs-sdk` v1.0.0-alpha.post2 |
| Add-in | C#, .NET Framework 4.8, COM add-in with a WPF Task Pane |
| Service | Python 3.11 (embedded in the install folder), loopback HTTP, SQLite |

## What it does

1. **One click.** Click *Send active part to Formlabs* in the Formlabs Task Pane. No properties, coordinate systems or other set-up are needed.
2. **Parts and assemblies.** In a part it sends the selected solid bodies, or all of them. In an assembly it sends every visible, unsuppressed part in one batch, each placed as it sits in the assembly.
3. **What you see is how it lands.** The part is placed in PreForm the way the current SOLIDWORKS view shows it.
4. **Automatic preparation.** After the import it saves the build, generates supports (internal supports off) and runs auto layout.
5. **Names, not codes.** Builds are named `yyyy-mm-dd-hh-mm-ss-<material name>`, for example `2026-11-14-22-21-28-Tough-2000-V2`. The same text is the `.form` file name and the build title in PreForm.
6. **Re-send.** Moving or turning a part and sending again replaces it in place and rebuilds its supports. Sending an unchanged part does nothing.
7. **Resilient.** It copes with PreForm being closed and reopened, and with builds or parts you delete in PreForm.

Supported materials: Tough 2000 V2 (default), Grey V5, White V5, Clear V5, Rigid 10K. Default printer: Form 4B. Layer thickness: 0.025, 0.05 or 0.1 mm (default 0.1).

## Documentation

| Document | For |
|---|---|
| [User guide](docs/USER_GUIDE.md) | Using the add-in day to day |
| [Installation](docs/INSTALL.md) | Building the install folder, registering, updating, uninstalling |
| [Troubleshooting](docs/TROUBLESHOOTING.md) | Error messages, logs, known PreForm quirks |
| [Architecture](docs/ARCHITECTURE.md) | Components, data flow, HTTP API, data model, behaviours |
| [Development](docs/DEVELOPMENT.md) | Building, tests, the SOLIDWORKS harness, working against PreForm |
| [Verification](docs/VERIFICATION.md) | What has been tested for real, what has not, open decisions |
| [Changelog](CHANGELOG.md) | What changed, in order |

CI and releases are described in [Development](docs/DEVELOPMENT.md#continuous-integration-and-releases).

## Repository layout

```
solidworks/
  addin/
    FormlabsSw.Core/         IPC client, service host, 4x4 maths, view-orientation maths (no SOLIDWORKS dependency)
    FormlabsSw.Core.Tests/   dependency-free test program for Core (exit code 0 = pass)
    FormlabsSw.AddIn/        the SOLIDWORKS add-in: COM entry point, Send command, exporter, Task Pane, icons
    FormlabsSw.Harness/      console tool that drives a running SOLIDWORKS for end-to-end checks
  service/
    formlabs_sw_service/     the Integration Service (Python)
    tests/                   pytest suite (fake PreForm port)
    scripts/                 phase0_check.py, phase1_check.py: live checks against a PreForm server
  packaging/                 build_install.ps1 (install folder), make_release.ps1 (release zip), Install/Uninstall scripts shipped in the zip
  addin/third_party/         SOLIDWORKS interop DLLs the add-in compiles against
  dist/                      the built install folder (git-ignored)
  docs/                      the documents listed above
```

## Install from a release

Download `FormlabsSw-<version>-win64.zip` from the GitHub Releases page, unpack it, close SOLIDWORKS and run `Install-FormlabsSw.ps1` (right-click, *Run with PowerShell*). Then start PreForm's server and tick the add-in in SOLIDWORKS. A tag named `solidworks-v<version>` triggers the release workflow; see [Development](docs/DEVELOPMENT.md#continuous-integration-and-releases).

## Build it yourself

```powershell
# 1. Build the install folder (needs the python.org 3.11 embeddable zip downloaded first)
.\packaging\build_install.ps1 -Out D:\FormlabsSw -PythonZip C:\dl\python-3.11.9-embed-amd64.zip

# 2. Register the add-in (elevated PowerShell)
& "$env:WINDIR\Microsoft.NET\Framework64\v4.0.30319\regasm.exe" /codebase D:\FormlabsSw\FormlabsSw.AddIn.dll

# 3. Start PreForm 3.66.0.1146, start its server, then open SOLIDWORKS
```

In SOLIDWORKS tick *Formlabs for SOLIDWORKS* under *Tools > Add-Ins* once. Details are in the [installation guide](docs/INSTALL.md).

## Tests

```bash
cd solidworks/service && python -m pip install -e ".[test]" && python -m pytest        # 48 tests
cd solidworks/addin && dotnet run --project FormlabsSw.Core.Tests                      # prints ALL PASSED
```

## Status

Phases 0 and 1 (service against a real server), the add-in's Send path for parts and assemblies, view-based orientation, automatic supports and layout, and the resilience behaviours have all been run for real. Real print submission has not (the pane no longer offers it; see [Verification](docs/VERIFICATION.md)). Nothing in this folder is committed yet.
