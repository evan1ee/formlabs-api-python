using System;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using FormlabsSw.AddIn;
using SolidWorks.Interop.sldworks;

// Phase 2 style standalone harness (spec section 15): attaches to a running SOLIDWORKS, loads the add-in,
// and exercises the body export outside the add-in UI.
//   Harness load <addin.dll>
//   Harness export <outDir> <printCsName>
internal static class Program
{
    private static int Main(string[] args)
    {
        if (args.Length > 0 && args[0] == "connect") // what the pane's "Connect / refresh" does, without SOLIDWORKS
        {
            try
            {
                Console.WriteLine("project: " + Session.ProjectDir + "  preform: " + Session.PreformExe + "  install: " + Session.InstallDir);
                var c = Session.EnsureStarted();
                Console.WriteLine("service started");
                var r = c.Post("/connect", new System.Collections.Generic.Dictionary<string, object>());
                Console.WriteLine("connect ok: " + string.Join(", ", r.Select(kv => kv.Key + "=" + kv.Value)));
                Console.WriteLine("builds: " + c.Get("/builds").Count + " printers: " + c.Get("/printers").Count);
                return 0;
            }
            catch (Exception ex) { Console.WriteLine("FAILED: " + ex); return 3; }
            finally { Session.Host.Stop(); }
        }
        var sw = (ISldWorks)Marshal.GetActiveObject("SldWorks.Application");
        switch (args.Length > 0 ? args[0] : "")
        {
            case "debugconnect": // run the add-in's own Connect logic inside SOLIDWORKS
                var addin = sw.GetAddInObject("{" + SwAddin.AddInGuid + "}");
                Console.WriteLine(addin == null ? "add-in object not available" :
                    (string)addin.GetType().InvokeMember("DebugConnect", System.Reflection.BindingFlags.InvokeMethod, null, addin, null));
                return 0;
            case "load":
                int status = sw.LoadAddIn(args[1]);
                Console.WriteLine("LoadAddIn status: " + status);
                Console.WriteLine("Add-in object present: " + (sw.GetAddInObject("{" + SwAddin.AddInGuid + "}") != null));
                return 0;
            case "cs": // create a coordinate system at a part vertex (x y z in mm)
                var d = (IModelDoc2)sw.ActiveDoc;
                d.ClearSelection2(true);
                bool picked = d.Extension.SelectByID2("", "VERTEX", double.Parse(args[1]) / 1000, double.Parse(args[2]) / 1000, double.Parse(args[3]) / 1000, false, 1, null, 0);
                Console.WriteLine("vertex selected: " + picked);
                var f = d.FeatureManager.InsertCoordinateSystem(args.Length > 4 && args[4] == "1", args.Length > 5 && args[5] == "1", args.Length > 6 && args[6] == "1");
                Console.WriteLine("coordinate system: " + (f != null ? ((IFeature)f).Name : "FAILED"));
                return f != null ? 0 : 3;
            case "probe": // which mechanism applies the output coordinate system? args: dir csName
                var pd = (IModelDoc2)sw.ActiveDoc;
                Directory.CreateDirectory(args[1]);
                var prefs = new[] { SolidWorks.Interop.swconst.swUserPreferenceStringValue_e.swFileSaveAsCoordinateSystem,
                                    SolidWorks.Interop.swconst.swUserPreferenceStringValue_e.swExportOutputCoordinateSystem };
                foreach (var pref in prefs)
                {
                    bool ok = sw.SetUserPreferenceStringValue((int)pref, args[2]);
                    string back = sw.GetUserPreferenceStringValue((int)pref);
                    int e = 0, w = 0;
                    string f1 = Path.Combine(args[1], pref + "_SaveAs.step");
                    bool r1 = pd.Extension.SaveAs(f1, 0, (int)SolidWorks.Interop.swconst.swSaveAsOptions_e.swSaveAsOptions_Silent, null, ref e, ref w);
                    Console.WriteLine(pref + " set=" + ok + " readback='" + back + "' Extension.SaveAs=" + r1 + " -> " + f1);
                }
                sw.SetUserPreferenceStringValue((int)prefs[0], "");
                sw.SetUserPreferenceStringValue((int)prefs[1], "");
                return 0;
            case "closeothers": // close every open document except the one titled args[1]
                var titles = new System.Collections.Generic.List<string>();
                for (var od = (IModelDoc2)sw.GetFirstDocument(); od != null; od = (IModelDoc2)od.GetNext()) titles.Add(od.GetTitle());
                foreach (var t in titles.Where(t => t != args[1])) { sw.CloseDoc(t); Console.WriteLine("closed " + t); }
                int ae = 0; sw.ActivateDoc3(args[1], true, 0, ref ae);
                return 0;
            case "exit": // close the scratch part without saving, then quit SOLIDWORKS
                foreach (var t in args.Skip(1)) sw.CloseDoc(t);
                sw.ExitApp();
                return 0;
            case "props": // set FL_* custom properties on the active part: material layer printCs
                var pm = ((IModelDoc2)sw.ActiveDoc).Extension.CustomPropertyManager[""];
                pm.Add3("FL_Material", 30, args[1], 2); pm.Add3("FL_Layer", 30, args[2], 2); pm.Add3("FL_PrintCS", 30, args[3], 2);
                Console.WriteLine("properties set");
                return 0;
            case "send": // run the add-in's real Send path synchronously
                var cmd = new SendCommand(sw);
                Console.WriteLine("sent: " + cmd.Execute(Console.WriteLine));
                return 0;
            case "bbox": // body bounding boxes in SOLIDWORKS model coordinates, mm
                var bd = (IModelDoc2)sw.ActiveDoc;
                foreach (var body in BodyExporter.Pick(bd))
                {
                    var bx = (double[])body.GetBodyBox();
                    Console.WriteLine(string.Format("SW body '{0}': x {1:F1}..{2:F1}  y {3:F1}..{4:F1}  z {5:F1}..{6:F1}", body.Name,
                        bx[0] * 1000, bx[3] * 1000, bx[1] * 1000, bx[4] * 1000, bx[2] * 1000, bx[5] * 1000));
                }
                return 0;
            case "viewprobe": // print the view transform for the standard views
                var vd = (IModelDoc2)sw.ActiveDoc;
                foreach (var kv in new[] { ("Front", 1), ("Right", 4), ("Top", 5), ("Isometric", 7) })
                {
                    vd.ShowNamedView2("", kv.Item2);
                    vd.ViewZoomtofit2();
                    var t = ((IModelView)vd.ActiveView).Orientation3;
                    var a = (double[])t.ArrayData;
                    Console.WriteLine(kv.Item1 + ": " + string.Join(" ", a.Take(9).Select(x => x.ToString("F3"))) + "  | t " + string.Join(" ", a.Skip(9).Take(3).Select(x => x.ToString("F3"))) + " s " + a[12].ToString("F3"));
                }
                return 0;
            case "setview": // 1 front, 4 right, 5 top, 7 isometric
                var sv = (IModelDoc2)sw.ActiveDoc; sv.ShowNamedView2("", int.Parse(args[1])); sv.ViewZoomtofit2();
                return 0;
            case "export":
                var doc = (IModelDoc2)sw.ActiveDoc;
                if (!(doc is IPartDoc)) { Console.WriteLine("Active document is not a part"); return 2; }
                var bodies = BodyExporter.Pick(doc);
                Console.WriteLine("Bodies picked: " + bodies.Count);
                foreach (var e in BodyExporter.Export(sw, doc, bodies, args[1], args.Length > 2 ? args[2] : "Coordinate System1"))
                    Console.WriteLine("EXPORTED " + e.BodyId + " " + e.File + " " + new FileInfo(e.File).Length + " bytes");
                return 0;
            default:
                Console.WriteLine("usage: load <dll> | export <dir> [cs]");
                return 1;
        }
    }
}
