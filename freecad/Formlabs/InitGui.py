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

        commands.register()
        self.appendToolbar("Formlabs", ["Formlabs_Send", "Formlabs_Panel"])
        self.appendMenu("Formlabs", ["Formlabs_Send", "Formlabs_Panel"])

    def GetClassName(self):
        return "Gui::PythonWorkbench"


# FreeCAD runs this file with separate globals and locals, so a class body cannot see module names: set it here.
FormlabsWorkbench.Icon = os.path.join(_here, "Resources", "formlabs.png")
Gui.addWorkbench(FormlabsWorkbench())
