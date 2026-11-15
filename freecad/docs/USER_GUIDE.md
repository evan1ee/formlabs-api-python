# Formlabs for FreeCAD: user guide

Sends parts and assemblies from FreeCAD to **PreForm** with one click. It does the same job as the SOLIDWORKS add-in and uses the same Integration Service, so builds, names and behaviour match.

## Install

1. Download `FormlabsFreeCAD-<version>-win64.zip` from the GitHub Releases page (`freecad-v*` tags) and check it against `SHA256SUMS-freecad.txt`.
2. Unpack it, close FreeCAD, right-click `Install-FormlabsFreeCAD.ps1` and choose *Run with PowerShell*. No administrator rights are needed.
3. Start PreForm **3.66.0.1146** and start its server (File, Start PreForm Server).
4. Start FreeCAD 1.0 or newer and choose the **Formlabs** workbench.

Uninstall with `Uninstall-FormlabsFreeCAD.ps1`. Your projects are kept.

The installer copies the workbench to `%APPDATA%\FreeCAD\Mod\Formlabs` and to every versioned folder such as `%APPDATA%\FreeCADv1-1\Mod\Formlabs` (FreeCAD 1.1 reads the versioned one).

Manual install: copy the `Formlabs` folder to `%APPDATA%\FreeCAD\Mod\` (and `v1-1\Mod\` for FreeCAD 1.1) and point `FL_INSTALL_DIR` at a folder that holds `python\python.exe` and the vendored service (for example the SOLIDWORKS install folder).

## Use

1. Open the **Formlabs panel** (toolbar button, or *Formlabs > Formlabs panel*).
2. Choose a **material** and **layer**. Defaults: Tough 2000 V2, 0.1 mm. The printer is Form 4B.
3. Select the solids to send, or select nothing to send every visible solid. Assemblies (`App::Part` containers and links) are sent part by part, each at its assembly position.
4. Click **Send to Formlabs**.

The part lands in PreForm the way the 3D view shows it. After the import the add-on saves the build, generates supports (internal supports off) and runs auto layout. A failure there is reported in the status line and does not undo the send.

| Material | Use |
|---|---|
| Tough 2000 V2 | Parts that resist impact and flex: snaps and clips. |
| Grey V5 | Standard parts and fixtures; stiffer and more brittle, better finish and accuracy. |
| White V5 | Like Grey V5, in white. |
| Clear V5 | Like Grey V5, transparent. |
| Rigid 10K | Very stiff glass-filled parts without snaps. |

### Names

A project is one folder per day, `yyyy-mm-dd`, in `Documents\Formlabs Projects`. Each build is `yyyy-mm-dd-hh-mm-ss-<material name>`, for example `2026-11-15-09-30-12-Tough-2000-V2`. A new FreeCAD or PreForm session starts a new build.

### Re-send

Move or turn a part and send again: it is replaced in place and gets fresh supports. Sending an unchanged part does nothing.

### More options

*Placement* (as the view shows it, same axes as FreeCAD, or stand a Y-up part up), *Freedom* (what PreForm may do with the part) and *Export format* (STEP, or STL as a fallback). *Project and connection* shows the project folder and starts a second project for the day.

## Troubleshooting

| Message | What to do |
|---|---|
| PreForm is not running | Start PreForm and its server, then send again. |
| PREFORM_SERVER_VERSION_UNSUPPORTED | Only PreForm 3.66.0.1146 is supported. |
| missing runtime ... python.exe | The runtime is not installed. Run the installer, or set `FL_INSTALL_DIR`. |
| There is no visible solid to send | Show a part or select one. |

Settings live in `%APPDATA%\Formlabs\FreeCAD\settings.json`. The service log is in the project folder.

## Differences from the SOLIDWORKS add-in

- Nothing is read from custom properties; material and layer come from the panel.
- Part identity is the object name inside the document, so renaming an object makes it a new part in PreForm.
- Unsaved documents are identified as `unsaved:<name>`; save the document for stable identity across sessions.
