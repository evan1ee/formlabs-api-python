# Troubleshooting

## Where to look

| What | Where |
|---|---|
| Add-in log (start-up steps, send results, full stack traces) | `%LOCALAPPDATA%\FormlabsSw\addin.log` |
| Project files and the operation journal | `Documents\Formlabs Projects\<yyyy-mm-dd>\` (`project.db`, `builds\`, `exports\`, `logs\`) |
| PreForm Server | `http://localhost:44388` (shown at the bottom of PreForm's side panel) |

The status line at the top of the Formlabs pane shows the last result. Failures read `Send failed: <CODE>: <message>`.

## Add-in and pane

| Symptom | Cause and fix |
|---|---|
| The add-in is listed but unticks itself or does not load | Check `addin.log`. The COM class must use `ClassInterfaceType.AutoDispatch`; a broken registration needs `regasm /codebase` again from an elevated shell. |
| No Formlabs tab or toolbar button | Icons are mandatory. Check that `Icons\formlabs_20/32/40/64/96/128.png` exist beside the DLL. |
| "The add-in is not connected to SOLIDWORKS." | The add-in did not finish loading. Untick and tick it again, then see `addin.log`. |
| Status stays on "Sending…" | Press **Stop waiting**. This used to happen when the active document was not a part; assemblies are now supported and any failure is reported. If it still hangs, send me the end of `addin.log`. |
| Cannot replace the add-in DLL | SOLIDWORKS has it locked. Close SOLIDWORKS first. See [Updating](INSTALL.md#updating). |

## Errors shown after Send

| Message | Meaning and fix |
|---|---|
| `PREFORM_NOT_RUNNING` – PreForm is not running or its server is not started | Start PreForm 3.66.0.1146 and its server, then send again. |
| `SERVICE_START_FAILED` | The service could not start or attach. Read the quoted reason: usually PreForm is not running, or `PreformExe` is empty (it must be `connect` or a valid path). |
| `PREFORM_SERVER_VERSION_UNSUPPORTED` | The running PreForm is not 3.66.0.1146. Install and start that build. |
| `PREFORM_API_ERROR: INPUT_ERROR: Scene with given scene_id not found` / `Model … not found in scene` | PreForm was restarted, or you deleted the build or part in PreForm. This is handled automatically on the next send. If you still see it, close and reopen SOLIDWORKS so the service starts clean. |
| `MATERIAL_NOT_SUPPORTED` | The material and layer have no matching print setting in PreForm's catalog. Pick another layer thickness, or check `FL_PrintSetting`. |
| `Unsupported FL_Material …` | A part's `FL_Material` is not one of the five supported codes. Fix or delete the property. |
| `LAYOUT_WOULD_EJECT` (shown as "Auto layout could not be done") | The parts do not fit the build volume. The scene was left unchanged. Reduce the number of parts per build, or rearrange in PreForm. The send itself still succeeded. |
| "Supports could not be generated (…)" | Send succeeded but supports failed. Layout is skipped. Generate supports in PreForm. |
| "The assembly has no visible solid parts to send." | Every component is hidden, suppressed or has no solid body. |
| `Coordinate system '…' not found` | `FL_PrintCS` names something that is not in the part. |
| `PRINTER_MISMATCH` | The chosen printer does not match the build's machine type (service submit only). |

## PreForm behaviours you may notice

- **"Untitled Project 1" with 0 models.** PreForm's own starting build. Its API reports a successful delete but keeps the scene, so it cannot be removed automatically. Delete it by hand if it bothers you.
- **A build titled "Untitled Project N" instead of its name.** PreForm titles a scene opened from a file by the file name, but only if the file has no stored project name. The add-in never stores one. A PreForm session that was used with other tools can carry a project name over and then titles builds "Untitled". **Restart PreForm** and send again.
- **The top title bar still says "Untitled Project N".** That is PreForm's own project name, which the API cannot set.
- **Model names look like `4938d0f45b33`.** The service names each PreForm model with its internal id and uses that to recognise it on re-send. Renaming models in PreForm breaks that link for the renamed model, which is then imported again.
- **Earlier builds disappeared from the active list or a new build appeared.** By design, a new session (reopening SOLIDWORKS or PreForm) starts a new build. Earlier builds stay on disk.

## Orientation looks wrong

The part lands as the **current SOLIDWORKS view** shows it. Set the view first (Front, Top, a custom rotation), then send. Alternatives are in *More options > Placement in PreForm*, and `FL_PrintCS` overrides all of them. If a re-send does not move the part in PreForm, the exported geometry was identical, which counts as unchanged.

## Collecting information for a bug report

1. The status line text.
2. The last 30 lines of `%LOCALAPPDATA%\FormlabsSw\addin.log`.
3. The PreForm version and whether its server was started before SOLIDWORKS.
4. Whether it was a part or an assembly, and how many components.
