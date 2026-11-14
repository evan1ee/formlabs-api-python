# Formlabs for SOLIDWORKS
## Technical Specification: Production PreForm Server Integration

| | |
|---|---|
| **Document version** | 1.1 (revised after review of v1.0) |
| **Date** | 2026-11-13 |
| **Status** | Proposed: decisions confirmed, open items listed in §20 |
| **Target** | SOLIDWORKS 2025 / Formlabs Form 4 / Windows 11 |
| **Primary integration** | Official Formlabs PreForm Server Local API |
| **Pinned API pair** | `formlabs-sdk v1.0.0-alpha.post2` ↔ PreForm Server `3.64.2.3797` (API `v1.0.0-alpha`) |
| **Implementation** | C# .NET Framework 4.8 add-in + Python 3.11+ Integration Service |

> **What changed from v1.0.** Decisions D-01…D-15 (§19) replace the open choices in v1.0. Findings from checking the spec against the SDK are in Appendix A. Sections that changed are marked **[v1.1]**.

---

# 1. Objective

Build a SOLIDWORKS Add-in that lets engineers prepare, validate, manage, and submit Formlabs print jobs directly from SOLIDWORKS. It uses the official **stable PreForm Server** and does not automate the PreForm GUI or depend on Insider builds.

Workflow:

1. Select a SOLIDWORKS Part or Body (Assembly later).
2. Click `Send to Formlabs`.
3. Export the selected geometry with the print orientation baked in (D-01).
4. Select printer, material, and layer thickness (pre-filled from the document, D-11).
5. Add the model to the compatible Build. If the same source was sent before, replace it in place (D-02).
6. Repeat for other documents.
7. Group models automatically into Builds by print configuration.
8. Validate, support, and arrange models, with each step started explicitly by the user.
9. Save the project (one `.form` per Build, D-05).
10. Queue the selected Build to a printer (D-04).

## 1.1 Core design principles

- Use only documented, official Formlabs APIs.
- Keep SOLIDWORKS independent of PreForm implementation details.
- Preserve CAD geometry and orientation deterministically.
- Never silently change a user's explicitly selected print orientation or arrangement.
- Keep Print Project, Build, and Print Job as separate concepts.
- Support multiple CAD documents and multiple materials.
- Never start a physical print without explicit user confirmation. **[v1.1]** Always send `print_now=False` explicitly when queuing.
- Verify the resulting PreForm scene before submission.
- Keep production independent of Insider-only functionality.

# 2. System Architecture

## 2.1 High-level architecture

```text
SOLIDWORKS
  └─ Add-in (C#, .NET 4.8): Ribbon, Task Pane (WPF), selection, export, print CS
        │  HTTP 127.0.0.1:<service port>  + per-session bearer token   [v1.1]
        ▼
Formlabs Integration Service (embedded Python 3.11+, started on demand)   [v1.1]
  Project/Build/Model registry · Config resolver · PreForm adapter (formlabs-sdk)
  Verification & Job manager · SQLite (in project folder)
        │  HTTP 127.0.0.1:44388
        ▼
PreForm Server (pinned build 3.64.2.3797, Managed mode)
        │
        ▼
Formlabs printer (Form 4, local queue)
```

## 2.2 Technology stack

| Component | Technology |
|---|---|
| SOLIDWORKS Add-in | C#, SOLIDWORKS COM Interop, WPF Task Pane + Ribbon, .NET Framework 4.8 |
| Integration Service | **[v1.1]** Embedded CPython 3.11+ distribution (or frozen executable) shipped in the add-in install folder |
| PreForm integration | `formlabs-sdk` (pinned), isolated behind an adapter module |
| Add-in ↔ Service | HTTP on localhost, JSON, per-session token |
| Persistence | SQLite, one database per project folder |
| Model exchange | **[v1.1]** STEP (default), STL (fallback) |
| Print project | Formlabs `.form`, one per Build |

## 2.3 Responsibility boundaries

**C# Add-in**: SOLIDWORKS document access, selection, geometry export, applying the print coordinate system to the export, UI, starting and stopping the service process.
It must not slice, touch PreForm data, contain Formlabs endpoint logic, or block the SOLIDWORKS UI thread.

