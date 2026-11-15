import os

import FreeCADGui as Gui

_here = os.path.dirname(os.path.abspath(__file__))


class FormlabsWorkbench(Gui.Workbench):
    MenuText = "Formlabs"
    ToolTip = "Send parts and assemblies to Formlabs PreForm"
    Icon = os.path.join(_here, "Resources", "formlabs.png")

    def Initialize(self):
        import sys

        if _here not in sys.path:
            sys.path.insert(0, _here)
        from formlabs_fc import commands

        commands.register()
        self.appendToolbar("Formlabs", ["Formlabs_Send", "Formlabs_Panel"])
        self.appendMenu("Formlabs", ["Formlabs_Send", "Formlabs_Panel"])

    def GetClassName(self):
        return "Gui::PythonWorkbench"


Gui.addWorkbench(FormlabsWorkbench())
