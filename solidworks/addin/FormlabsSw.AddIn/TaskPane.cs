using System;
using System.Collections;
using System.Collections.Generic;
using System.Linq;
using System.Runtime.InteropServices;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Forms.Integration;
using FormlabsSw.Core;

namespace FormlabsSw.AddIn
{
    /// <summary>
    /// Task Pane (spec §11): Project, Builds, Preparation, Submit, History. WPF hosted in a COM-visible
    /// WinForms control. All service calls run off the UI thread; success is shown only after the
    /// service confirms the operation (never optimistic).
    /// </summary>
    [ComVisible(true)]
    [Guid("0B7E2C41-8C0A-4E5B-B7C4-5A3D6F2E9C11")]
    [ProgId(ProgId)]
    public sealed class TaskPane : System.Windows.Forms.UserControl
    {
        public const string ProgId = "FormlabsSw.TaskPane";

        public TaskPane()
        {
            Dock = System.Windows.Forms.DockStyle.Fill;
            Controls.Add(new ElementHost { Dock = System.Windows.Forms.DockStyle.Fill, Child = new PaneView() });
        }
    }

    internal sealed class PaneView : System.Windows.Controls.UserControl
    {
        private readonly TextBox _projectBox = new TextBox { IsReadOnly = true, ToolTip = "Project folder (date-time name)" };
        private readonly TextBlock _status = new TextBlock { TextWrapping = TextWrapping.Wrap, Margin = new Thickness(0, 0, 0, 4), FontWeight = FontWeights.SemiBold };
        private readonly ProgressBar _progress = new ProgressBar { IsIndeterminate = true, Height = 6, Visibility = Visibility.Collapsed };
        private CancellationTokenSource _cts = new CancellationTokenSource();

        private readonly List<Button> _actions = new List<Button>();   // disabled while a call is running
        private readonly Button _cancel = new Button { Content = "Stop waiting", Visibility = Visibility.Collapsed, Margin = new Thickness(0, 2, 0, 2) };
        private static readonly string[] LayerChoices = { "0.025", "0.05", "0.1" };
        private bool _busy;

        public PaneView()
        {
            var root = new StackPanel { Margin = new Thickness(8) };

            // Status first: always visible, says what is happening or what to do next.
            _status.Text = "Ready. Pick a material and click Send.";
            root.Children.Add(_status);
            root.Children.Add(_progress);
            _cancel.Click += (s, e) => _cts.Cancel();
            root.Children.Add(_cancel);

            // 1. Settings the user actually changes.
            root.Children.Add(Header("1. Material and layer"));
            var presets = new[]
            {
                "Tough 2000 V2 - impact, flex, snaps",
                "Grey V5 - standard parts, fixtures, best finish and accuracy",
                "White V5 - like Grey, other colour",
                "Clear V5 - like Grey, transparent",
                "Rigid 10K - very stiff, glass filled, no snaps",
            };
            var mat = new ComboBox { ItemsSource = presets, ToolTip = "Material for new parts. A part's FL_Material property overrides it." };
            mat.SelectedIndex = Math.Max(0, Array.IndexOf(Session.MaterialCodes, Session.Material));
            mat.SelectionChanged += (s, e) => { if (mat.SelectedIndex >= 0) Session.Material = Session.MaterialCodes[mat.SelectedIndex]; };
            root.Children.Add(Labelled("Material", mat));
            var layer = new ComboBox { ItemsSource = LayerChoices.Select(l => l + " mm").ToList(), ToolTip = "Layer thickness. Thinner = finer detail, slower print." };
            layer.SelectedIndex = Math.Max(0, Array.IndexOf(LayerChoices, Session.Layer));
            layer.SelectionChanged += (s, e) => { if (layer.SelectedIndex >= 0) Session.Layer = LayerChoices[layer.SelectedIndex]; };
            root.Children.Add(Labelled("Layer thickness", layer));

            // 2. The one main action.
            root.Children.Add(Header("2. Send"));
            var sendBtn = Btn("Send active part to Formlabs", () =>
            {
                if (Session.Send == null) { _status.Text = "The add-in is not connected to SOLIDWORKS."; return; }
                SetBusy(true, "Sending to Formlabs, generating supports and laying out (connecting if needed)... this can take a minute.");
                // Exports on this (UI) thread, talks to the service off-thread, then reports here and refreshes.
                Session.Send.Run(text => Dispatcher.Invoke(() =>
                {
                    bool failed = text.StartsWith("Send failed");
                    SetBusy(false, failed ? text : text + " Open it in PreForm to check and print.");
                }));
            }, primary: true);
            root.Children.Add(sendBtn);
            root.Children.Add(Hint("Turn the part in SOLIDWORKS the way you want it printed: it lands in PreForm as the view shows it."));

            // Rarely changed options stay out of the way.
            var more = new StackPanel();
            var orient = new ComboBox
            {
                ItemsSource = new[] { "As shown in the SOLIDWORKS view", "Same axes as the SOLIDWORKS model", "Stand up (Y up becomes PreForm up)" },
                SelectedIndex = Session.Orientation == "same" ? 1 : Session.Orientation == "yup" ? 2 : 0,
                ToolTip = "How the part is placed in PreForm. A part's FL_PrintCS coordinate system overrides this.",
            };
            orient.SelectionChanged += (s, e) => Session.Orientation = orient.SelectedIndex == 1 ? "same" : orient.SelectedIndex == 2 ? "yup" : "view";
            more.Children.Add(Labelled("Placement in PreForm", orient));
            var lockBox = new ComboBox { ItemsSource = new[] { "Keep orientation, allow moving", "Allow turning around Z and moving", "Allow any turning and moving" }, SelectedIndex = Array.IndexOf(Session.LockValues, Session.LockMode) < 0 ? 0 : Array.IndexOf(Session.LockValues, Session.LockMode) };
            lockBox.SelectionChanged += (s, e) => Session.LockMode = Session.LockValues[lockBox.SelectedIndex];
            more.Children.Add(Labelled("Freedom in PreForm", lockBox));
            var fmt = new ComboBox { ItemsSource = new[] { "STEP", "STL" }, SelectedItem = Session.ExportFormat, ToolTip = "STEP keeps exact surfaces; use STL only if STEP fails." };
            fmt.SelectionChanged += (s, e) => Session.ExportFormat = (string)fmt.SelectedItem;
            more.Children.Add(Labelled("Export format", fmt));
            var wb = new CheckBox { Content = "Save these choices into the part's properties (marks it modified)", IsChecked = Session.WriteBackProperties, Margin = new Thickness(0, 4, 0, 0) };
            wb.Click += (s, e) => Session.WriteBackProperties = wb.IsChecked == true;
            more.Children.Add(wb);
            root.Children.Add(new Expander { Header = "More options", Content = more, Margin = new Thickness(0, 6, 0, 0) });

            // Housekeeping, collapsed.
            var proj = new StackPanel();
            _projectBox.Text = Session.ProjectDir;
            proj.Children.Add(_projectBox);
            var projBtns = new WrapPanel();
            projBtns.Children.Add(Btn("New project", () => { _projectBox.Text = Session.StartNewProject(); _status.Text = "New project: " + _projectBox.Text; }));
            projBtns.Children.Add(Btn("Save project", SaveProject));
            proj.Children.Add(projBtns);
            root.Children.Add(new Expander { Header = "Project and connection", Content = proj, Margin = new Thickness(0, 8, 0, 0) });
            Content = new ScrollViewer { Content = root, VerticalScrollBarVisibility = ScrollBarVisibility.Auto };
            UpdateEnabled();
        }

