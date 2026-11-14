# Development

## Layout and conventions

See the [README](../README.md#repository-layout). Python code uses frozen `attrs` classes and type annotations; C# targets .NET Framework 4.8. Keep files focused and under about 800 lines, handle errors explicitly, and never log tokens.

## Build and test

```bash
# Service
cd solidworks/service
python -m pip install -e ".[test]"
python -m pytest                    # 48 tests, against a fake PreForm port

# C# core (no SOLIDWORKS needed)
cd solidworks/addin
dotnet run --project FormlabsSw.Core.Tests    # ALL PASSED

# Add-in
dotnet build solidworks/addin/FormlabsSw.AddIn -c Release -o <folder>
```

`FormlabsSw.Core.Tests` is a small dependency-free program (exit code 0 means every check passed). It covers the matrix maths, the view-orientation maths and the HTTP client.

The pytest suite uses `FakePort` in `tests/conftest.py`. When you add a method to `PreformPort` (`ports.py`), add it to `FakePort` and to `SdkAdapter`.

## Working against a real PreForm

1. Start PreForm 3.66.0.1146 and its server (it must listen on `localhost:44388`).
2. Run the live checks:

```bash
cd solidworks/service
python scripts/phase0_check.py connect <part.step-or.stl> [printer-serial]   # scenes, imports, layout, validators, save, reopen
python scripts/phase1_check.py <step_v1> <step_v2> <projectDir>             # replace in place, restore, project save (attaches to the running server)
```

`connect` attaches to the running server instead of launching a PreForm Server executable. `phase1_check.py` always attaches. Neither script submits anything: a printer given to phase 0 only ever receives `print_now=False`. `step_v2` must differ from `step_v1` (the same body, edited) to exercise replace-in-place.

Rules for experiments against a **real** PreForm window:

- Your test scenes appear in the user's PreForm. Delete the scenes you create and remove any model you add to a scene you do not own.
- Opening or saving a `.form` with a project name can leave that name in the PreForm session, which then titles later builds "Untitled Project". Restart PreForm after such experiments.
- PreForm's starting blank scene cannot be deleted through the API.

## The SOLIDWORKS harness

`addin/FormlabsSw.Harness` attaches to a running SOLIDWORKS (`Marshal.GetActiveObject`) and runs the add-in's own code without the UI:

| Command | Does |
|---|---|
| `load <dll>` / `debugconnect` | Load the add-in; run the Connect logic inside SOLIDWORKS |
| `send` | Run the real Send path synchronously on the active part or assembly |
| `export <dir> <csName>` | Export bodies relative to a coordinate system |
| `bbox`, `viewprobe`, `setview <1\|4\|5\|7>` | Inspect geometry and views (front, right, top, isometric) |
| `props <material> <layer> <cs>` | Set `FL_*` properties on the active part |
| `cs <x> <y> <z>` | Create a coordinate system at a point (mm) |
| `closeothers`, `exit` | Tidy up |
| `connect` | The pane's Connect logic, without SOLIDWORKS |

A typical end-to-end check:

```powershell
$env:FL_INSTALL_DIR = "D:\...\solidworks\dist\FormlabsSw"   # use the installed service
dotnet build addin\FormlabsSw.Harness -c Release
addin\FormlabsSw.Harness\bin\Release\net48\FormlabsSw.Harness.exe send
```

Cautions:

- The harness sends into the **real** project folder (`Documents\Formlabs Projects\<today>`) unless `ProjectDir` points at today's date folder elsewhere; a stored folder that is not today's rolls over. Remove your test builds afterwards.
- Never run it while the user's own SOLIDWORKS session is the one it would attach to.
- Stop the service it leaves behind (`python.exe` with `formlabs_sw_service` on its command line) before the next run.

## Gotchas learned the hard way

**SOLIDWORKS API**

- `IMathTransform.ArrayData` is 16 doubles: nine rotation numbers in the row-vector convention, three translation numbers in metres, then scale. Rotations are transposed compared with a column-vector 4x4.
- `CreateFeatureFromBody3` returns null on success; verify by counting solid bodies.
- Casting `IBody2` to `IEntity` fails; use `body.Select2(false, null)`.
- `IComponent2.GetBodies3` returns bodies in part coordinates; apply `Transform2`.
- Add-in icons (PNG at 20, 32, 40, 64, 96, 128) are mandatory or the tab and button are invisible.
- The add-in class needs `ClassInterfaceType.AutoDispatch`.

**PreForm 3.66 and the SDK**

- `get_server_version` returns the PreForm build string.
- Use the SDK's enums (`ImportUnits`, `RepairBehavior`, `OnLayoutFailure`), not strings.
- 3.66 omits `is_group`, so typed `list_models` and `list_scenes` fail; read raw JSON.
- Regenerating supports on a model that has none is rejected.
- Print settings must come from the catalog: Tough 2000 V2's default is `SUPPORTSV1`.
- Form 4B and Form 4 share machine type `FORM-4-0`.
- Saving a `.form` with `project_name` makes the reopened scene untitled; saving without it titles the scene by the file name.

**Tooling**

- Bash heredocs with quotes can fail with "unexpected EOF"; write script files instead.
- PowerShell 7 has no `Marshal.GetActiveObject`.
- `pip` packaging can leave stray `build/` and `*.egg-info` folders; delete them.

## Continuous integration and releases

Two GitHub Actions workflows live in `.github/workflows/`:

| Workflow | Runs on | Does |
|---|---|---|
| `solidworks-ci.yml` | Every push to `main` and every pull request that touches `solidworks/`, the SDK or the workflows | Installs the SDK and service, runs the 48 pytest tests, builds the add-in and the harness, runs the C# core checks, builds the full release zip and uploads it as a 14-day build artifact |
| `solidworks-release.yml` | A pushed tag named `solidworks-v<version>` | Runs the tests, builds the release zip, creates a GitHub Release with the zip and `SHA256SUMS.txt`, and uses [RELEASE_NOTES_TEMPLATE.md](RELEASE_NOTES_TEMPLATE.md) as the notes |

The runners are Windows. They do not have SOLIDWORKS, PreForm or a printer, so CI proves that everything builds, the tests pass and the package assembles. It does not prove the add-in works inside SOLIDWORKS; that is the manual check below.

### Publishing a release

1. Update [CHANGELOG.md](../CHANGELOG.md) and [VERIFICATION.md](VERIFICATION.md).
2. Run the manual check against PreForm 3.66.0.1146: both phase scripts, then a harness `send` for a part and for an assembly.
3. Tag and push:

```bash
git tag solidworks-v0.1.0
git push origin solidworks-v0.1.0
```

The workflow publishes `FormlabsSw-v0.1.0-win64.zip`. Users download it from the Releases page ([installation](INSTALL.md#install-from-a-release-most-users)).

### Supply chain notes

- The embedded Python zip is downloaded from python.org and checked against the SHA-256 pinned in `packaging/make_release.ps1`. To move to another Python version, change the URL and the hash together.
- The SDK is installed from this repository, not from PyPI.
- `addin/third_party/solidworks/` holds `SolidWorks.Interop.sldworks`, `swconst` and `swpublished` (version 33.0, from SOLIDWORKS 2025's `api\redist` folder). They are Dassault Systèmes files that SOLIDWORKS provides for redistribution with add-ins. Replace them from a newer SOLIDWORKS to target a newer release.
