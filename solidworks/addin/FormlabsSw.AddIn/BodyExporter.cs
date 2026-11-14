using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using FormlabsSw.Core;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;

namespace FormlabsSw.AddIn
{
    public sealed class ExportedBody
    {
        public string BodyId;
        public string BodyName;
        public string File;
        public double[][] Transform; // 4x4 (mm) applied to the SOLIDWORKS model coordinates
        // Set for assembly components: each part keeps its own document, configuration and settings.
        public string DocPath, Config;
        public Dictionary<string, string> Cfg;
    }

    /// <summary>
    /// Exports each solid body to its own STEP file (spec §5.1, D-10), baking the print coordinate
    /// system into the geometry by exporting relative to it (Strategy A, D-01, OD-09 default).
    /// </summary>
    public static class BodyExporter
    {
        public static IEnumerable<IBody2> SolidBodies(IPartDoc part) =>
            ((object[])part.GetBodies2((int)swBodyType_e.swSolidBody, true) ?? new object[0]).Cast<IBody2>();

        /// <summary>Selected solid bodies, or every solid body when nothing is selected.</summary>
        public static List<IBody2> Pick(IModelDoc2 doc)
        {
            var mgr = (ISelectionMgr)doc.SelectionManager;
            var picked = new List<IBody2>();
            for (int i = 1; i <= mgr.GetSelectedObjectCount2(-1); i++)
                if (mgr.GetSelectedObject6(i, -1) is IBody2 b && b.GetType() == (int)swBodyType_e.swSolidBody) picked.Add(b);
            return picked.Count > 0 ? picked : SolidBodies((IPartDoc)doc).ToList();
        }

        /// <summary>Stable body id: hash of the persistent reference, falling back to the body name.</summary>
        public static string BodyId(IModelDoc2 doc, IBody2 body)
        {
            try
            {
                var pid = doc.Extension.GetPersistReference3(body) as byte[];
                if (pid != null && pid.Length > 0)
                    using (var sha = SHA256.Create()) return BitConverter.ToString(sha.ComputeHash(pid), 0, 8).Replace("-", "");
            }
            catch { /* fall through to the name */ }
            return "name:" + body.Name;
        }

        /// <summary>
        /// Bakes the print CS into the geometry (Strategy A, D-01): a COPY of each body is moved by the inverse
        /// of the coordinate system's transform and exported from a temporary part. The source document is
        /// never modified. (The output-CS user preferences were tried first and do not shift the export, OD-09.)
        /// </summary>
        public static List<ExportedBody> Export(ISldWorks sw, IModelDoc2 doc, IEnumerable<IBody2> bodies, string exportDir, string printCsName, string format = "STEP", string orientation = "view")
        {
            // No print CS chosen. "same" (default): PreForm X/Y/Z are the SOLIDWORKS model X/Y/Z, so the part has the
            // orientation and XY position it has against the SOLIDWORKS origin/triad (PreForm only drops it onto the platform).
            // "yup": stand a Y-up part up, (x, y, z) -> (x, -z, y). A named coordinate system overrides both.
            IMathTransform toPrint;
            double[][] matrix;
            var math = (IMathUtility)sw.GetMathUtility();
            var viewModel = doc.ActiveView as IModelView;
            if (string.IsNullOrEmpty(printCsName) && orientation == "view" && viewModel != null)
            {
                // What you see is how it lands: the current SOLIDWORKS view orientation, mapped to PreForm axes.
                var rot = ViewOrientation.FromView((double[])viewModel.Orientation3.ArrayData);
                toPrint = (IMathTransform)math.CreateTransform(ViewOrientation.ToSolidWorksArray(rot));
                matrix = ViewOrientation.ToColumn4x4(rot);
            }
            else if (string.IsNullOrEmpty(printCsName) && (orientation == "yup" || orientation == "view"))
            {
                toPrint = (IMathTransform)math.CreateTransform(new double[] { 1, 0, 0, 0, 0, 1, 0, -1, 0, 0, 0, 0, 1, 0, 0, 0 } /* SOLIDWORKS stores the rotation transposed (row-vector convention) */);
                matrix = new[] { new double[] { 1, 0, 0, 0 }, new double[] { 0, 0, -1, 0 }, new double[] { 0, 1, 0, 0 }, new double[] { 0, 0, 0, 1 } };
            }
            else if (string.IsNullOrEmpty(printCsName))
            {
                toPrint = (IMathTransform)math.CreateTransform(new double[] { 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0 });
                matrix = new[] { new double[] { 1, 0, 0, 0 }, new double[] { 0, 1, 0, 0 }, new double[] { 0, 0, 1, 0 }, new double[] { 0, 0, 0, 1 } };
            }
            else
            {
                var csFeature = ((IPartDoc)doc).FeatureByName(printCsName) as IFeature;
                var csData = csFeature?.GetDefinition() as ICoordinateSystemFeatureData;
                if (csData == null)
                    throw new InvalidOperationException("Coordinate system '" + printCsName + "' not found in " + doc.GetTitle());
                toPrint = (IMathTransform)csData.Transform.Inverse();
                matrix = Core.Matrix4.FromSolidWorksMetres((double[])toPrint.ArrayData).ToJagged();
            }
            Directory.CreateDirectory(exportDir);
            string template = sw.GetDocumentTemplate((int)swDocumentTypes_e.swDocPART, "", 0, 0, 0);
            string sourceTitle = doc.GetTitle();
            var result = new List<ExportedBody>();
            foreach (var body in bodies)
            {
                string id = BodyId(doc, body);
                string file = ExportOne(sw, template, sourceTitle, exportDir, format, id, body, toPrint);
                result.Add(new ExportedBody { BodyId = id, BodyName = body.Name, File = file, Transform = matrix });
            }
            return result;
        }