**Python Integration Service**: Projects, Builds, Models, Jobs; all PreForm communication; configuration resolution; async operation tracking; persistence; verification.

**PreForm Server**: import, supports, layout, printability checks, slicing, upload. Do not reimplement PreForm algorithms.

## 2.4 Service deployment and IPC **[v1.1]** (D-03)

- The service ships as an embedded Python runtime (or a frozen executable) with all dependencies vendored, including the pinned `formlabs-sdk` and `formlabs-preform-api` wheel. No user-installed Python or `pip` is needed.
- The add-in starts the service on first use. The service binds to `127.0.0.1` on a free port.
- At startup the add-in generates a random session token and passes it to the service through an environment variable or stdin (never on the command line). Every request must carry `Authorization: Bearer <token>`; requests without it are rejected.
- The service reports its port back on stdout (one handshake JSON line). The add-in monitors the process and restarts it if it crashes.
- The service shuts down when SOLIDWORKS closes or after an idle timeout, after a safe save (§7.4).
- Long operations are asynchronous: the service returns an operation id and the add-in polls or streams progress.

# 3. PreForm Server Integration

## 3.1 Production runtime

Use the official Windows PreForm Server release. Do not depend on PreForm Insider, GUI scripting, mouse/keyboard automation, or undocumented APIs. The stable PreForm desktop app may be installed alongside the server for manual inspection.

## 3.2 Version management **[v1.1]** (D-08)

- **Exact pin.** The deployment config pins one `(formlabs-sdk version, PreForm Server build)` pair. Currently: `v1.0.0-alpha.post2` ↔ `3.64.2.3797`.
- At startup the service locates the server executable, starts it on the configured port, waits until it is ready, and calls `GET /v1/` (`get_server_version`).
- Any version other than the pinned build is refused with `PREFORM_SERVER_VERSION_UNSUPPORTED`. The error states the expected and found versions and where to download the right build.
- Never upgrade the server silently. A new pair ships only as an add-in update after the integration test suite (§14.2) passes.
- The API is currently **`v1.0.0-alpha`**. Expect breaking changes between pairs. The adapter layer (§3.4) is the only code that may change when the pin changes.

## 3.3 Server lifecycle

- **Managed mode (MVP):** the service starts and owns the PreForm Server process, records its PID, and stops it on shutdown after saving all dirty Builds.
- **Connected mode (later):** attach to an already-running server. Never terminate it. Detect port conflicts (`PREFORM_PORT_IN_USE`) and version mismatches.

## 3.4 API communication

- Base URL `http://127.0.0.1:44388`, endpoints under `/v1/`, localhost only.
- All calls go through a single **adapter module** that wraps `formlabs-sdk`. No other module imports the SDK.
- Explicit timeouts on every call (`timeout=` / `poll_interval=` on async SDK calls).
- Async operations are polled until `SUCCEEDED` or `FAILED`. Operation ids are persisted before polling starts (§12).
- Original API error codes and messages are captured and wrapped, never discarded.
- Retry only idempotent reads (`get_scene`, `list_models`, `get_operation`, `list_print_settings`, `list_devices`). Never blindly retry imports or `print_scene`. A timed-out request may still have executed (§12.2).

# 4. Print Project Data Model

## 4.1 Print Project
Top-level collection of Builds. It lives in a user-chosen **project folder** (D-12):

```text
Documents\Formlabs Projects\<ProjectName>\
  project.db                 SQLite metadata
  builds\<build_id>.form     one .form per Build
  exports\<model_id>\<hash>.step   exported geometry (immutable per hash)
  logs\
```

## 4.2 Build **[v1.1]**
One compatible print configuration, mapped to exactly one PreForm Scene and one `.form` file.

**Build grouping key** = canonical print-setting identity as returned by `list_print_settings`:

```text
machine_type + material_code (versioned, as returned) + layer_thickness_mm + print_setting identity
```

- `print_setting identity` is the canonical identifier or name returned by the catalog. For custom settings saved with `save_print_setting`, it also includes a hash of the setting's parameters.
- Floats in the key are normalized (layer thickness rounded to 0.001 mm) before comparison.
- If the catalog shows that other parameters affect compatibility, the key is extended and the schema is migrated.

