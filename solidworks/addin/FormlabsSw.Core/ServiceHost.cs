using System;
using System.Diagnostics;
using System.IO;
using System.Security.Cryptography;
using System.Web.Script.Serialization;

namespace FormlabsSw.Core
{
    /// <summary>
    /// Starts and supervises the Python Integration Service (spec §2.4, D-03). The token goes to the
    /// child through an environment variable, never argv. The child reports its port in one JSON line.
    /// </summary>
    public sealed class ServiceHost : IDisposable
    {
        private Process _proc;
        public ServiceClient Client { get; private set; }

        public static string NewToken()
        {
            var b = new byte[32];
            using (var rng = RandomNumberGenerator.Create()) rng.GetBytes(b);
            return Convert.ToBase64String(b).Replace('/', '_').Replace('+', '-');
        }

        /// <param name="pythonExe">Embedded runtime shipped in the install folder.</param>
        public void Start(string pythonExe, string projectFolder, string preformExe, string installFolder, TimeSpan startupTimeout)
        {
            if (!File.Exists(pythonExe)) throw new ServiceException("SERVICE_START_FAILED", "missing runtime " + pythonExe);
            var token = NewToken();
            var psi = new ProcessStartInfo(pythonExe,
                "-I -m formlabs_sw_service --project \"" + projectFolder + "\" --preform-exe \"" + preformExe + "\"")
            {
                UseShellExecute = false,
                RedirectStandardOutput = true,
                RedirectStandardInput = true, // closing stdin tells the service to shut down
                CreateNoWindow = true,
                WorkingDirectory = installFolder,
            };
            psi.EnvironmentVariables["FL_SERVICE_TOKEN"] = token;
            psi.EnvironmentVariables["PYTHONPATH"] = installFolder;
            _proc = Process.Start(psi);
            var lineTask = _proc.StandardOutput.ReadLineAsync();
            if (!lineTask.Wait(startupTimeout))
            {
                Stop();
                throw new ServiceException("SERVICE_START_FAILED", "no handshake within " + startupTimeout);
            }
            var hs = new JavaScriptSerializer().Deserialize<System.Collections.Generic.Dictionary<string, object>>(lineTask.Result ?? "{}");
            if (!hs.ContainsKey("port"))
            {
                Stop();
                object c; hs.TryGetValue("app_code", out c);
                throw new ServiceException(c as string ?? "SERVICE_START_FAILED", lineTask.Result ?? "");
            }
            Client = new ServiceClient(Convert.ToInt32(hs["port"]), token);
        }

        public bool IsRunning => _proc != null && !_proc.HasExited;

        public void Stop()
        {
            if (_proc == null) return;
            try { _proc.StandardInput.Close(); if (!_proc.WaitForExit(15000)) _proc.Kill(); } catch { /* already gone */ }
            _proc = null;
        }

        public void Dispose() => Stop();
    }
}
