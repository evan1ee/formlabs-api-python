using System;
using System.Collections.Generic;
using System.IO;
using System.Net;
using System.Text;
using System.Threading;
using FormlabsSw.Core;

// Minimal dependency-free test harness: exit code 0 = all passed.
internal static class Program
{
    private static int _failed;
    private static void Check(bool ok, string name)
    {
        Console.WriteLine((ok ? "PASS " : "FAIL ") + name);
        if (!ok) _failed++;
    }
    private static bool Near(double a, double b) => Math.Abs(a - b) < 1e-9;

    private static int Main()
    {
        var p = Matrix4.Rotation('z', 90).Apply(1, 0, 0);
        Check(Near(p.X, 0) && Near(p.Y, 1) && Near(p.Z, 0), "rotate Z 90 maps X to Y");

        var m = Matrix4.Translation(5, 0, 0) * Matrix4.Rotation('x', 45);
        var id = m * m.InvertRigid();
        bool ident = true;
        for (int i = 0; i < 4; i++) for (int j = 0; j < 4; j++) ident &= Near(id.M[i, j], i == j ? 1 : 0);
        Check(ident, "rigid inverse composes to identity");
        m.ValidateRigid();

        var scaled = Matrix4.Identity(); scaled.M[0, 0] = 2;
        var mirror = Matrix4.Identity(); mirror.M[0, 0] = -1;
        Check(Throws(() => scaled.ValidateRigid()), "scale rejected");
        Check(Throws(() => mirror.ValidateRigid()), "mirror rejected");

        var arr = new double[16];
        arr[0] = arr[4] = arr[8] = 1; arr[9] = 0.025; // 25 mm in metres
        Check(Near(Matrix4.FromSolidWorksMetres(arr).M[0, 3], 25), "metres converted to mm");

        Check(ServiceHost.NewToken().Length >= 32 && ServiceHost.NewToken() != ServiceHost.NewToken(), "tokens random");

        // View orientation: "what you see is how it lands".
        double[] front = { 1, 0, 0, 0, 1, 0, 0, 0, 1 };
        double[] top = { 1, 0, 0, 0, 0, 1, 0, -1, 0 };      // values measured from SOLIDWORKS 2025
        double[] iso = { 0.707, -0.408, 0.577, 0, 0.817, 0.577, -0.707, -0.408, 0.577 };
        var up = ViewOrientation.Apply(ViewOrientation.FromView(front), 0, 1, 0);
        Check(Near(up.X, 0) && Near(up.Y, 0) && Near(up.Z, 1), "Front view: model +Y (screen up) becomes PreForm up (+Z)");
        var toward = ViewOrientation.Apply(ViewOrientation.FromView(front), 0, 0, 1);
        Check(Near(toward.X, 0) && Near(toward.Y, -1) && Near(toward.Z, 0), "Front view: toward-viewer becomes PreForm -Y (front)");
        var topUp = ViewOrientation.Apply(ViewOrientation.FromView(top), 0, 0, -1);
        Check(Near(topUp.Z, 1), "Top view: screen up (model -Z) becomes PreForm up");
        var isoUp = ViewOrientation.Apply(ViewOrientation.FromView(iso), 0, 1, 0);
        Check(isoUp.Z > 0.8, "Isometric view: model +Y mostly up on screen, mostly up in PreForm");
        var r = ViewOrientation.FromView(iso);
        double det = r[0] * (r[4] * r[8] - r[5] * r[7]) - r[1] * (r[3] * r[8] - r[5] * r[6]) + r[2] * (r[3] * r[7] - r[4] * r[6]);
        Check(Math.Abs(det - 1) < 0.01, "view mapping is a proper rotation (no mirroring)");
        Check(ViewOrientation.ToColumn4x4(ViewOrientation.FromView(front))[2][1] == 1, "column 4x4 for the service");

        ClientTests();
        Console.WriteLine(_failed == 0 ? "ALL PASSED" : _failed + " FAILED");
        return _failed == 0 ? 0 : 1;
    }

    private static bool Throws(Action a) { try { a(); return false; } catch (ArgumentException) { return true; } }

    private static void ClientTests()
    {
        const int port = 47811;
        var l = new HttpListener();
        l.Prefixes.Add("http://127.0.0.1:" + port + "/");
        l.Start();
        string seenAuth = null;
        var t = new Thread(() =>
        {
            while (l.IsListening)
            {
                HttpListenerContext c;
                try { c = l.GetContext(); } catch { return; }
                seenAuth = c.Request.Headers["Authorization"];
                string body; int code = 200;
                if (seenAuth != "Bearer tok") { code = 401; body = "{\"app_code\":\"SERVICE_AUTH_FAILED\"}"; }
                else if (c.Request.Url.AbsolutePath == "/fail") { code = 400; body = "{\"app_code\":\"LAYOUT_WOULD_EJECT\",\"message\":\"x\"}"; }
                else body = "{\"ok\":true}";
                var data = Encoding.UTF8.GetBytes(body);
                c.Response.StatusCode = code;
                c.Response.OutputStream.Write(data, 0, data.Length);
                c.Response.Close();
            }
        }) { IsBackground = true };
        t.Start();
        try
        {
            Check((bool)new ServiceClient(port, "tok").Get("/health")["ok"], "client sends bearer token");
            Check(seenAuth == "Bearer tok", "authorization header format");
            string code = null;
            try { new ServiceClient(port, "bad").Get("/health"); } catch (ServiceException e) { code = e.AppCode; }
            Check(code == "SERVICE_AUTH_FAILED", "401 maps to SERVICE_AUTH_FAILED");
            code = null;
            try { new ServiceClient(port, "tok").Post("/fail", new Dictionary<string, object>()); } catch (ServiceException e) { code = e.AppCode; }
            Check(code == "LAYOUT_WOULD_EJECT", "service app_code surfaced");
        }
        finally { l.Stop(); }
    }
}