## 4.3 Print Job
A submission of a Build to a printer or queue. One Build may produce several Jobs.

## 4.4 Data structures

```python
class PrintProject:
    project_id: str; name: str; folder: str
    created_at: str; updated_at: str; status: str

class Build:
    build_id: str; project_id: str
    machine_type: str; material_code: str
    layer_thickness_mm: float; print_setting: str
    print_setting_fingerprint: str          # [v1.1]
    preform_scene_id: str | None            # session-only, never trusted after restart
    form_file: str                          # builds/<build_id>.form
    dirty: bool                             # [v1.1] unsaved scene changes
    status: str                             # see §8.6
    validation_status: str                  # NOT_RUN | PASSED | WARNINGS_ACKED | BLOCKED

class PrintModel:
    model_id: str; build_id: str
    source_document: str; source_configuration: str
    source_body_name: str | None            # one PrintModel per body (D-10)
    source_identity_key: str                # [v1.1] doc path + config + body persistent id
    source_file: str; source_file_hash: str
    export_format: str                      # STEP | STL
    export_settings: dict                   # units, tolerances, CS used
    import_chordal_tolerance_um: float      # [v1.1] PreForm STEP tessellation
    import_angle_tolerance_deg: float       # [v1.1]
    print_cs_transform: list[list[float]]   # 4x4 baked into geometry (D-01)
    preform_model_id: str | None            # session-only
    preform_fingerprint: dict | None        # [v1.1] bbox/volume after import, for re-identification
    orientation_mode: str; lock_mode: str; status: str

class PrintJob:
    job_id: str; build_id: str
    printer_id: str; job_name: str
    print_now: bool                         # always False in MVP
    form_file_snapshot: str                 # copy of .form at submission
    submitted_at: str | None
    preform_operation_id: str | None
    status: str                             # PENDING | IN_FLIGHT | SUCCEEDED | FAILED | UNKNOWN
    error_code: str | None; error_detail: str | None

class OperationRecord:                      # [v1.1] crash-safe operation journal
    op_id: str; kind: str; build_id: str; model_id: str | None
    preform_operation_id: str | None
    state: str                              # INTENT | SENT | SUCCEEDED | FAILED | UNCERTAIN
    created_at: str; updated_at: str
```

Implementation uses validated models (for example `attrs` or `pydantic`) and versioned SQLite migrations.

# 5. SOLIDWORKS Model Selection and Export

## 5.1 Selection modes
MVP: active Part (all solid bodies), one selected solid body, several selected solid bodies.
Later: Assembly, selected components.

**[v1.1] (D-10)** Each selected body is exported to its **own file** and becomes its own `PrintModel` / PreForm model. A Part with no explicit selection sends each of its solid bodies as a separate model. Body identity uses the SOLIDWORKS persistent reference ID where available, with the body name as fallback.