        /// <summary>The print placement of the current view as one transform (view orientation, or standing up).</summary>
        private static IMathTransform ViewTransform(ISldWorks sw, IModelDoc2 doc, string orientation, IMathUtility math)
        {
            if (orientation == "view" && doc.ActiveView is IModelView v)
            {
                var rot = ViewOrientation.FromView((double[])v.Orientation3.ArrayData);
                return (IMathTransform)math.CreateTransform(ViewOrientation.ToSolidWorksArray(rot));
            }
            if (orientation == "same")
                return (IMathTransform)math.CreateTransform(new double[] { 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0 });
            return (IMathTransform)math.CreateTransform(new double[] { 1, 0, 0, 0, 0, 1, 0, -1, 0, 0, 0, 0, 1, 0, 0, 0 });
        }

        /// <summary>
        /// Every part in an assembly, each placed as it sits in the assembly and then as the current view shows it.
        /// Suppressed and hidden components are skipped. Each component instance is its own model in PreForm.
        /// </summary>
        public static List<ExportedBody> ExportAssembly(ISldWorks sw, IAssemblyDoc asm, string exportDir, string format,
            string orientation, Func<IModelDoc2, Dictionary<string, string>> readConfig, Action<string> progress = null)
        {
            var doc = (IModelDoc2)asm;
            var math = (IMathUtility)sw.GetMathUtility();
            var viewXf = ViewTransform(sw, doc, orientation, math);
            Directory.CreateDirectory(exportDir);
            string template = sw.GetDocumentTemplate((int)swDocumentTypes_e.swDocPART, "", 0, 0, 0);
            string sourceTitle = doc.GetTitle();
            var result = new List<ExportedBody>();
            var comps = ((object[])asm.GetComponents(false) ?? new object[0]).Cast<IComponent2>().ToList();
            foreach (var comp in comps)
            {
                if (comp.IsSuppressed() || comp.IsEnvelope() || comp.Visible == (int)swComponentVisibilityState_e.swComponentHidden) continue;
                var part = comp.GetModelDoc2() as IPartDoc;
                if (part == null) continue; // sub-assemblies are walked through GetComponents(false); only parts carry bodies
                var partDoc = (IModelDoc2)part;
                var cfg = readConfig(partDoc);
                var bodies = ((object[])comp.GetBodies3((int)swBodyType_e.swSolidBody, out object info) ?? new object[0]).Cast<IBody2>().ToList();
                int n = 0;
                foreach (var body in bodies)
                {
                    // Bodies come in part coordinates: place by the component's transform in the assembly, then by the view.
                    var placed = (IMathTransform)((IMathTransform)comp.Transform2).Multiply(viewXf);
                    string id = Sanitize(comp.Name2) + "_" + BodyId(partDoc, body);
                    progress?.Invoke("exporting " + comp.Name2);
                    string file = ExportOne(sw, template, sourceTitle, exportDir, format, id, body, placed);
                    string cfgName = comp.ReferencedConfiguration;
                    result.Add(new ExportedBody
                    {
                        BodyId = id, BodyName = comp.Name2 + (bodies.Count > 1 ? " #" + (++n) : ""), File = file,
                        Transform = Core.Matrix4.FromSolidWorksMetres((double[])placed.ArrayData).ToJagged(),
                        DocPath = partDoc.GetPathName(), Config = string.IsNullOrEmpty(cfgName) ? "Default" : cfgName, Cfg = cfg,
                    });
                }
            }
            if (result.Count == 0) throw new InvalidOperationException("The assembly has no visible solid parts to send.");
            return result;
        }

        /// <summary>Copies one body, moves the copy by xf, and exports it from a temporary part. The source is never modified.</summary>
        private static string ExportOne(ISldWorks sw, string template, string sourceTitle, string exportDir, string format,
            string id, IBody2 body, IMathTransform xf)
        {
            string file = Path.Combine(exportDir, Sanitize(id) + (format == "STL" ? ".stl" : ".step"));
            var copy = (IBody2)body.Copy2(true);
            if (copy == null || !copy.ApplyTransform((MathTransform)xf))
                throw new InvalidOperationException("Could not transform a copy of body " + body.Name);
            var temp = (IModelDoc2)sw.NewDocument(template, 0, 0, 0) ?? (IModelDoc2)sw.NewPart();
            try
            {
                if (temp == null)
                    throw new InvalidOperationException("Could not create a temporary part (template '" + template + "')");
                // The return value is unreliable (null even on success); verify the staged solid instead.
                ((IPartDoc)temp).CreateFeatureFromBody3(copy, false, 0);
                if (((object[])((IPartDoc)temp).GetBodies2((int)swBodyType_e.swSolidBody, true) ?? new object[0]).Length == 0)
                    throw new InvalidOperationException("Staging body " + body.Name + " produced no solid");
                int err = 0, warn = 0;
                if (!temp.Extension.SaveAs(file, 0, (int)swSaveAsOptions_e.swSaveAsOptions_Silent, null, ref err, ref warn)
                    || !File.Exists(file))
                    throw new IOException("Export failed for body " + body.Name + " (error " + err + ")");
            }
            finally
            {
                if (temp != null) sw.CloseDoc(temp.GetTitle());
                int e2 = 0;
                sw.ActivateDoc3(sourceTitle, true, (int)swRebuildOnActivation_e.swDontRebuildActiveDoc, ref e2);
            }
            return file;
        }

        private static string Sanitize(string s) => new string(s.Select(c => char.IsLetterOrDigit(c) ? c : '_').ToArray());
    }
}
