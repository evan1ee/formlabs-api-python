# Architecture

## Overview

```
SOLIDWORKS 2025
 └─ FormlabsSw.AddIn (C#, COM add-in, UI thread)
      ├─ Task Pane (WPF in an ElementHost), toolbar/menu command
      ├─ BodyExporter: copies bodies, places them, exports STEP/STL from a temporary part
      └─ FormlabsSw.Core: ServiceHost (starts Python), ServiceClient (HTTP), ViewOrientation, Matrix4
            │  loopback HTTP, bearer token, JSON
            ▼
 Integration Service (Python 3.11, one process per SOLIDWORKS session)
      ├─ http_api    routes, token check, async operations
      ├─ core        ProjectService: sends, builds, supports, layout, validation, submission, recovery
      ├─ store/db    SQLite project database (JSON documents, migrations)
      ├─ journal     operation journal, written before every PreForm mutation
      └─ sdk_adapter the only module that imports formlabs-sdk
            │  HTTP (PreForm Server API v1.0.0-alpha)
            ▼
 PreForm 3.66.0.1146 (GUI-hosted server on localhost:44388, "connect" mode)
```

All SOLIDWORKS COM work happens on the UI thread. Everything slow (service calls, waiting) happens off-thread so SOLIDWORKS never blocks. Nothing in the add-in talks to PreForm directly.

## The add-in

| File | Role |
|---|---|
| `SwAddin.cs` | COM entry point (`ISwAddin`). Registers the command group, the toolbar item and the Task Pane. Tolerant start-up: each step is logged and a failure never makes SOLIDWORKS untick the add-in. `ClassInterfaceType.AutoDispatch` is required for `SetAddinCallbackInfo2` and name-based command callbacks. |
| `TaskPane.cs` | WPF pane: status line and progress, material and layer, Send button, collapsed *More options* and *Project and connection*. Buttons are disabled while a call runs. |
| `SendCommand.cs` | Prepares the export on the UI thread, then dispatches to the service on a worker thread; always reports back, success or failure. Runs the automatic steps after the import. |
| `BodyExporter.cs` | Per-body export for parts (`Export`) and per-component export for assemblies (`ExportAssembly`). |
| `Session.cs` | Per-user settings in the registry, defaults, project folder rollover, the shared service host. |
| `FormlabsSw.Core` | `ServiceHost` (launches `python -I -m formlabs_sw_service`, hands the token over in an environment variable, reads the port from one JSON line), `ServiceClient` (bearer token, operation polling), `ViewOrientation`, `Matrix4`. |

### Export and placement

For every body the exporter copies it (`Body2.Copy2`), moves the copy with a transform, builds a temporary part from it, saves STEP or STL, and closes the temporary part. The source document is never modified. (The output-coordinate-system preferences were tried first and do not shift exports.)

The transform is one of:

- **View** (default). The model is mapped through the current graphics view. SOLIDWORKS stores a view rotation as nine numbers in the row-vector convention (`IModelView.Orientation3.ArrayData`; Front is the identity). Screen coordinates are X right, Y up, Z toward the viewer; PreForm is X right, Z up, front at -Y, so screen `(a, b, c)` becomes PreForm `(a, -c, b)`. `ViewOrientation.FromView` multiplies the two.
- **Same**: the identity. PreForm axes equal the model axes.
- **Y up**: `(x, y, z)` becomes `(x, -z, y)`.
- **Named coordinate system** (`FL_PrintCS`): the inverse of that system's transform. Overrides the others.

In an assembly each part body first gets the component's `Transform2` (part to assembly), then the view transform. PreForm keeps the XY position and drops the model onto the platform in Z (observed, "OD-01").

## The Integration Service

### Data model (SQLite, `project.db`)

| Table | Content |
|---|---|
| `project` | One row: id, name (`yyyy-mm-dd`), folder |
| `build` | One row per build. Unique `key` = machine type, material code, layer, print-setting fingerprint. `form_file`, status, validation status, acknowledged warnings, support parameters, dirty flag. |
| `model` | One row per model. Unique `identity_key` = document path, configuration, body id. Source file and hash, lock, export settings, PreForm fingerprint (bounding box, model hash), status. |
| `operation` | The journal: state `RUNNING`, `SUCCEEDED`, `FAILED`, `UNCERTAIN` |
| `job` | Print jobs submitted through the service |
| `catalog_cache` | PreForm's print-setting catalog |

Build status: `EMPTY`, `HAS_MODELS`, `SUPPORTED`, `LAID_OUT`, `VALIDATED`, `SAVED`. Model status: `IMPORTED`, `SUPPORTS_STALE`, `SUPPORTED`.

Frozen `attrs` classes; every change creates a new object and writes it.

### Naming

- Project: `yyyy-mm-dd` (folder and name). The add-in rolls a stored folder from an earlier day over to today's.
- Build: `yyyy-mm-dd-hh-mm-ss-<material name>` (`-2`, `-3` on collision), also the `.form` file name. Material names come from `naming.MATERIAL_NAMES`.

