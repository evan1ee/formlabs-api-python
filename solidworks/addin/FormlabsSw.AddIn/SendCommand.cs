using System;
using System.Collections.Generic;
using System.IO;
using System.Threading.Tasks;
using System.Windows.Forms;
using FormlabsSw.Core;
using SolidWorks.Interop.sldworks;

namespace FormlabsSw.AddIn
{
    /// <summary>
    /// "Send to Formlabs": export bodies on the UI thread (COM), then talk to the service off-thread so
    /// SOLIDWORKS never blocks (spec §2.3, §11). Config comes from FL_* custom properties (D-11, read-only: OD-07).
    /// </summary>
    public sealed class SendCommand : IDisposable
    {
        private readonly ISldWorks _sw;
        public SendCommand(ISldWorks sw) { _sw = sw; }

        private sealed class Prepared
        {
            public string ProjectDir, DocPath, Config;
            public Dictionary<string, string> Cfg;
            public List<ExportedBody> Bodies;
        }

        public void Run(Action<string> onDone = null)
        {
            try
            {
                var prepared = Prepare(null); // SOLIDWORKS COM work stays on the UI thread
                Task.Run(() => Dispatch(prepared)).ContinueWith(t =>
                {
                    string text = t.IsFaulted
                        ? "Send failed: " + t.Exception.GetBaseException().Message
                        : "Sent " + t.Result + " body(ies) to Formlabs." + _supportNote;
                    SwAddin.Log(text);
                    if (onDone != null) onDone(text); // the Task Pane shows it in its status line
                    else _sw.SendMsgToUser2(text, (int)SolidWorks.Interop.swconst.swMessageBoxIcon_e.swMbInformation,
                        (int)SolidWorks.Interop.swconst.swMessageBoxBtn_e.swMbOk);
                });
            }
            catch (Exception ex)
            {
                string text = "Send failed: " + ex.Message;
                SwAddin.Log(text + System.Environment.NewLine + ex);
                if (onDone != null) onDone(text); else MessageBox.Show(ex.Message, "Formlabs");
            }
        }

        /// <summary>Synchronous send (export + service calls). Returns the number of bodies sent. Used by the test harness.</summary>
        public int Execute(Action<string> log) => Dispatch(Prepare(log));

        private Prepared Prepare(Action<string> log)
        {
            var doc = _sw.ActiveDoc as IModelDoc2;
            if (doc == null || !(doc is IPartDoc || doc is IAssemblyDoc)) throw new InvalidOperationException("Open a part or an assembly first.");
            var cfg = ReadConfig(doc);
            string projectDir = Session.ProjectDir;
            string staging = Path.Combine(projectDir, "exports", "staging");
            List<ExportedBody> bodies;
            if (doc is IAssemblyDoc asm)
            {
                // Every part of the assembly goes in one batch; nothing has to be opened part by part.
                asm.ResolveAllLightweight();
                bodies = BodyExporter.ExportAssembly(_sw, asm, staging, Session.ExportFormat, Session.Orientation, ReadConfig,
                    name => log?.Invoke(name));
            }
            else
            {
                bodies = BodyExporter.Export(_sw, doc, BodyExporter.Pick(doc), staging, cfg["FL_PrintCS"], Session.ExportFormat, Session.Orientation);
                if (Session.WriteBackProperties) WriteBack(doc, cfg);
            }
            log?.Invoke("exported " + bodies.Count + " body(ies)");
            return new Prepared
            {
                ProjectDir = projectDir, DocPath = doc.GetPathName(), Cfg = cfg, Bodies = bodies,
                Config = doc.ConfigurationManager.ActiveConfiguration.Name,
            };
        }

        private string _supportNote = "";

        private int Dispatch(Prepared p)
        {
            _supportNote = "";
            SendAll(p.ProjectDir, p.DocPath, p.Config, p.Cfg, p.Bodies);
            return p.Bodies.Count;
        }

        /// <summary>Opt-in (OD-07): persists the FL_* picks on the document; this marks it modified.</summary>
        private static void WriteBack(IModelDoc2 doc, Dictionary<string, string> cfg)
        {
            var mgr = doc.Extension.CustomPropertyManager[doc.ConfigurationManager.ActiveConfiguration.Name];
            foreach (var kv in cfg)
                if (!string.IsNullOrEmpty(kv.Value))
                    mgr.Add3(kv.Key, (int)SolidWorks.Interop.swconst.swCustomInfoType_e.swCustomInfoText, kv.Value,
                        (int)SolidWorks.Interop.swconst.swCustomPropertyAddOption_e.swCustomPropertyReplaceValue);
        }