        private static TextBlock Header(string t) =>
            new TextBlock { Text = t, FontWeight = FontWeights.Bold, Margin = new Thickness(0, 12, 0, 3) };

        private static TextBlock Hint(string t) =>
            new TextBlock { Text = t, TextWrapping = TextWrapping.Wrap, Foreground = System.Windows.Media.Brushes.Gray, FontSize = 11, Margin = new Thickness(0, 2, 0, 0) };

        private static StackPanel Labelled(string label, UIElement control)
        {
            var p = new StackPanel { Margin = new Thickness(0, 2, 0, 4) };
            p.Children.Add(new TextBlock { Text = label, Foreground = System.Windows.Media.Brushes.DimGray, FontSize = 11 });
            p.Children.Add(control);
            return p;
        }

        private Button Btn(string text, Action a, bool primary = false)
        {
            var b = new Button { Content = text, Margin = new Thickness(0, 2, 4, 2), Padding = new Thickness(8, 3, 8, 3) };
            if (primary)
            {
                b.Padding = new Thickness(8, 8, 8, 8);
                b.FontWeight = FontWeights.Bold;
                b.FontSize = 14;
                b.Background = new System.Windows.Media.SolidColorBrush(System.Windows.Media.Color.FromRgb(0xF5, 0x82, 0x20));
                b.Foreground = System.Windows.Media.Brushes.White;
            }
            b.Click += (s, e) => a();
            _actions.Add(b);
            return b;
        }

        /// <summary>Disables actions while a call runs (no double clicks).</summary>
        private void SetBusy(bool busy, string status = null)
        {
            _busy = busy;
            _progress.Visibility = busy ? Visibility.Visible : Visibility.Collapsed;
            _cancel.Visibility = busy ? Visibility.Visible : Visibility.Collapsed;
            if (status != null) _status.Text = status;
            UpdateEnabled();
        }

        private void UpdateEnabled()
        {
            foreach (var b in _actions) b.IsEnabled = !_busy;
        }

        /// <summary>Runs a service call off the UI thread, then marshals the confirmed result back.</summary>
        private void Do(string what, Action<ServiceClient> work, Action done = null, bool quiet = false)
        {
            // quiet: background refresh; keeps the last message (e.g. "Sent 1 body") on screen unless it fails.
            _cts = new CancellationTokenSource();
            SetBusy(true, quiet ? null : what + "...");
            Task.Run(() =>
            {
                try { work(Session.EnsureConnected()); return (string)null; }
                catch (OperationCanceledException) { return "stopped waiting; the service result is reconciled later (OD-05)"; }
                catch (Exception ex)
                {
                    SwAddin.Log(what + " FAILED: " + ex); // full stack in %LOCALAPPDATA%\FormlabsSw\addin.log
                    return ex is ServiceException se ? se.AppCode + ": " + se.Message : ex.GetType().Name + ": " + ex.Message;
                }
            }).ContinueWith(t => Dispatcher.Invoke(() =>
            {
                SetBusy(false);
                if (t.Result != null) _status.Text = what + " failed. " + t.Result;
                else if (!quiet) _status.Text = what + ": done.";
                if (t.Result == null && done != null) done();
            }));
        }

        private void SaveProject()
        {
            Do("Saving project", c =>
            {
                var r = c.Post("/project/save", new Dictionary<string, object>());
                c.Wait((string)r["operation_id"], TimeSpan.FromMinutes(10), _cts.Token);
            });
        }
    }
}
