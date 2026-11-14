# Changelog

Newest first. Nothing has been released or committed yet; entries are grouped by day of work.

## 2026-11-14

### Added
- Send from an **assembly**: every visible, unsuppressed part in one batch, each placed as in the assembly and then as the view shows it. No need to open the parts.
- **Automatic preparation** after a send: save, generate supports (internal supports off), auto layout. A failure is reported without undoing the send.
- **Material pick-list** limited to Tough 2000 V2, Grey V5, White V5, Clear V5 and Rigid 10K, with a short description of each. Layer is a fixed pick-list.
- **View-based placement**: the part lands in PreForm the way the current SOLIDWORKS view shows it.
- **PreForm icon** for the Task Pane tab and the toolbar button.
- **Resilience**: handles PreForm being restarted, and builds or parts deleted in PreForm. A new session starts a new build.
- `PREFORM_NOT_RUNNING` with a readable message.
- Documentation set: user guide, installation, troubleshooting, architecture, development, verification.

### Changed
- Naming: project `yyyy-mm-dd` (one folder per day); build `yyyy-mm-dd-hh-mm-ss-<material name>`, also the `.form` file name and the title in PreForm. Material codes no longer appear in the UI or in names.
- Send connects to PreForm by itself; there is no Connect step.
- A re-sent, changed part gets fresh supports for the new geometry instead of a rebuild in place.
- The pane is reduced to material and layer, Send, collapsed *More options* and *Project and connection*. The builds list, supports, layout, check, save, acknowledge, queue-to-printer and history sections were removed.
- Saving a build no longer stores a project name in the `.form`, so PreForm titles the build by its file name. After the first save the service continues in the reopened file.
- Default printer Form 4B, default material Tough 2000 V2. The print setting comes from PreForm's catalog.

### Fixed
- Send in an assembly (or any non-part) left the pane on "Sending…" forever; every failure is now reported.
- Auto layout failing with `LAYOUT_WOULD_EJECT` on the unsaved live scene; the build is saved first.
- Send failing after reopening PreForm with "Scene … not found"; and after deleting a build or part in PreForm with "Model … not found".
- Parts landing in an earlier day's build after reopening SOLIDWORKS.
- Builds titled "Untitled Project N" in PreForm.
- Add-in unticking itself (COM class interface), invisible tab and button (missing icons), `FL_*` properties read only per configuration, stuck pane status.

### Verified
See [docs/VERIFICATION.md](docs/VERIFICATION.md). Python tests: 48. Core checks: all pass.

## Earlier

- Phase 0 and Phase 1 of the specification against a live PreForm 3.66.0.1146: scene creation, imports, layout, validators, save and reopen, supports, replace in place, restore.
- Python Integration Service, C# Core, SOLIDWORKS add-in, install packaging, and the SOLIDWORKS harness.