### Send flow (`send_model`)

1. Revalidate PreForm's state (below).
2. Resolve the print setting from the catalog (`SUPPORTSV1` is Tough 2000 V2's default, not `DEFAULT`) and validate it.
3. Look the model up by identity key and decide:

| Situation | Action |
|---|---|
| Not known | Import into the build found or created for its key |
| Known, same build key, same file hash | `unchanged`, nothing is touched |
| Known, same build key, new hash | Replace in place: import the new geometry, remove the old model, keep the lock, mark supports stale |
| Known, different build key (material, layer or setting changed, or the build was retired) | Move: import into the target build, remove from the old one |

4. Every PreForm mutation is journalled before it runs and marked after. A timeout marks the operation `UNCERTAIN`.
5. The build is marked dirty and an autosave is scheduled (debounced, 2 s).

The add-in then, for each changed build: saves it, generates supports, runs auto layout.

### Supports and layout

- Supports use `auto_support_models` with `internal_supports_enabled=False` unless a caller opts in. Replaced models get fresh supports for the new geometry through the same call restricted to those models.
- Layout uses `on_layout_failure=FAIL_AND_LEAVE_SCENE_UNCHANGED`, a fixed seed and rotation locking that follows the models' locks. Failure raises `LAYOUT_WOULD_EJECT` and changes nothing.

### Saving, naming in PreForm, and restore

- A build is saved atomically (write `<name>.tmp.form`, keep a `.bak`, replace) with **no** stored project name.
- PreForm titles a build opened from a file by the file name, but gives it the generic title "Untitled Project N" if the file stores a project name. A scene created through the API is always titled "Untitled Project N" and the API cannot rename it. So after a build's first save the service reopens its `.form`, remaps the models by name, and deletes the untitled scene. From then on the build is the reopened one.
- Restore: a PreForm model's name is the model id the service assigned at import. Remapping after a reopen is by that name, and a hash check detects substituted geometry (`MODEL_IDENTITY_MISMATCH`).

### Sessions and resilience

- **New session, new build.** On the first connect of a service run, and whenever PreForm has lost all of its known scenes, existing builds are *retired*: their key is changed so the next send opens a fresh build. Retired builds reopen lazily, only if something needs them. Re-sending a part that lives in a retired build moves it to the current build.
- **Revalidation before each send.** All cached scenes gone means PreForm restarted: saved builds reopen on demand, a never-saved build forgets its models so the next send imports again. Only some scenes gone means the user deleted those builds: they are retired and their models forgotten. A scene present but a model missing means the user deleted the part: the model is forgotten.
- **PreForm not running** raises `PREFORM_NOT_RUNNING` with a readable message.
- **Recovery** (`recover`, run at start-up): operations left `RUNNING` or `UNCERTAIN` are reconciled. A lost import is matched by name, else retried once. A print submission is never retried; it is flagged for the user.

### Validation and submission (service only)

The service runs the seven PreForm validators, gates submission on blocking results, and requires an explicit acknowledgement of warnings. Any change to the scene clears the acknowledgement. Submission always uses `print_now=False`: a job is queued, never started. The pane does not expose these today.

### HTTP API

Loopback only. Every request carries `Authorization: Bearer <token>`; the token is random per run and is passed to the service through an environment variable, never on the command line. Long operations return `{"operation_id"}` and are polled at `GET /operation/<id>`.

| Route | Purpose |
|---|---|
| `GET /health` | Liveness |
| `POST /connect` | Check the PreForm version, restore builds |
| `POST /send` | Send one body (async) |
| `POST /build/save`, `/build/supports`, `/build/layout`, `/build/validate`, `/build/ack`, `/build/submit` | Build operations (supports, layout, validate and submit are async) |
| `POST /project/save` | Save all dirty builds and write `project.json` |
| `GET /project`, `/builds`, `/printers`, `/jobs` | State |
| `GET /operation/<id>` | Poll an operation |

Errors are `{"app_code", "message", "api_code", "api_message", "operation_id", "build_id", "model_id"}`. Application codes are in `errors.py`.

### PreForm adapter

`sdk_adapter.py` is the only module that imports `formlabs-sdk`. It converts strings to the SDK's enums, wraps SDK errors as `ServiceError`, maps connection failures to `PREFORM_NOT_RUNNING`, and reads raw JSON where PreForm 3.66 omits fields that the 3.64 wheel requires (`list_models`). The rest of the service talks to the `PreformPort` protocol (`ports.py`), which the tests replace with a fake.

## Design decisions worth remembering

| Decision | Reason |
|---|---|
| One build per printer, material, layer and setting | Parts that print together must share all four |
| Export copy and temp part, not output-CS preferences | Preferences do not move the export |
| Save then reopen after a build's first save | Only way to get the real build title into PreForm |
| Supports then layout, after a save | Layout on the unsaved live scene reported "would eject" in every live run; after save and reopen it succeeds |
| Retire builds per session | Parts from an earlier day should not pile into the same build |
| `print_now=False` always | The add-in must never start a print |