        private Dictionary<string, string> ReadConfig(IModelDoc2 doc)
        {
            // Configuration-specific properties win; document-level properties are the fallback.
            var perConfig = doc.Extension.CustomPropertyManager[doc.ConfigurationManager.ActiveConfiguration.Name];
            var perDoc = doc.Extension.CustomPropertyManager[""];
            string Get(string name, string fallback = "")
            {
                foreach (var mgr in new[] { perConfig, perDoc })
                {
                    mgr.Get5(name, false, out string _, out string resolved, out bool _);
                    if (!string.IsNullOrEmpty(resolved)) return resolved;
                }
                return fallback;
            }
            string material = Get("FL_Material", Session.Material);
            if (Array.IndexOf(Session.MaterialCodes, material) < 0)
                throw new InvalidOperationException("Unsupported FL_Material '" + material + "'. Use one of: " + string.Join(", ", Session.MaterialNames) + ".");
            return new Dictionary<string, string>
            {
                ["FL_Printer"] = Get("FL_Printer", Session.Machine),
                ["FL_Material"] = material,
                ["FL_Layer"] = Get("FL_Layer", Session.Layer),
                ["FL_PrintSetting"] = Get("FL_PrintSetting", ""), // empty: the service picks the catalog default
                ["FL_PrintCS"] = Get("FL_PrintCS"),
            };
        }

        private void SendAll(string projectDir, string docPath, string conf, Dictionary<string, string> cfg, List<ExportedBody> bodies)
        {
            var client = Session.EnsureConnected();
            var changedBuilds = new List<string>(); // builds that got a new or replaced model need supports
            foreach (var b in bodies)
            {
                string target = Path.Combine(Session.ProjectDir, "exports", b.BodyId + "_" + Guid.NewGuid().ToString("N").Substring(0, 8) + Path.GetExtension(b.File));
                File.Move(b.File, target);
                var bcfg = b.Cfg ?? cfg;
                var req = new Dictionary<string, object>
                {
                    ["document"] = b.DocPath ?? docPath, ["configuration"] = b.Config ?? conf, ["body_id"] = b.BodyId, ["body_name"] = b.BodyName,
                    ["export_file"] = target, ["export_format"] = Session.ExportFormat, ["lock_mode"] = Session.LockMode,
                    ["machine_type"] = bcfg["FL_Printer"], ["material_code"] = bcfg["FL_Material"],
                    ["layer_thickness_mm"] = double.Parse(bcfg["FL_Layer"], System.Globalization.CultureInfo.InvariantCulture),
                    ["print_setting"] = bcfg["FL_PrintSetting"],
                    ["print_cs_transform"] = b.Transform, // baked into the export (D-01)
                };
                var op = client.Post("/send", req);
                var done = client.Wait((string)op["operation_id"], TimeSpan.FromMinutes(10));
                var res = done.ContainsKey("result") ? done["result"] as Dictionary<string, object> : null;
                if (res != null && (string)res["action"] != "unchanged" && !changedBuilds.Contains((string)res["build_id"]))
                    changedBuilds.Add((string)res["build_id"]);
            }
            AutoSupports(client, changedBuilds);
        }

        /// <summary>Right after a send: generate supports, then auto layout. A failure is reported but never undoes the send.</summary>
        private void AutoSupports(ServiceClient client, List<string> buildIds)
        {
            foreach (var id in buildIds)
            {
                // Save first: the build continues in its saved file, so PreForm shows its real name, and layout
                // after that is reliable (measured: layout of the unsaved live scene can report "would eject").
                try { client.Post("/build/save", new Dictionary<string, object> { ["build_id"] = id }); }
                catch (Exception ex) { SwAddin.Log("save before supports FAILED: " + ex); }
                bool supports = RunStep(client, "/build/supports", id, TimeSpan.FromMinutes(30), "Supports could not be generated", "use Generate supports");
                if (!supports) continue; // layout after a failed support step would hide the real problem
                bool laidOut = RunStep(client, "/build/layout", id, TimeSpan.FromMinutes(30), "Auto layout could not be done", "use Auto layout");
                if (supports && laidOut) _supportNote = " Supports generated and parts laid out.";
            }
        }

        private bool RunStep(ServiceClient client, string path, string buildId, TimeSpan timeout, string failText, string fixText)
        {
            try
            {
                var op = client.Post(path, new Dictionary<string, object> { ["build_id"] = buildId });
                client.Wait((string)op["operation_id"], timeout);
                return true;
            }
            catch (Exception ex)
            {
                SwAddin.Log(path + " FAILED: " + ex);
                _supportNote = " " + failText + " (" + (ex is ServiceException se ? se.Message : ex.Message) + "); " + fixText + ".";
                return false;
            }
        }

        public void Dispose() => Session.Host.Dispose();
    }
}
