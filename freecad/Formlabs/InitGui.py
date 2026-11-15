import os
import sys

import FreeCADGui as Gui

# FreeCAD executes this file without __file__; it has already put the Mod folder on sys.path.
_here = ""
for _p in list(sys.path):  # plain loop: no comprehension, which would not see module names either
    if os.path.isdir(os.path.join(_p, "formlabs_fc")):
        _here = _p
        break


class FormlabsWorkbench(Gui.Workbench):
    MenuText = "Formlabs"
    ToolTip = "Send parts and assemblies to Formlabs PreForm"

    def Initialize(self):
        from formlabs_fc import commands

        commands.register()  # the toolbar and menu are global (see toolbar.py), so they show in every workbench

    def GetClassName(self):
        return "Gui::PythonWorkbench"


# FreeCAD runs this file with separate globals and locals, so a class body cannot see module names: set it here.
FormlabsWorkbench.Icon = os.path.join(_here, "Resources", "formlabs.png")
Gui.addWorkbench(FormlabsWorkbench())

# Visible in Part Design, Assembly and every other workbench: a Formlabs toolbar and menu.
try:
    from formlabs_fc import toolbar as _fl_toolbar

    _fl_toolbar.install()
except Exception as _fl_exc:  # never break FreeCAD start-up
    try:
        import FreeCAD as _fl_app

        _fl_app.Console.PrintError("Formlabs toolbar could not be added: " + str(_fl_exc) + chr(10))
    except Exception:
        pass
