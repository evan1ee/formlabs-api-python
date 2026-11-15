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

Status: logic and the full send flow are tested against the real service. **The FreeCAD GUI layer (workbench, panel, view camera, shape export) has not yet been run inside FreeCAD**; this is the main remaining risk. Releases are built by the `freecad-v*` tag workflow.
