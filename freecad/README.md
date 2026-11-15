# Formlabs for FreeCAD

A FreeCAD workbench with the same job as the [SOLIDWORKS add-in](../solidworks/README.md): one click sends the selected solids, or every visible solid of a part or assembly, to PreForm; it places them as the view shows them, then generates supports and lays the build out.

It talks to the shared Integration Service (`solidworks/service`, Python, loopback HTTP) so naming, re-send, resilience and PreForm handling are identical to the SOLIDWORKS version.

```
freecad/
  Formlabs/               the FreeCAD Mod folder (package.xml, Init.py, InitGui.py)
    formlabs_fc/          constants, settings, client, host, orientation, exporter, send, panel, commands
  tests/                  pytest: maths, settings, exporter (stand-in objects), send flow against the real service
  packaging/              make_release.ps1, Install/Uninstall scripts
  docs/USER_GUIDE.md
```

Feature parity with the SOLIDWORKS version: five materials with descriptions, Form 4B, layer list, view-based placement, assemblies in one batch, automatic supports (internal off) then layout, day project and time-stamped build names, re-send updates supports, PreForm restart or deleted builds handled by the service, one-click panel with collapsed options.

```bash
cd freecad && python -m pip install pytest && python -m pytest      # needs solidworks/service importable (its deps: pip install -e ../solidworks/service)
```

Status: verified in FreeCAD 1.1 with a real window and a running PreForm 3.66.0.1146. `start_send` exported a box, the service imported it, generated supports (internal off) and laid it out ("Supports generated and parts laid out"), and a build named `yyyy-mm-dd-hh-mm-ss-Grey-V5` was saved. With the Right view active the 30 x 20 x 10 mm box was exported as 20 x 30 x 10, the orientation the view shows. Camera orientation reads correctly for Front, Top, Right and Isometric. Also checked: panel, commands, assemblies and links with global placement, `Cut` inputs, STEP and STL. Not checked: a mouse click on the Send button, and re-send, restart and deletion handling (these come from the shared service, which the SOLIDWORKS tests cover). Offscreen FreeCAD (`QT_QPA_PLATFORM=offscreen`) does not update the camera, so view placement needs a real window. Releases are built by the `freecad-v*` tag workflow.
