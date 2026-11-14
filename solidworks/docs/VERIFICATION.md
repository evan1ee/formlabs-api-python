# Verification

What has been tested for real, what has only been tested against a fake, and what is still open. Dates are 2026-11-14 unless noted. Environment: Windows 11, SOLIDWORKS 2025 (33.0), PreForm 3.66.0.1146 beta hosting its server in the GUI, no printer touched.

## Automated tests

| Suite | Count | Covers |
|---|---|---|
| `service/tests` (pytest, fake PreForm port) | 48 | Version pin, build grouping, re-send table, one model per body, `.form` save and restore re-map, journal and recovery, autosave, layout rules, validation gating, submission rules, HTTP API and token, naming, session retirement, PreForm restart, deleting builds and models in PreForm |
| `addin/FormlabsSw.Core.Tests` | 16 checks | Matrix maths, rigid-transform validation, view-to-PreForm orientation, HTTP client token and error mapping |

## Verified against a live PreForm 3.66.0.1146

`service/scripts/phase0_check.py` and `phase1_check.py` pass end to end: scene creation, STL and STEP import with each lock string, non-ejecting layout, all seven validators, save, reopen, supports, replace in place keeping the lock, unchanged re-send as a no-op, restore and remap by name, `save_project`.

Findings recorded in the adapter and the docs:

- The SDK needs `ImportUnits`, `RepairBehavior` and `OnLayoutFailure` enums, not strings. `validate_in_bounds` and `validate_interferences` take no poll arguments. `open_form_file` returns `{"project_name", "scenes": [{"scene_id", "scene_name", "new_model_ids", ...}]}`.
- 3.66 omits `is_group`, so typed `list_models` and `list_scenes` fail; raw JSON is used.
- Regenerating supports on a model with none is rejected.
- A scene saved with a project name reopens with an empty `scene_name` (titled "Untitled Project N"); saved without one, `scene_name` is the file stem.
- Deleting PreForm's starting blank scene returns success and has no effect.
- Layout of the unsaved live scene returned `LAYOUT_WOULD_EJECT` in four of four runs; after save and reopen it succeeded in every run.

## Verified inside SOLIDWORKS 2025

Run with `addin/FormlabsSw.Harness` against a SolidPilot-launched SOLIDWORKS, with the add-in's own code and the installed Python service.

| Check | Result |
|---|---|
| Registration (`regasm /codebase`, elevated) and `LoadAddIn` | Works; interop DLLs must sit beside the add-in |
| Add-in loads, Task Pane builds, icons appear | Works (PreForm butterfly icon) |
| Send of a part: export, import, save, supports, layout | Build `…-Tough-2000-V2` reached `LAID_OUT`, journal `SUCCEEDED` for import, supports and layout |
| Naming | `yyyy-mm-dd-hh-mm-ss-<material name>`; the title read back from PreForm equals the name on a clean PreForm |
| Orientation by view | Front view: 18 x 18 x 31.7 mm, standing. Top view: 18 x 31.8 x 18 mm, lying along Y |
| OD-09: baking a coordinate system | Output-CS preferences do not shift exports; the copy-and-transform export does. A CS 10 mm off in Y shifts Y by 10 mm; a CS with X flipped gives a proper 180 degree rotation with dimensions preserved |
| Body ids | Identical across three runs |
| Assembly | Two instances of one part, one at the origin and one 80 mm to the side, were both sent in one click into one build, the second at x 71..89 mm against the first at -9..9 mm, supports and layout done |
| Re-send after moving the part (view changed) | Replaced or moved into the current build, supports and layout done |
| Send after PreForm restart | Builds reopen or reimport; new session starts a new build |
| Send after deleting the part or the build in PreForm | New import; new build for a deleted build |

## Not verified

- **The Task Pane buttons clicked by a person.** The Send command and the service were driven through the harness. The pane's layout, the disabled-while-busy behaviour and the status messages have only been seen by the user in their own session.
- **Add-in auto-load at SOLIDWORKS start-up** in a normal launch (the add-in loads when ticked and stays ticked in the user's session; a cold start has not been logged).
- **Real print submission.** The pane has no submit button. The service's `/build/submit`, printer matching and `UNKNOWN` job state are tested against the fake port only. A printer was never sent a job.
- **Visual correctness of supports after a re-send.** The service regenerates supports with `auto_support_models` for replaced models; both that and the older "regenerate" call ran without errors and PreForm reports supports present either way, so the difference was not measurable from data.
- **Rotations other than the views tried** (Front, Top, isometric on paper; 45 and 90 degree turns about each axis, combined rotations, inch documents, STL export).
- **Assemblies with nested sub-assemblies, hidden or suppressed components**, mates that move components, and very large assemblies.
- **A PreForm other than 3.66.0.1146.** The version pin refuses it.
- **Several users or machines**, and a SOLIDWORKS other than 2025.

## Open decisions from the specification

| ID | Question | State |
|---|---|---|
| OD-01 | Does the import keep position? | Resolved: XY kept, Z dropped onto the platform. `FULLY_LOCKED` stays hidden. |
| OD-02 | Are all lock strings accepted at import? | Resolved: yes, `FULLY_LOCKED` too |
| OD-03 | Layout failure behaviour | Resolved: `FAIL_AND_LEAVE_SCENE_UNCHANGED` from the SDK enum |
| OD-04, OD-05, OD-06 | Behaviour of long operations, cancellation and printing | **Open**: needs a printer or a long-running operation. Cancel in the pane only stops waiting. |
| OD-07 | Write `FL_*` properties back into the part | Opt-in checkbox, off by default; marks the document modified |
| OD-09 | How to bake a coordinate system into the export | Resolved: copy, transform, export from a temporary part |

## Known limitations

- PreForm's blank starting build cannot be removed through the API.
- The Task Pane cannot rename a build after it exists; the name is fixed at creation.
- Models in PreForm carry internal ids as names; the service relies on them for re-send matching.
- One instance of the add-in per SOLIDWORKS session; one service per session.
