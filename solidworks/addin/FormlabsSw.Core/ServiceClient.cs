using System;
using System.Collections.Generic;
using System.IO;
using System.Net;
using System.Text;
using System.Threading;
using System.Web.Script.Serialization;

namespace FormlabsSw.Core
{
    public sealed class ServiceException : Exception
    {
        public string AppCode { get; }
        public ServiceException(string appCode, string message) : base(appCode + ": " + message) { AppCode = appCode; }
    }

    /// <summary>
    /// HTTP client for the Integration Service. Every request carries the per-session bearer token
    /// (spec §2.4). Thin by design: all Formlabs logic lives in the service (rule 12).
    /// </summary>
    public sealed class ServiceClient
    {
        private readonly string _baseUrl;
        private readonly string _token;
        private readonly JavaScriptSerializer _json = new JavaScriptSerializer { MaxJsonLength = int.MaxValue };

        public ServiceClient(int port, string token)
        {
            if (string.IsNullOrEmpty(token)) throw new ArgumentException("token required", nameof(token));
            _baseUrl = "http://127.0.0.1:" + port; // loopback only
            _token = token;
        }

        public Dictionary<string, object> Get(string path) => Send("GET", path, null);
        public Dictionary<string, object> Post(string path, object body) => Send("POST", path, body);

        public Dictionary<string, object> Send(string method, string path, object body)
        {
            var req = (HttpWebRequest)WebRequest.Create(_baseUrl + path);
            req.Method = method;
            req.Headers["Authorization"] = "Bearer " + _token;
            req.Timeout = 30000;
            if (body != null)
            {
                var data = Encoding.UTF8.GetBytes(_json.Serialize(body));
                req.ContentType = "application/json";
                req.ContentLength = data.Length;
                using (var s = req.GetRequestStream()) s.Write(data, 0, data.Length);
            }
            try
            {
                using (var resp = (HttpWebResponse)req.GetResponse())
                    return Parse(resp);
            }
            catch (WebException ex) when (ex.Response is HttpWebResponse err)
            {
                var d = Parse(err);
                object code, msg;
                d.TryGetValue("app_code", out code);
                d.TryGetValue("message", out msg);
                throw new ServiceException(code as string ?? ("HTTP_" + (int)err.StatusCode), msg as string ?? "");
            }
        }

        private Dictionary<string, object> Parse(WebResponse r)
        {
            using (var sr = new StreamReader(r.GetResponseStream(), Encoding.UTF8))
            {
                var text = sr.ReadToEnd();
                // Some endpoints return arrays; wrap them so callers always get a dictionary.
                var obj = _json.DeserializeObject(text);
                return obj as Dictionary<string, object> ?? new Dictionary<string, object> { { "items", obj } };
            }
        }

        /// <summary>Polls an async operation until it leaves RUNNING. Never reports success early.</summary>
        public Dictionary<string, object> Wait(string operationId, TimeSpan timeout, CancellationToken ct = default)
        {
            var end = DateTime.UtcNow + timeout;
            while (DateTime.UtcNow < end)
            {
                ct.ThrowIfCancellationRequested();
                var op = Get("/operation/" + operationId);
                if ((string)op["state"] != "RUNNING")
                {
                    if ((string)op["state"] == "FAILED")
                    {
                        var e = op["error"] as Dictionary<string, object>;
                        throw new ServiceException(e?["app_code"] as string ?? "FAILED", e?["message"] as string ?? "");
                    }
                    return op;
                }
                Thread.Sleep(200);
            }
            throw new TimeoutException("operation " + operationId + " still running");
        }
    }
}
