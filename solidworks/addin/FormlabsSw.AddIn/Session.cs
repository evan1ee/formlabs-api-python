using System;
using System.IO;
using FormlabsSw.Core;
using Microsoft.Win32;

namespace FormlabsSw.AddIn
{
    /// <summary>Process-wide state shared by the command and the Task Pane.</summary>
    public static class Session
    {
        private const string RegKey = @"Software\Formlabs\SolidWorks";
        public static readonly ServiceHost Host = new ServiceHost();

        public static string InstallDir =>
            System.Environment.GetEnvironmentVariable("FL_INSTALL_DIR") ?? Path.GetDirectoryName(typeof(Session).Assembly.Location);

        public static string ProjectsRoot =>
            Path.Combine(System.Environment.GetFolderPath(System.Environment.SpecialFolder.MyDocuments), "Formlabs Projects");

        /// <summary>Project folder: one project per day, named yyyy-MM-dd. A stored folder from an earlier day rolls over to today.</summary>
        public static string ProjectDir
        {
            get
            {
                var dir = (string)Get("ProjectDir");
                if (string.IsNullOrEmpty(dir) || IsEarlierDay(dir)) { dir = TodayFolder(); Set("ProjectDir", dir); }
                return dir;
            }
            set => Set("ProjectDir", value);
        }

        /// <summary>Today's project folder; reused if it exists, so a day's builds share one project.</summary>
        public static string TodayFolder() => Path.Combine(ProjectsRoot, DateTime.Now.ToString("yyyy-MM-dd"));

        /// <summary>A second, separate project on the same day: yyyy-MM-dd-2, -3...</summary>
        public static string NewProjectFolder()
        {
            string day = DateTime.Now.ToString("yyyy-MM-dd"), p = Path.Combine(ProjectsRoot, day);
            for (int n = 2; Directory.Exists(p); n++) p = Path.Combine(ProjectsRoot, day + "-" + n);
            return p;
        }

        /// <summary>True unless the folder is today's project (yyyy-MM-dd, or yyyy-MM-dd-2 for a second one).
        /// Older day folders and the earlier date-time folders roll over to today's project.</summary>
        private static bool IsEarlierDay(string dir)
        {
            string name = Path.GetFileName(dir.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar));
            string today = DateTime.Now.ToString("yyyy-MM-dd");
            return !(name == today || System.Text.RegularExpressions.Regex.IsMatch(name, "^" + today + "-[0-9]+$"));
        }

        /// <summary>Starts a separate project for today; the running service is stopped so the next call uses it.</summary>
        public static string StartNewProject()
        {
            Host.Stop();
            ProjectDir = NewProjectFolder();
            return ProjectDir;
        }

        /// <summary>Set by the add-in on connect so the Task Pane can run the same Send command as the toolbar.</summary>
        public static SendCommand Send;

        public const string DefaultPrinter = "Form 4B";
        /// <summary>The printer last chosen in the pane (remembered between sessions); Form 4B until one is chosen.</summary>
        public static string Printer
        {
            get { var v = (string)Get("Printer"); return string.IsNullOrWhiteSpace(v) ? DefaultPrinter : v; }
            set { if (!string.IsNullOrWhiteSpace(value)) Set("Printer", value); }
        }
        public static string Machine => "FORM-4-0"; // the machine type id Form 4 and Form 4B share

        /// <summary>Default printer (Form 4B), material (Tough 2000 V2) and layer thickness; FL_* properties on the part override them.</summary>
        public static string Material
        {
            get { var v = (string)Get("Material"); return Array.IndexOf(MaterialCodes, v) >= 0 ? v : MaterialCodes[0]; }
            set { if (Array.IndexOf(MaterialCodes, value) >= 0) Set("Material", value); }
        }

        /// <summary>The only supported materials: Tough 2000 V2 (default), Grey V5, White V5, Clear V5, Rigid 10K.</summary>
        public static readonly string[] MaterialCodes = { "FLTO2002", "FLGPGR05", "FLGPWH05", "FLGPCL05", "FLRG1001" };

        /// <summary>What people see, in the same order as MaterialCodes. Codes never appear in the UI.</summary>
        public static readonly string[] MaterialNames = { "Tough 2000 V2", "Grey V5", "White V5", "Clear V5", "Rigid 10K" };

        public static string MaterialName(string code)
        {
            int i = Array.IndexOf(MaterialCodes, code);
            return i >= 0 ? MaterialNames[i] : code;
        }

        public static string Layer
        {
            get => string.IsNullOrWhiteSpace((string)Get("Layer")) ? "0.1" : (string)Get("Layer");
            set => Set("Layer", (value ?? "").Trim());
        }

        /// <summary>"view" (default): the part lands as the current SOLIDWORKS view shows it. "same": PreForm X/Y/Z =
        /// SOLIDWORKS X/Y/Z. "yup": stand a Y-up part up.</summary>
        public static string Orientation
        {
            get { var v = (string)Get("Orientation"); return v == "same" || v == "yup" ? v : "view"; }
            set => Set("Orientation", value == "same" || value == "yup" ? value : "view");
        }

        public static string PreformExe
        {
            // "connect" attaches to a server already listening on 44388 (PreForm > File > Start PreForm Server).
            get
            {
                var v = (string)Get("PreformExe");
                if (string.IsNullOrWhiteSpace(v)) v = System.Environment.GetEnvironmentVariable("FL_PREFORM_EXE");
                return string.IsNullOrWhiteSpace(v) ? "connect" : v;
            }
            set => Set("PreformExe", value);
        }

        /// <summary>OD-07: writing FL_* custom properties dirties the document, so it is opt-in (default off).</summary>
        public static bool WriteBackProperties
        {
            get => Get("WriteBack") as string == "1";
            set => Set("WriteBack", value ? "1" : "0");
        }

        public static readonly string[] LockValues =
            { "LOCKED_ROTATION_FREE_TRANSLATION", "LOCKED_XY_ROTATION_FREE_TRANSLATION", "FREE" };

        public static string LockMode
        {
            get => (string)Get("LockMode") ?? LockValues[0];
            set { if (Array.IndexOf(LockValues, value) >= 0) Set("LockMode", value); }
        }

        /// <summary>STEP (default) or STL fallback (D-06).</summary>
        public static string ExportFormat
        {
            get => (string)Get("ExportFormat") == "STL" ? "STL" : "STEP";
            set => Set("ExportFormat", value == "STL" ? "STL" : "STEP");
        }

        public static ServiceClient EnsureStarted()
        {
            if (!Host.IsRunning)
            {
                Directory.CreateDirectory(ProjectDir);
                Host.Start(Path.Combine(InstallDir, "python", "python.exe"), ProjectDir, PreformExe,
                    InstallDir, TimeSpan.FromSeconds(90));
            }
            return Host.Client;
        }

        private static ServiceClient _connectedClient;

        /// <summary>Starts the service and connects it to PreForm if that has not happened yet, so the user never
        /// has to press Connect first. A restarted service gets a new client and is connected again.</summary>
        public static ServiceClient EnsureConnected()
        {
            var c = EnsureStarted();
            if (!ReferenceEquals(c, _connectedClient))
            {
                c.Post("/connect", new System.Collections.Generic.Dictionary<string, object>());
                _connectedClient = c;
            }
            return c;
        }

        private static object Get(string name)
        {
            using (var k = Registry.CurrentUser.OpenSubKey(RegKey)) return k?.GetValue(name);
        }

        private static void Set(string name, string value)
        {
            using (var k = Registry.CurrentUser.CreateSubKey(RegKey)) k.SetValue(name, value);
        }
    }
}
