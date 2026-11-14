using System;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using Microsoft.Win32;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swpublished;

namespace FormlabsSw.AddIn
{
    /// <summary>
    /// SOLIDWORKS add-in entry point (spec §2.3): thin shell. Registers a "Send to Formlabs" command;
    /// all Formlabs logic lives in the Python Integration Service.
    /// </summary>
    [ComVisible(true)]
    [Guid(AddInGuid)]
    [ClassInterface(ClassInterfaceType.AutoDispatch)]
    public sealed class SwAddin : ISwAddin
    {
        public const string AddInGuid = "6D1C7F0E-3B7A-4C55-9E55-2F1B0B7A4A10";
        private const int CommandGroupId = 0x4C46; // "LF"
        private ISldWorks _sw;
        private int _cookie;
        private ICommandManager _cmdMgr;
        private SendCommand _send;
        private ITaskpaneView _pane;

        public static readonly string LogPath = Path.Combine(
            System.Environment.GetFolderPath(System.Environment.SpecialFolder.LocalApplicationData), "FormlabsSw", "addin.log");

        internal static void Log(string msg)
        {
            try
            {
                Directory.CreateDirectory(Path.GetDirectoryName(LogPath));
                File.AppendAllText(LogPath, DateTime.Now.ToString("s") + " " + msg + System.Environment.NewLine);
            }
            catch { /* logging must never break the add-in */ }
        }

        /// <summary>Runs one start-up step; a failure is logged and does not stop the other steps.</summary>
        private static bool Step(string name, Func<bool> f)
        {
            try { bool ok = f(); Log(name + ": " + (ok ? "ok" : "returned false")); return ok; }
            catch (Exception ex) { Log(name + " FAILED: " + ex); return false; }
        }

        public bool ConnectToSW(object thisSw, int cookie)
        {
            Log("ConnectToSW start, SOLIDWORKS " + ((ISldWorks)thisSw).RevisionNumber());
            _sw = (ISldWorks)thisSw;
            _cookie = cookie;
            if (!Step("SetAddinCallbackInfo2", () => _sw.SetAddinCallbackInfo2(0, this, cookie))) return false;
            _cmdMgr = _sw.GetCommandManager(cookie);
            _send = new SendCommand(_sw);
            Session.Send = _send;
            var icons = IconPaths();
            Log("icons present: " + icons.All(File.Exists));

            Step("command group", () =>
            {
                int err = 0;
                var grp = _cmdMgr.CreateCommandGroup2(CommandGroupId, "Formlabs", "Formlabs for SOLIDWORKS", "", -1, true, ref err);
                Log("CreateCommandGroup2 error code " + err);
                grp.IconList = icons;
                grp.MainIconList = icons;
                int cmd = grp.AddCommandItem2("Send to Formlabs", -1, "Send the selected bodies to a Formlabs print project",
                    "Send to Formlabs", 0, nameof(OnSend), nameof(EnableSend), 1,
                    (int)SolidWorks.Interop.swconst.swCommandItemType_e.swMenuItem | (int)SolidWorks.Interop.swconst.swCommandItemType_e.swToolbarItem);
                grp.HasToolbar = true;
                grp.HasMenu = true;
                Log("AddCommandItem2 returned " + cmd);
                return grp.Activate();
            });

            // The task pane is independent of the toolbar: a failure above must not stop it.
            Step("task pane", () =>
            {
                _pane = _sw.CreateTaskpaneView3(icons, "Formlabs");
                return _pane != null && _pane.AddControl(TaskPane.ProgId, "") != null;
            });
            Log("ConnectToSW done");
            return true; // never make SOLIDWORKS untick the add-in; problems are in the log
        }

        public bool DisconnectFromSW()
        {
            Log("DisconnectFromSW");
            Session.Send = null;
            _send?.Dispose();
            try { _pane?.DeleteView(); } catch (Exception ex) { Log("DeleteView: " + ex.Message); }
            _pane = null;
            _cmdMgr?.RemoveCommandGroup(CommandGroupId);
            _cmdMgr = null;
            _sw = null;
            GC.Collect();
            GC.WaitForPendingFinalizers();
            return true;
        }

        /// <summary>PNG icons at the sizes SOLIDWORKS asks for (20, 32, 40, 64, 96, 128 px).</summary>
        private static string[] IconPaths()
        {
            string dir = Path.Combine(Path.GetDirectoryName(typeof(SwAddin).Assembly.Location), "Icons");
            return new[] { 20, 32, 40, 64, 96, 128 }.Select(n => Path.Combine(dir, "formlabs_" + n + ".png")).ToArray();
        }

        /// <summary>Diagnostics: runs what the pane's Connect button runs, inside SOLIDWORKS, and returns the full result.</summary>
        public string DebugConnect()
        {
            try
            {
                var sb = new System.Text.StringBuilder();
                sb.AppendLine("install=" + Session.InstallDir + " project=" + Session.ProjectDir + " preform=" + Session.PreformExe);
                var c = Session.EnsureStarted();
                sb.AppendLine("service started");
                var r = c.Post("/connect", new System.Collections.Generic.Dictionary<string, object>());
                sb.AppendLine("connect ok: " + r["server_version"]);
                return sb.ToString();
            }
            catch (Exception ex) { Log("DebugConnect FAILED: " + ex); return "FAILED: " + ex; }
        }

        public void OnSend() => _send.Run();

        public int EnableSend() => _sw?.ActiveDoc is IPartDoc || _sw?.ActiveDoc is IAssemblyDoc ? 1 : 0;

        [ComRegisterFunction]
        public static void Register(Type t)
        {
            using (var k = Registry.LocalMachine.CreateSubKey(@"SOFTWARE\SolidWorks\Addins\{" + AddInGuid + "}"))
            {
                k.SetValue(null, 0);
                k.SetValue("Title", "Formlabs for SOLIDWORKS");
                k.SetValue("Description", "Prepare and queue Formlabs print jobs through PreForm Server");
            }
        }

        [ComUnregisterFunction]
        public static void Unregister(Type t) =>
            Registry.LocalMachine.DeleteSubKey(@"SOFTWARE\SolidWorks\Addins\{" + AddInGuid + "}", false);
    }
}