## 5.2 Export requirements
Each export records: model id, source document path, configuration, body identity, file path, SHA-256 of the file, the 4×4 print CS transform, timestamp, format, units, and export settings. Exports go to `<project>\exports\`. Source CAD files are never written to.

## 5.3 Export format **[v1.1]** (D-06)
- **Default: STEP** (AP214 or AP242, millimeters). PreForm tessellates STEP on import using `chordal_tolerance_um` (SDK default 10.0) and `angle_tolerance_deg` (default 5.0). The service sets both explicitly and records them per model.
- **Fallback: binary STL**, chosen per send or automatically when STEP import fails. The add-in sets STL units (mm), deviation and angle tolerance explicitly and records them.
- STEP and STL are not assumed to give identical geometry. Acceptance tolerances (§6.5) are checked per format.
- Units are always passed explicitly to `import_models(units=...)`. They are never inferred.

# 6. Coordinate System and Orientation

## 6.1 Requirement
Preserve the intended orientation. The SOLIDWORKS screen view is **not** the print orientation.

Modes: (1) model coordinate system, (2) selected SOLIDWORKS coordinate system, (3) explicit print orientation, (4) PreForm auto orientation (only when the user opts in).

## 6.2 Transformation pipeline
SW model coordinates → selected print CS → export coordinates (= PreForm build coordinates, Z up, mm). Homogeneous 4×4 matrices throughout, with no Euler angles exchanged between applications. Documented in code and tests: axis mapping, right-handedness, mm units, origin, rotation order, translation, unit scale.

## 6.3 Orientation strategy **[v1.1]** (D-01)
**Strategy A only: bake the orientation into the exported geometry.**

- The add-in transforms the geometry into the print CS before exporting. In SOLIDWORKS this means exporting relative to the selected coordinate system, or applying a temporary move/copy body transform that is never saved.
- The service imports with the lock already set (`import_models(lock=...)`) and **never calls `orient_models`** for CAD-oriented models.
- `orient_models` / `auto_orient_models` are called only in mode (4), after explicit user opt-in.
- Strategy B (apply the transform through the API) is not implemented. Reason: `import_models` takes no transform, so B needs separate `orient_models` + `translate_models` calls, and the model sits unoriented in between.

## 6.4 Orientation locking **[v1.1]** (D-09)

| User option | PreForm lock | MVP availability |
|---|---|---|
| Preserve orientation, allow translation **(default)** | `LOCKED_ROTATION_FREE_TRANSLATION` | Yes |
| Allow Z rotation and translation | `LOCKED_XY_ROTATION_FREE_TRANSLATION` | Yes |
| Allow rotation and translation | `FREE` | Yes (needed for auto-orient mode) |
| Preserve exact position and orientation | `FULLY_LOCKED` | **Hidden** until open item OD-01 is resolved |

Every layout call also passes `auto_layout_models(lock_rotation=True)` when any model in the Build has a rotation-locked mode. This is belt-and-braces on top of the per-model locks.

## 6.5 Verification
Test matrix: 0°; 45° and 90° about X, Y and Z; combined rotations; a coordinate system away from the origin; inch and mm source documents; STEP and STL; assembly transforms (later).

Acceptance: no unexpected rotation, no scaling, no double transform, bounding-box dimensions within ±0.05 mm (STEP) or within the STL deviation tolerance, and orientation unchanged after `auto_layout_models` (compared through `get_scene` model data or `preform_fingerprint`).

# 7. Multi-Part and Multi-Material Workflow

## 7.1 Incremental add
Every Send adds to the **current** project. New projects are created only through an explicit `New Project` action.

## 7.2 Automatic Build grouping
On Send: resolve config → compute key (§4.2) → find or create Build (create scene via `create_scene` with the resolved print setting) → import → verify the model id and fingerprint → mark Build `dirty`.

## 7.3 Re-send / update of an existing model **[v1.1]** (D-02)
`source_identity_key` = document path + configuration + body persistent id.

| Situation | Action |
|---|---|
| Key not in project | Import as a new model |
| Key exists, same export hash | No-op. Report "unchanged". |
| Key exists, different hash, same Build key | `replace_model` in place, keeping the lock mode. Supports on that model are invalidated (status → `SUPPORTS_STALE`). |
| Key exists, different print config | Delete it from the old Build (`delete_models`) and import it into the new or matching Build. Both Builds are marked dirty. |

Validation status of any affected Build resets to `NOT_RUN`.

## 7.4 Scene management and persistence **[v1.1]** (D-05)
- Every scene call passes an explicit `scene_id`. The default scene is never used.
- **One `.form` per Build** at `builds/<build_id>.form`, written with `save_form_file`.
- Writes are safe: save to `<build_id>.form.tmp`, then rename atomically, keeping one `.bak`.
- Save triggers: explicit Save, before submission, before service shutdown, and after any successful structural change if autosave is on (default on, debounced).
- **Restore:** `open_form_file` per Build → new `scene_id`, then `list_models`. Application `model_id` ↔ new `preform_model_id` are re-mapped by model name (the service names each model `<model_id>` on import) and confirmed with `preform_fingerprint`. Mismatches are reported, never guessed.
- Scene and model ids are never trusted across server restarts.

# 8. Print Preparation Pipeline

```text
Create/Restore Scene → Resolve Config → Import (locked) → [Auto Orient, opt-in]
→ [Generate Supports, user-triggered] → [Auto Layout, user-triggered]
→ Validate → Save .form → User Review → Queue to Printer
```

## 8.1 Import
STEP/STL from SOLIDWORKS (§5.3). Direct native SLDPRT import is out of scope for the MVP. Pass `repair_behavior` explicitly and report any repair to the user.

## 8.2 Orientation
Preserve CAD orientation (default), PreForm auto-orient (explicit opt-in per model; switches the lock to `FREE`), or user-defined orientation through a SOLIDWORKS coordinate system.

## 8.3 Supports **[v1.1]** (D-13)
**Off by default.** The user clicks `Generate Supports` per Build. The dialog shows the `auto_support_models` parameters, and the values used are stored with the Build. `regenerate_supports` is used after `replace_model`. Support removal is listed as OD-04.

## 8.4 Layout **[v1.1]** (D-07)
- `auto_layout_models` is always called with `on_layout_failure` set explicitly to the **non-ejecting** failure mode (exact enum value: OD-03), a fixed `seed` for reproducibility, `lock_rotation` as in §6.4, and an explicit `model_spacing_mm`.
- If layout fails, the operation fails, the service reports which models did not fit, and the scene is restored to its pre-layout state by reloading the last saved `.form`. No auto-save happens in between.
- Never eject models.

## 8.5 Printability **[v1.1]** (D-14)
Checks mapped to the API:

| Check | API | Severity |
|---|---|---|
| Out of build volume | `validate_in_bounds` | **Blocking** |
| Model interference | `validate_interferences` | **Blocking** |
| Non-manifold mesh | `validate_manifoldness` | **Blocking** |
| Thin features | `validate_thin_features` | Warning, needs acknowledgement |
| Unsupported minima | `validate_minima` | Warning, needs acknowledgement |
| Supportedness | `validate_supportedness` | Warning, needs acknowledgement |
| Cups / suction | `validate_cups` | Warning, needs acknowledgement |
| Print setting validity | `validate_print_setting` | **Blocking** |

The UI quotes API wording. A warning is never shown as a confirmed manufacturing failure. Acknowledgements are stored per Build and per validation run, and are cleared by any scene change.

## 8.6 Build status machine **[v1.1]**
`EMPTY → HAS_MODELS → (SUPPORTED) → (LAID_OUT) → VALIDATED | BLOCKED → SAVED → SUBMITTED`. Any model change returns the Build to `HAS_MODELS` and clears validation.

# 9. Material and Print Configuration
- The catalog comes from `list_print_settings`, is cached per server version, and is refreshed when the pinned version changes. Nothing is hardcoded.
- Selections are validated with `validate_print_setting` before `create_scene`.
- Canonical values are persisted, including versioned material codes.
- **[v1.1] (D-11)** The Task Pane picker is pre-filled from SOLIDWORKS **custom properties** on the document/configuration (`FL_Printer`, `FL_Material`, `FL_Layer`, `FL_PrintSetting`). Writing them back on Send changes the document's dirty state, which needs care; see OD-07. If a stored value no longer exists in the catalog, the picker shows it as invalid and Send is blocked (`MATERIAL_NOT_SUPPORTED`).

# 10. Print Submission

## 10.1 MVP target **[v1.1]** (D-04)
**Local printer queue only.** Printers come from `discover_devices` / `list_devices`. The call is `print_scene(scene_id, printer=<serial or IP>, job_name, print_now=False)`.

> `print_now` is **always sent as `False`**. If it is omitted, the printer prints immediately when it is ready, which would break §10.2.

Deferred: Print Now (needs a second confirmation and a `ready_to_print_now` check) and Fleet Control queues (need Dashboard auth through the SDK `auth` module; credentials go to Windows Credential Manager).

## 10.2 Workflow
User selects a Build → printer → job name → `Submit Build to Printer` → confirmation dialog shows printer, material, layer, model count, and any acknowledged warnings → service checks `validation_status ∈ {PASSED, WARNINGS_ACKED}` and that the printer's machine type matches the Build → saves `.form` and keeps a submission snapshot → writes an `OperationRecord(INTENT)` → calls `print_scene` → tracks the operation → reports the result.

## 10.3 Job history
Build, project, printer, material, layer, models, source hashes, `.form` snapshot, timestamps, API result, printer/job id if returned, error details.

# 11. User Interface
Task Pane sections stay as in v1.0 (Project, Add Model, Builds, Preparation, Submit, History), with these changes:
- **[v1.1]** Add Model: lock-mode selector (§6.4), export format (STEP/STL), config picker pre-filled from custom properties.
- **[v1.1]** Submit: queue only. No Print Now control in the MVP.
- **[v1.1]** Builds: shows `dirty`, `SUPPORTS_STALE`, and validation status with acknowledgement controls.
- Long operations run off the UI thread, with progress and cancellation (cancellation = stop waiting plus `delete_operations` where the API supports it; see OD-05). Success is never shown before the server confirms it.

# 12. Error Handling and Recovery

## 12.1 Error codes
As in v1.0, plus:
`SERVICE_START_FAILED`, `SERVICE_AUTH_FAILED`, `MODEL_IDENTITY_MISMATCH`, `OPERATION_STATE_UNCERTAIN`, `LAYOUT_WOULD_EJECT`.
Each error carries `{app_code, api_code, api_message, operation_id, build_id, model_id}`.

## 12.2 Uncertain operations **[v1.1]**
The operation journal (`OperationRecord`) is written **before** each mutating call:
- **Import / replace uncertain** (timeout or crash): on recovery, `list_models` for the scene and match by model name (`<model_id>`). If found, mark it `SUCCEEDED`; otherwise retry once.
- **Print uncertain**: never auto-retry. Mark the Job `UNKNOWN` and ask the user to check the printer queue before resubmitting.
- **Server crash**: restart in Managed mode → restore every Build from `.form` (§7.4) → replay any journal entries in `INTENT` state after the last save, or flag them for the user.

# 13. Security and Reliability
- PreForm Server and the Integration Service bind to `127.0.0.1` only. Port 44388 is never exposed.
- **[v1.1]** Add-in ↔ service calls need the per-session bearer token (§2.4).
- Credentials, when Fleet Control is added later, go in Windows Credential Manager.
- All file paths are validated to stay inside the project folder or the install folder. Source CAD is never written to (except opt-in custom properties, OD-07).
- Structured JSON logs per project. Server and service PIDs are tracked, and processes the service does not own are never terminated.

# 14. Testing Strategy

## 14.1 Unit tests
Python: Build key normalization, config resolution, re-send state table (§7.3), restore re-mapping, journal recovery, error mapping, path validation. The SDK repo's spec-driven stand-in server (`respx` + the OpenAPI schema used in `test_examples.py`) is used for adapter tests.
C#: selection, export settings, 4×4 transform maths, IPC client and token handling, UI state.

## 14.2 Integration tests (real pinned PreForm Server)
As in v1.0, plus: **[v1.1]** `print_now=False` actually queues; layout with the non-ejecting failure mode leaves the scene unchanged on failure; locked models keep their orientation through `auto_layout_models`; `replace_model` keeps the lock; restore re-mapping after a server restart; OD-01 position test.

## 14.3 Acceptance tests
AT-01…AT-15 as in v1.0, plus:

| ID | Requirement | Expected |
|---|---|---|
| AT-16 | Re-send an unchanged part | No-op, no duplicate |
| AT-17 | Re-send a changed part | Replaced in place, lock kept, validation reset |
| AT-18 | Layout cannot fit all models | Failure reported, no model ejected, scene unchanged |
| AT-19 | Queue submission with printer ready | Job is queued, not started |
| AT-20 | Wrong server version installed | Refused with expected and found versions |
| AT-21 | Multi-body part | One PreForm model per body |

# 15. Development Roadmap

| Phase | Scope | Exit criteria |
|---|---|---|
| **0** Stable server PoC | Python only, pinned pair. Start server, version check, Form 4 scene, STEP import with lock, supports, all §8.5 validations, save/reopen `.form`, `print_now=False` dry run to a test printer. **Resolve OD-01, OD-02, OD-03.** | All essential operations work; open items answered |
| **1** Multi-model / multi-Build | Project/Build/Model registry, SQLite, grouping, re-send logic, journal, restore re-mapping | Multiple parts and materials managed and restored after a server restart |
| **2** Orientation | **[v1.1]** Standalone C# console harness (not the add-in) using SOLIDWORKS API for CS extraction and baked STEP/STL export, plus the transform test matrix | §6.5 passes for the full matrix |
| **3** Add-in MVP | Registration, ribbon, Task Pane, embedded service lifecycle and token, Send for Part/Bodies | Engineer sends several parts into one project |
| **4** Preparation | Pickers, supports, layout, validation gating, review, save | A Build is prepared without opening PreForm |
| **5** Submission | Device discovery, queue submission, operation tracking, history | Verified Build queued from SOLIDWORKS |

Phase 3 does not start until Phases 0 and 1 have shown the stable server workflow working.

# 16. Out of Scope for MVP
Custom slicing or support engines, firmware communication, cloud multi-user projects, cost optimization, unverified feasibility rules, replacing PreForm desktop, GUI automation. **[v1.1]** Also deferred: Print Now, Fleet Control queues, Connected mode, Assemblies, Strategy B, `FULLY_LOCKED` (until OD-01), native SLDPRT import.

# 17. Official References
- PreForm API reference (pinned version): https://developer.formlabs.com/api-reference/v1.0.0-alpha/
- Headless PreForm Server: https://developer.formlabs.com/guides/headless-preform-server/
- Downloads and release notes: https://formlabs.com/support/Formlabs-API-downloads-and-release-notes/
- Python SDK: https://github.com/Formlabs/formlabs-api-python (tag `v1.0.0-alpha.post2`)
- CLI options: https://developer.formlabs.com/resources/preform-server-cli/
- Install: https://developer.formlabs.com/getting-started/install/

# 18. Implementation Rules
1. The stable PreForm Server (pinned pair) is the only production target.
2. Do not assume the GUI exposes Insider scripting.
3. No GUI automation.
4. Documented endpoints only, accessed through the adapter module.
5. No hardcoded catalogs.
6. Scene and model ids never survive restarts.
7. Never mix print configurations in one Build.
8. Never silently alter a CAD-defined orientation. Never call `orient_models` on CAD-oriented models.
9. Never print without approval. **Always send `print_now=False`.**
10. No Phase 3 before Phases 0 and 1 are demonstrated.
11. Unverified capabilities go in §20, not into code.
12. Thin C# add-in. Formlabs logic lives in the service.
13. **[v1.1]** Always set `on_layout_failure` explicitly to a non-ejecting mode.
14. **[v1.1]** Write the operation journal before every mutating call.

**Definition of Done:** an engineer can select multiple SOLIDWORKS Parts and bodies, send them incrementally into a persistent print project, have them grouped automatically into compatible Builds, keep their baked orientations under lock, prepare and validate each Build through the pinned stable PreForm Server, and queue a selected Build to a Formlabs printer with explicit confirmation.

---

# 19. Decision Log **[v1.1]**

| ID | Decision | Section |
|---|---|---|
| D-01 | Orientation Strategy A only (bake into export, import locked, no `orient_models`) | §6.3 |
| D-02 | Re-send: identity + hash; no-op if unchanged, `replace_model` in place if changed, lock kept | §7.3 |
| D-03 | Service = embedded Python / frozen exe, started on demand, localhost + per-session token | §2.4 |
| D-04 | MVP submission = local printer queue only, `print_now=False` always | §10.1 |
| D-05 | One `.form` per Build; SQLite maps build ↔ file ↔ model fingerprints | §7.4 |
| D-06 | STEP default (tessellation tolerances recorded), STL fallback | §5.3 |
| D-07 | Layout failure: fail, report, change nothing, never eject | §8.4 |
| D-08 | Exact version pin of the SDK + server build pair; refuse anything else | §3.2 |
| D-09 | Default lock `LOCKED_ROTATION_FREE_TRANSLATION`; `FULLY_LOCKED` hidden until OD-01 | §6.4 |
| D-10 | One PreForm model per selected body | §5.1 |
| D-11 | Config picker pre-filled from SOLIDWORKS custom properties | §9 |
| D-12 | User-chosen project folder (default `Documents\Formlabs Projects\<name>`) | §4.1 |
| D-13 | Supports off by default; user-triggered with visible settings | §8.3 |
| D-14 | Block on API errors; warnings need explicit acknowledgement | §8.5 |
| D-15 | Revised spec kept in `docs/specs/` | — |

# 20. Open Decisions / Unverified Capabilities **[v1.1]**

| ID | Question | Resolve in | Default until resolved |
|---|---|---|---|
| OD-01 | Does `import_models` keep the CAD XYZ position, or does PreForm move the model onto the platform or recentre it? | Phase 0 test | `FULLY_LOCKED` hidden; translation allowed |
| OD-02 | Exact `lock` string values accepted by `import_models` / `update_models` in API v1.0.0-alpha (the SDK types it as `str`) | Phase 0, API reference | Use the documented enum names in §6.4 |
| OD-03 | Exact non-ejecting `OnLayoutFailure` enum value | Phase 0, SDK enum | Treat as blocking: no layout without it |
| OD-04 | Is there a documented "remove supports" operation? | Phase 0 | Regenerate only; removal deferred |
| OD-05 | Does `delete_operations` cancel a running operation or only forget it? | Phase 0 | Cancellation = stop waiting, result reconciled later |
| OD-06 | Does `print_scene` return a printer-side job id? | Phase 0/5 | Store the operation id only |
| OD-07 | Writing `FL_*` custom properties dirties the SOLIDWORKS document. Write on Send, or only read? | Phase 3 UX review | Read-only, plus a per-user remembered default |
| OD-08 | Does `split_multi_model_file` give a better route for multi-body STEP than one file per body? | Phase 2 | One file per body (D-10) |
| OD-09 | SOLIDWORKS-side method for baking the print CS: export with output coordinate system vs a temporary transform | Phase 2 | Output coordinate system option |

---

# Appendix A: Review Findings Against `formlabs-sdk v1.0.0-alpha.post2`

| # | v1.0 statement | Finding | Resolution |
|---|---|---|---|
| A1 | §10.2 never auto-print | `print_scene`: omitting `print_now` defers to the printer's `ready_to_print_now`, so it prints immediately if ready | Always send `print_now=False` (D-04, rule 9) |
| A2 | §8.4 do not silently eject | `auto_layout_models(on_layout_failure=EJECT_A_MODEL_AND_RETRY, max_ejections=…)` exists | Explicit non-ejecting mode (D-07, rule 13) |
| A3 | §6.3 Strategy B "apply transform through API" | `import_models` has no transform parameter. A transform needs `orient_models(TransformMatrix)` + `translate_models` after import | Strategy A only (D-01) |
| A4 | §3.1 "stable" production API | Pinned API is `v1.0.0-alpha`; the SDK pins PreForm `3.64.2.3797` | Exact pin of the pair (D-08) |
| A5 | §7.4 ".form may contain multiple scenes" | `open_form_file` / `save_form_file` work one scene at a time | One `.form` per Build (D-05) |
| A6 | §5.3 STL for tessellation control | STEP import takes `chordal_tolerance_um` / `angle_tolerance_deg` | STEP default, tolerances recorded (D-06) |
| A7 | §6.4 locks only per model | `auto_layout_models(lock_rotation=True)` overrides per-model locks | Also used as belt-and-braces (§6.4) |
| A8 | §8.5 generic "printability checks" | Specific validators exist (in_bounds, interferences, manifoldness, thin_features, minima, supportedness, cups, print_setting) | Mapped with severities (D-14) |
| A9 | No re-send semantics | `replace_model` exists | D-02 |
| A10 | No service deployment or IPC security | Unauthenticated localhost endpoint can be reached by any local process | D-03 token |
| A11 | Phase 2 needs SOLIDWORKS code before Phase 3 | Contradicts "no add-in before Phase 3" | Phase 2 uses a standalone console harness |
| A12 | Layout determinism not specified | `seed` gives reproducible layouts | Fixed seed per Build (§8.4) |
