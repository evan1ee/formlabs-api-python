# User guide

## Before you start

1. PreForm **3.66.0.1146** is running and its server is started. The PreForm window shows "PreForm Server Running on: http://localhost:44388" at the bottom of the side panel.
2. The add-in is ticked in SOLIDWORKS (*Tools > Add-Ins > Formlabs for SOLIDWORKS*). A purple PreForm butterfly tab appears in the Task Pane, and a Formlabs button appears in the toolbar and menu.

You do not need to press any Connect button. Send connects for you.

## Sending a part

1. Open the part. Turn the view the way you want it printed: the part lands in PreForm the way the view shows it. Front stands the part up as you see it; Top lays it down.
2. Open the Formlabs tab.
3. Pick the **Material** and **Layer thickness**.
4. Click **Send active part to Formlabs**.

The status line at the top shows the progress. When it says "Sent N body(ies) to Formlabs. Supports generated and parts laid out.", open PreForm: the build is there with supports and layout done. Check it in PreForm and print from there.

A part with several solid bodies sends each body as its own model. Select bodies first to send only those.

## Sending an assembly

Open the assembly and click Send. Every visible, unsuppressed part is sent in one batch, each placed as it sits in the assembly and then as the view shows it. You do not open the parts one by one.

- Each instance is its own model (`flange-1`, `flange-2`).
- Hidden and suppressed components, and envelope components, are skipped.
- Lightweight components are resolved automatically.
- Each part uses its own `FL_*` properties if it has them, otherwise the pane's choices.

## Sending again

| You did | What happens |
|---|---|
| Nothing changed since the last send | Nothing is sent. The part is reported as unchanged. |
| Moved or turned the part, or edited it | The model is replaced in place in the same build, keeps its lock setting, and gets fresh supports and a new layout. |
| Changed material or layer | The part moves into a build for the new material and layer. |
| Reopened SOLIDWORKS or PreForm | A new session: the first send starts a **new build**. Earlier builds stay on disk but no longer receive parts. |
| Deleted the part in PreForm | It is imported again into the same build. |
| Deleted the whole build in PreForm | The next send makes a new build. |

## Materials

| Material | Use it for |
|---|---|
| **Tough 2000 V2** (default) | Parts that must resist impact and can flex, such as snaps |
| **Grey V5** | Standard parts and fixtures that need no flex or high impact. More brittle, with a better surface finish and dimensional accuracy |
| **White V5** | Like Grey, in another colour |
| **Clear V5** | Like Grey, transparent |
| **Rigid 10K** | Very stiff, glass-filled parts without snaps, only to resist high impact |

Only these five are supported. The add-in shows names everywhere; material codes (for example `FLTO2002`) are internal.

## Naming and where files go

- **Project**: one folder per day, `Documents\Formlabs Projects\yyyy-mm-dd`. All the day's builds share it. A new day starts a new project on the first send. *Project and connection > New project* starts a second one for the same day (`yyyy-mm-dd-2`).
- **Build**: `yyyy-mm-dd-hh-mm-ss-<material name>`. This is the build's title in PreForm and the file name `builds\<name>.form`.
- Exports are kept in `exports\`, the service database is `project.db`, and *Save project* writes `project.json`, a readable list of builds, files and models.

PreForm always keeps one empty starting build named "Untitled Project 1". PreForm refuses to delete it, so it stays. Ignore it or delete it by hand in PreForm.

## More options (collapsed in the pane)

| Option | Meaning |
|---|---|
| Placement in PreForm | *As shown in the SOLIDWORKS view* (default), *Same axes as the SOLIDWORKS model*, or *Stand up (Y up becomes PreForm up)* |
| Freedom in PreForm | The lock set on each imported model: keep orientation and allow moving (default), allow turning around Z and moving, or allow any turning and moving |
| Export format | STEP (default, exact surfaces) or STL (use only if STEP fails) |
| Save these choices into the part's properties | Off by default. When on, Send writes the `FL_*` properties into the part and marks it modified. |

*Project and connection* holds the current project folder, **New project** and **Save project**.

## Part properties (optional overrides)

Set these in *File > Properties > Custom* only when a part needs something different from the pane. Configuration-specific properties win over document-level ones.

| Property | Meaning |
|---|---|
| `FL_Material` | One of `FLTO2002` (Tough 2000 V2), `FLGPGR05` (Grey V5), `FLGPWH05` (White V5), `FLGPCL05` (Clear V5), `FLRG1001` (Rigid 10K). Anything else is refused with a message listing the names. |
| `FL_Layer` | `0.025`, `0.05` or `0.1` |
| `FL_PrintCS` | Name of a coordinate system in the part. The part is exported relative to it, overriding the view-based placement. |
| `FL_Printer` | Machine type, default `FORM-4-0` (Form 4 and Form 4B share it) |
| `FL_PrintSetting` | Print setting code. Empty means PreForm's "Default settings" entry for the material (for Tough 2000 V2 that is `SUPPORTSV1`). |

## What is not in the pane

The pane only prepares and sends. Checking for problems, saving a build, and queuing to a printer are done in PreForm. The Integration Service still has endpoints for them (see the [architecture](ARCHITECTURE.md)), so the buttons can come back.
