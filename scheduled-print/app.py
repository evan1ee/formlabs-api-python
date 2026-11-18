"""Scheduled printing for Formlabs Form 4.

Pick a .form file, a printer and a time, then click Schedule Print. Keep this app open until the print starts.

Usage:  py -3 app.py
"""

from __future__ import annotations

import ctypes
import os
import queue
import threading
import tkinter as tk
import webbrowser
from datetime import datetime, timedelta
from pathlib import Path
from tkinter import filedialog, font as tkfont, messagebox, ttk

from core import (
    CANCELLED, DONE, FAILED, MISSED, PENDING, QUEUED, RUNNING,
    JobStore, PreFormBackend, Scheduler, Settings, find_server_exe, new_job,
)
from timefmt import describe, humanize_delta, next_at, parse_when, presets

ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001
PRINTER_POLL_MS = 30_000
DATA_DIR = Path(os.environ.get("APPDATA", Path.home())) / "FormlabsScheduledPrint"
DOWNLOAD_PAGE = "https://formlabs.com/support/Formlabs-API-downloads-and-release-notes/"
GOOD, WARN, BAD, MUTED = "#1a7f37", "#b35900", "#c62828", "#6b6b6b"
STATUS_VIEW = {  # status -> (label, tag)
    PENDING: ("●  Scheduled", "pending"), RUNNING: ("▶  Printing", "running"), DONE: ("✔  Sent", "done"), QUEUED: ("▣  Queued only", "queued"),
    FAILED: ("✖  Failed", "failed"), MISSED: ("⚠  Missed", "missed"), CANCELLED: ("⊘  Cancelled", "cancelled"),
}


def keep_awake(on: bool) -> None:
    """Stop Windows sleeping while a print is scheduled; otherwise a 2 AM job would never fire."""
    if os.name == "nt":
        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | (ES_SYSTEM_REQUIRED if on else 0))


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Form 4 Scheduled Print")
        self._scale = self.winfo_fpixels("1i") / 96  # Tk scales fonts with the display, but not pixel sizes
        width = min(self.px(900), self.winfo_screenwidth() - self.px(40))
        height = min(self.px(800), self.winfo_screenheight() - self.px(110))  # leave room for the taskbar
        self.geometry(f"{width}x{height}+{(self.winfo_screenwidth() - width) // 2}+{max(0, (self.winfo_screenheight() - height) // 2 - self.px(30))}")
        self.minsize(min(self.px(760), width), min(self.px(640), height))
        self.settings = Settings(DATA_DIR / "settings.json")
        self.server_var = tk.StringVar(value=self.settings.get("server_exe") or find_server_exe())
        self._server_exe = self.server_var.get()  # cached: worker threads must not touch tk variables
        self.backend = PreFormBackend(server_exe=lambda: self._server_exe)
        self.scheduler = Scheduler(JobStore(DATA_DIR / "jobs.json"), self.backend, on_change=self._changed)
        self.form_var, self.printer_var = tk.StringVar(), tk.StringVar()
        self.date_var, self.hour_var, self.minute_var = tk.StringVar(), tk.StringVar(), tk.StringVar()
        self._printers: dict[str, dict] = {}
        self._refreshing = False
        self._form_ok = False
        self._printers_error = ""
        self._server_running, self._has_exe = False, True
        self._ui_queue: queue.SimpleQueue = queue.SimpleQueue()  # worker threads post here; only the main thread touches tk
        self._style()
        self._build()
        self._apply_time(next_at(2, 0, datetime.now()))
        for var in (self.form_var,):
            var.trace_add("write", lambda *_: self._on_form_changed())
        for var in (self.printer_var, self.date_var, self.hour_var, self.minute_var):
            var.trace_add("write", lambda *_: self._update_summary())
        self.server_var.trace_add("write", self._server_changed)
        self.bind("<Return>", lambda _e: self.schedule() if str(self.schedule_btn["state"]) == "normal" else None)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.refresh()
        self.refresh_printers()
        self._check_server()
        self.after(PRINTER_POLL_MS, self._poll_printers)
        self._tick()

    def px(self, n: int) -> int:
        return int(n * self._scale)

    # ---------- layout ----------
    def _style(self) -> None:
        for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
            tkfont.nametofont(name).configure(family="Segoe UI", size=10)
        style = ttk.Style()
        style.configure("Title.TLabel", font=("Segoe UI", 15, "bold"))
        style.configure("Hint.TLabel", foreground=MUTED)
        style.configure("Accent.TButton", font=("Segoe UI", 10, "bold"), padding=(18, 7))
        style.configure("Treeview", rowheight=self.px(28))
        style.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"))
        style.configure("TLabelframe.Label", font=("Segoe UI", 10, "bold"))

    def _build(self) -> None:
        root = ttk.Frame(self, padding=(16, 12, 16, 8))
        root.pack(fill="both", expand=True)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(3, weight=1)
        self._build_header(root)
        self._build_new_print(root)
        self._build_printers(root)
        self._build_jobs(root)
        bar = ttk.Frame(root)
        bar.grid(row=4, column=0, sticky="ew", pady=(8, 0))
        bar.columnconfigure(0, weight=1)
        self.status = ttk.Label(bar, text="", style="Hint.TLabel")
        self.status.grid(row=0, column=0, sticky="w")
        self.awake_note = ttk.Label(bar, text="", style="Hint.TLabel")
        self.awake_note.grid(row=0, column=1, sticky="e")

    def _build_header(self, root: ttk.Frame) -> None:
        head = ttk.Frame(root)
        head.grid(row=0, column=0, sticky="ew")
        head.columnconfigure(0, weight=1)
        ttk.Label(head, text="Form 4 Scheduled Print", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        self.server_state = ttk.Label(head, text="●  Checking PreForm Server...", foreground=MUTED)
        self.server_state.grid(row=0, column=1, padx=(0, 10))
        self.server_btn = ttk.Button(head, text="Start server", width=13, command=self.toggle_server)
        self.server_btn.grid(row=0, column=2)
        ttk.Button(head, text="Settings...", command=self.open_settings).grid(row=0, column=3, padx=(6, 0))
        self.banner = ttk.Label(
            head, foreground=WARN, wraplength=self.px(800), justify="left",
            text="PreFormServer.exe was not found, so the app cannot start the server by itself. Start it in PreForm "
                 "(File > Start PreForm Server) or set its location in Settings.",
        )
        self.banner.grid(row=1, column=0, columnspan=4, sticky="w", pady=(6, 0))
        self.banner.grid_remove()

    def _build_new_print(self, root: ttk.Frame) -> None:
        card = ttk.LabelFrame(root, text="New print", padding=(14, 10))
        card.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        card.columnconfigure(1, weight=1)

        ttk.Label(card, text="File").grid(row=0, column=0, sticky="w", pady=(0, 2))
        ttk.Entry(card, textvariable=self.form_var).grid(row=0, column=1, sticky="ew", padx=8)
        ttk.Button(card, text="Browse...", command=self.browse).grid(row=0, column=2)
        self.file_info = ttk.Label(card, text="Choose a .form file prepared in PreForm (orientation, supports and settings are used as saved).", style="Hint.TLabel", wraplength=self.px(700), justify="left")
        self.file_info.grid(row=1, column=1, columnspan=2, sticky="w", padx=8, pady=(0, 10))

        ttk.Label(card, text="Printer").grid(row=2, column=0, sticky="w", pady=(0, 2))
        self.printer_box = ttk.Combobox(card, textvariable=self.printer_var)
        self.printer_box.grid(row=2, column=1, sticky="ew", padx=8)
        self.printer_box.bind("<<ComboboxSelected>>", lambda _e: (self._show_printer_state(), self._sync_printer_row()))
        ttk.Button(card, text="Refresh", command=self.refresh_printers).grid(row=2, column=2)
        self.printer_state = ttk.Label(card, text="", style="Hint.TLabel", wraplength=self.px(700), justify="left")
        self.printer_state.grid(row=3, column=1, columnspan=2, sticky="w", padx=8, pady=(0, 10))

        ttk.Label(card, text="Start at").grid(row=4, column=0, sticky="w")
        when = ttk.Frame(card)
        when.grid(row=4, column=1, columnspan=2, sticky="w", padx=8)
        ttk.Button(when, text="−", width=2, command=lambda: self._shift_day(-1)).pack(side="left")
        ttk.Entry(when, textvariable=self.date_var, width=11, justify="center").pack(side="left", padx=4)
        ttk.Button(when, text="+", width=2, command=lambda: self._shift_day(1)).pack(side="left")
        ttk.Label(when, text="   at ").pack(side="left")
        for var, top in ((self.hour_var, 23), (self.minute_var, 59)):
            ttk.Spinbox(when, from_=0, to=top, width=3, wrap=True, format="%02.0f", textvariable=var, justify="center").pack(side="left")
            if var is self.hour_var:
                ttk.Label(when, text=" : ").pack(side="left")
        ttk.Label(when, text="   24-hour clock", style="Hint.TLabel").pack(side="left")

        quick = ttk.Frame(card)
        quick.grid(row=5, column=1, columnspan=2, sticky="w", padx=8, pady=(6, 0))
        ttk.Label(quick, text="Quick:", style="Hint.TLabel").pack(side="left", padx=(0, 6))
        for label, _ in presets(datetime.now()):
            ttk.Button(quick, text=label, command=lambda l=label: self._apply_preset(l)).pack(side="left", padx=(0, 6))

        foot = ttk.Frame(card)
        foot.grid(row=6, column=0, columnspan=3, sticky="ew", pady=(14, 0))
        foot.columnconfigure(0, weight=1)
        self.summary = ttk.Label(foot, text="", wraplength=self.px(560), justify="left")
        self.summary.grid(row=0, column=0, sticky="w")
        self.schedule_btn = ttk.Button(foot, text="Schedule Print", style="Accent.TButton", command=self.schedule, state="disabled")
        self.schedule_btn.grid(row=0, column=1, sticky="e")

    def _build_printers(self, root: ttk.Frame) -> None:
        card = ttk.LabelFrame(root, text="Printers", padding=(10, 8))
        card.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        card.columnconfigure(0, weight=1)
        cols = (("name", "Printer", 230), ("status", "Status", 230), ("conn", "Connection", 130))
        self.printer_tree = ttk.Treeview(card, columns=[c[0] for c in cols], show="headings", height=3, selectmode="browse")
        for key, title, width in cols:
            self.printer_tree.heading(key, text=title, anchor="w")
            self.printer_tree.column(key, width=self.px(width), anchor="w", stretch=key == "status")
        self.printer_tree.tag_configure("ready", foreground=GOOD)
        self.printer_tree.tag_configure("notready", foreground=WARN)
        self.printer_tree.grid(row=0, column=0, sticky="ew")
        self.printer_tree.bind("<<TreeviewSelect>>", lambda _e: self._on_printer_row())
        self.printer_empty = tk.Label(self.printer_tree, text="", bg="white", fg=MUTED, justify="center")

    def _build_jobs(self, root: ttk.Frame) -> None:
        card = ttk.LabelFrame(root, text="Scheduled prints", padding=(10, 8))
        card.grid(row=3, column=0, sticky="nsew", pady=(12, 0))
        card.columnconfigure(0, weight=1)
        card.rowconfigure(0, weight=1)
        cols = (("when", "Start", 140), ("printer", "Printer", 130), ("file", "File", 170), ("status", "Status", 105), ("details", "Details", 260))
        self.tree = ttk.Treeview(card, columns=[c[0] for c in cols], show="headings", selectmode="browse")
        for key, title, width in cols:
            self.tree.heading(key, text=title, anchor="w")
            self.tree.column(key, width=self.px(width), anchor="w", stretch=key == "details")
        for tag, color in (("pending", "#0b5cad"), ("running", WARN), ("done", ""), ("queued", WARN), ("failed", BAD), ("missed", WARN), ("cancelled", MUTED)):
            self.tree.tag_configure(tag, foreground=color)
        scroll = ttk.Scrollbar(card, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        self.empty = tk.Label(self.tree, text="No scheduled prints yet.\nFill in the form above and click Schedule Print.", bg="white", fg=MUTED, justify="center")
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._update_job_buttons())
        self.tree.bind("<Double-1>", lambda _e: self.show_details())
        self.tree.bind("<Delete>", lambda _e: self.cancel())
        bar = ttk.Frame(card)
        bar.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        self.cancel_btn = ttk.Button(bar, text="Cancel selected", command=self.cancel, state="disabled")
        self.cancel_btn.pack(side="left")
        ttk.Button(bar, text="Details", command=self.show_details).pack(side="left", padx=6)
        ttk.Button(bar, text="Clear finished", command=self.remove).pack(side="right")

    # ---------- form state ----------
    def browse(self) -> None:
        path = filedialog.askopenfilename(initialdir=self.settings.get("last_dir") or None, filetypes=[("PreForm files", "*.form")])
        if path:
            self.form_var.set(path)
            self.settings.set("last_dir", str(Path(path).parent))

    def _on_form_changed(self) -> None:
        text = self._form_path()
        path = Path(text)
        if not text:
            self._form_ok, msg, color = False, "Choose a .form file prepared in PreForm (orientation, supports and settings are used as saved).", MUTED
        elif path.suffix.lower() != ".form":
            self._form_ok, msg, color = False, "This is not a .form file.", BAD
        elif not path.is_file():
            self._form_ok, msg, color = False, "File not found.", BAD
        else:
            info = path.stat()
            self._form_ok, color = True, MUTED
            msg = f"{info.st_size / 1_048_576:.1f} MB, saved {datetime.fromtimestamp(info.st_mtime):%Y-%m-%d %H:%M}"
        self.file_info.config(text=msg, foreground=color)
        self._update_summary()

    def _apply_time(self, when: datetime) -> None:
        self.date_var.set(f"{when:%Y-%m-%d}")
        self.hour_var.set(f"{when.hour:02d}")
        self.minute_var.set(f"{when.minute:02d}")

    def _apply_preset(self, label: str) -> None:
        self._apply_time(dict(presets(datetime.now()))[label])

    def _shift_day(self, days: int) -> None:
        try:
            base = datetime.strptime(self.date_var.get().strip(), "%Y-%m-%d")
        except ValueError:
            base = datetime.now()
        self.date_var.set(f"{base + timedelta(days=days):%Y-%m-%d}")

    def _chosen_time(self) -> datetime:
        return parse_when(self.date_var.get(), self.hour_var.get(), self.minute_var.get())

    def _form_path(self) -> str:
        return self.form_var.get().strip().strip('"')

    def _printer_id(self) -> str:
        return str((self._selected_printer() or {}).get("id") or self.printer_var.get().strip())

    def _update_summary(self) -> None:
        """Say what is still missing, or what will happen; enable Schedule Print only when everything is valid."""
        problem, color, run_at = "", MUTED, None
        if not self._form_ok:
            problem = "Choose a .form file to print."
        elif not self.printer_var.get().strip():
            problem = "Choose a printer."
        else:
            try:
                run_at = self._chosen_time()
                if run_at <= datetime.now():
                    problem, color = "The start time is in the past. Pick a later time.", BAD
            except ValueError as exc:
                problem, color = str(exc), BAD
        if problem:
            self.summary.config(text=problem, foreground=color)
            self.schedule_btn.config(state="disabled")
        else:
            name, when = Path(self._form_path()).name, describe(run_at, datetime.now())
            self.summary.config(text=f"Will print {name} on {self._printer_id()}\n{when}", foreground="")
            self.schedule_btn.config(state="normal")

    def schedule(self) -> None:
        try:
            run_at = self._chosen_time()
            printer = self._printer_id()
            job = new_job(self._form_path(), printer, run_at)
        except ValueError as exc:
            messagebox.showerror("Cannot schedule", str(exc))
            return
        warnings = []
        chosen = self._selected_printer()
        if chosen is not None and not chosen.get("ready_to_print_now"):
            warnings.append(f"{printer} is not ready to print right now ({chosen.get('status', 'unknown')}). If it is still not ready at the start time, the job is queued on the printer instead of starting.")
        if not self._server_running and not self._has_exe:
            warnings.append("PreForm Server is not running and PreFormServer.exe is not set, so the print will fail unless you start the server before then.")
        if warnings and not messagebox.askyesno("Schedule anyway?", "\n\n".join(warnings) + "\n\nSchedule this print anyway?"):
            return
        self.scheduler.add(job)
        self.settings.set("last_printer", printer)
        self.status.config(text=f"Scheduled for {run_at:%a %d %b %H:%M}. Keep this app open until the print starts.")

    # ---------- printers ----------
    def refresh_printers(self, quiet: bool = False) -> None:
        if self._refreshing:
            return
        self._refreshing = True
        if not quiet:
            self.printer_state.config(text="Looking for printers...", foreground=MUTED)

        def work() -> None:
            try:
                found = self.backend.list_printers(start_server=False)  # listing never starts a server; the toggle does
                printers, error = {str(p.get("id", "")): p for p in found}, ""
            except Exception as exc:
                printers, error = {}, str(getattr(exc, "message", exc))
            self._ui_queue.put(lambda: self._printers_loaded(printers, error, quiet))

        threading.Thread(target=work, daemon=True).start()

    def _printers_loaded(self, printers: dict[str, dict], error: str, quiet: bool) -> None:
        self._refreshing = False
        if printers or not quiet:  # a failed background poll keeps the last known list
            self._printers = printers
            self.printer_box.config(values=[self._label(p) for p in printers.values()])
            self._fill_printer_tree()
            if not self.printer_var.get() and (last := self.settings.get("last_printer")) in printers:
                self.printer_var.set(self._label(printers[last]))
        self._printers_error = error
        self._show_printer_state()
        self._update_summary()

    @staticmethod
    def _label(p: dict) -> str:
        """Dropdown text: the printer name and whether it can print right now."""
        status = str(p.get("status") or "unknown")
        state = "Ready to print" if p.get("ready_to_print_now") else ("Not ready" if status.lower() == "not ready" else f"Not ready ({status})")
        return f"{p.get('id', '')}  -  {state}"

    def _selected_printer(self) -> dict | None:
        text = self.printer_var.get().strip()
        return next((p for p in self._printers.values() if text in (self._label(p), str(p.get("id")))), None)

    @staticmethod
    def _status_text(p: dict) -> str:
        status = str(p.get("status") or "unknown")
        return "●  Ready to print" if p.get("ready_to_print_now") else f"●  {status}"

    def _fill_printer_tree(self) -> None:
        selected = self.printer_tree.selection()
        self.printer_tree.delete(*self.printer_tree.get_children())
        for pid, p in self._printers.items():
            kind = str(p.get("connection_type") or "").replace("_", " ").title()
            self.printer_tree.insert("", "end", iid=pid, tags=("ready" if p.get("ready_to_print_now") else "notready",),
                                     values=(f"{pid}", self._status_text(p), kind))
        for iid in selected:
            if self.printer_tree.exists(iid):
                self.printer_tree.selection_set(iid)
        if self._printers:
            self.printer_empty.place_forget()
        else:
            reason = ("PreForm Server is not running. Click Start server, then Refresh." if self._printers_error
                      else "No Form 4 found.")
            self.printer_empty.config(text=reason)
            self.printer_empty.place(relx=0.5, rely=0.5, anchor="center")

    def _on_printer_row(self) -> None:
        sel = self.printer_tree.selection()
        if sel and sel[0] in self._printers:
            self.printer_var.set(self._label(self._printers[sel[0]]))
            self._show_printer_state()

    def _sync_printer_row(self) -> None:
        p = self._selected_printer()
        if p is not None and self.printer_tree.exists(str(p.get("id"))):
            self.printer_tree.selection_set(str(p.get("id")))

    def _show_printer_state(self) -> None:
        p = self._selected_printer()
        if p is not None:
            if p.get("ready_to_print_now"):
                self.printer_state.config(text="●  Ready to print now", foreground=GOOD)
            else:
                status = str(p.get("status") or "unknown")
                self.printer_state.config(
                    text=f"●  Not ready (PreForm reports: \"{status}\"). A job sent now would only be queued on the printer, "
                         "not started. Check its screen: build platform, resin tank or cartridge, door, a finished print "
                         "waiting to be removed.",
                    foreground=WARN)
        elif self._printers:
            self.printer_state.config(text=f"{len(self._printers)} printer(s) found. Choose one from the list.", foreground=MUTED)
        elif self._printers_error:
            self.printer_state.config(text="No printer list: PreForm Server is not running. Start it, then Refresh. You can also type a printer name or IP address.", foreground=MUTED)
        else:
            self.printer_state.config(text="No Form 4 found. You can also type a printer name or IP address.", foreground=MUTED)

    # ---------- server ----------
    def _check_server(self) -> None:
        def work() -> None:
            running, owned = self.backend.server_reachable(), self.backend.owns_server()
            has_exe = bool(find_server_exe(self._server_exe))
            self._ui_queue.put(lambda: self._show_server_state(running, owned, has_exe))

        threading.Thread(target=work, daemon=True).start()

    def _show_server_state(self, running: bool, owned: bool, has_exe: bool = True) -> None:
        self._server_running, self._has_exe = running, has_exe
        if running and owned:
            self.server_state.config(text="●  PreForm Server running", foreground=GOOD)
            self.server_btn.config(text="Stop server", state="normal")
        elif running:
            self.server_state.config(text="●  PreForm Server running (started in PreForm)", foreground=GOOD)
            self.server_btn.config(text="Stop server", state="disabled")  # started in PreForm: close it there
        else:
            self.server_state.config(text="●  PreForm Server stopped", foreground=WARN)
            self.server_btn.config(text="Start server", state="normal")
        if running or has_exe:
            self.banner.grid_remove()
        else:
            self.banner.grid()

    def toggle_server(self) -> None:
        stopping = self.backend.owns_server()
        if stopping and self.scheduler.has_pending() and not messagebox.askyesno(
            "Stop server", "Print jobs are still scheduled. The app will start the server again at print time if the "
            "PreFormServer.exe path is set. Stop it now?"
        ):
            return
        self.server_btn.config(state="disabled")
        self.server_state.config(text="●  Stopping PreForm Server..." if stopping else "●  Starting PreForm Server...", foreground=MUTED)

        def work() -> None:
            try:
                self.backend.stop_server() if stopping else self.backend.start_server()
                err = ""
            except Exception as exc:
                err = str(getattr(exc, "message", exc))

            def done() -> None:
                self._check_server()
                self.refresh_printers()
                self.status.config(text=err, foreground=BAD if err else MUTED)

            self._ui_queue.put(done)

        threading.Thread(target=work, daemon=True).start()

    def _server_changed(self, *_: object) -> None:
        self._server_exe = self.server_var.get().strip()
        self.settings.set("server_exe", self._server_exe)
        self._check_server()

    def open_settings(self) -> None:
        win = tk.Toplevel(self)
        win.title("Settings")
        win.transient(self)
        win.resizable(False, False)
        body = ttk.Frame(win, padding=16)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="PreFormServer.exe", font=("Segoe UI", 10, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(body, wraplength=self.px(460), justify="left", style="Hint.TLabel",
                  text="Lets the app start PreForm Server for you, including at print time. It is a separate download from "
                       "Formlabs (not part of PreForm). Leave it empty if you start the server in PreForm yourself.").grid(row=1, column=0, columnspan=2, sticky="w", pady=(2, 8))
        ttk.Entry(body, textvariable=self.server_var, width=52).grid(row=2, column=0, sticky="ew")
        ttk.Button(body, text="Browse...", command=self.browse_server).grid(row=2, column=1, padx=(6, 0))
        buttons = ttk.Frame(body)
        buttons.grid(row=3, column=0, columnspan=2, sticky="e", pady=(14, 0))
        ttk.Button(buttons, text="Open download page", command=lambda: webbrowser.open(DOWNLOAD_PAGE)).pack(side="left", padx=(0, 6))
        ttk.Button(buttons, text="Done", style="Accent.TButton", command=win.destroy).pack(side="left")
        win.update_idletasks()
        win.geometry(f"+{self.winfo_rootx() + 80}+{self.winfo_rooty() + 80}")
        win.grab_set()

    def browse_server(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("PreFormServer", "PreFormServer.exe"), ("Programs", "*.exe")])
        if path:
            self.server_var.set(path)

    def _poll_printers(self) -> None:
        self._check_server()
        self.refresh_printers(quiet=True)
        self.after(PRINTER_POLL_MS, self._poll_printers)

    # ---------- jobs ----------
    def _selected_job(self):
        sel = self.tree.selection()
        return next((j for j in self.scheduler.jobs if sel and j.id == sel[0]), None)

    def _update_job_buttons(self) -> None:
        job = self._selected_job()
        self.cancel_btn.config(state="normal" if job is not None and job.status == PENDING else "disabled")

    def cancel(self) -> None:
        job = self._selected_job()
        if job is not None and job.status == PENDING:
            self.scheduler.cancel(job.id)

    def remove(self) -> None:
        for job in list(self.scheduler.jobs):
            self.scheduler.remove(job.id)  # pending and running jobs are kept by the scheduler

    def show_details(self) -> None:
        job = self._selected_job()
        if job is not None:
            label = STATUS_VIEW[job.status][0].split("  ", 1)[1]
            messagebox.showinfo("Print details", f"Status: {label}\nStart: {job.when:%Y-%m-%d %H:%M}\nPrinter: {job.printer}\nFile: {job.form_file}\n\n{job.message or 'Waiting for the start time.'}")

    def _changed(self) -> None:
        self._ui_queue.put(self.refresh)  # may be called from a worker thread

    @staticmethod
    def _details(job, now: datetime) -> str:
        return f"Starts in {humanize_delta(job.when - now)}" if job.status == PENDING and job.when > now else job.message

    def refresh(self) -> None:
        selected = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        now = datetime.now()
        for j in sorted(self.scheduler.jobs, key=lambda j: j.run_at):
            label, tag = STATUS_VIEW[j.status]
            self.tree.insert("", "end", iid=j.id, tags=(tag,), values=(f"{j.when:%a %d %b  %H:%M}", j.printer, Path(j.form_file).name, label, self._details(j, now)))
        for iid in selected:
            if self.tree.exists(iid):
                self.tree.selection_set(iid)
        if self.scheduler.jobs:
            self.empty.place_forget()
        else:
            self.empty.place(relx=0.5, rely=0.5, anchor="center")
        pending = self.scheduler.has_pending()
        keep_awake(pending)
        self.awake_note.config(text="Windows will stay awake until these prints start." if pending else "")
        self._update_job_buttons()

    def _refresh_countdowns(self) -> None:
        now = datetime.now()
        for j in self.scheduler.jobs:
            if j.status == PENDING and self.tree.exists(j.id):
                self.tree.set(j.id, "details", self._details(j, now))

    def _on_close(self) -> None:
        if self.scheduler.has_pending() and not messagebox.askyesno(
            "Quit", "Print jobs are still scheduled and will NOT run if the app is closed. Quit anyway?"
        ):
            return
        keep_awake(False)
        self.backend.stop_server()  # only a server this app started
        self.destroy()

    def _drain_ui_queue(self) -> None:
        while True:
            try:
                self._ui_queue.get_nowait()()
            except queue.Empty:
                return

    def _tick(self) -> None:
        self._drain_ui_queue()
        self.scheduler.tick()
        self._refresh_countdowns()
        self._update_summary()  # keeps "in 3 h 20 min" and the in-the-past check current
        self.after(1000, self._tick)


def selftest() -> int:
    """Headless check for the packaged exe: SDK imports and PreForm Server answers. Writes selftest.log next to the exe."""
    import sys

    log = Path(sys.executable).parent / "selftest.log" if getattr(sys, "frozen", False) else Path("selftest.log")
    try:
        printers = PreFormBackend().list_printers()
        log.write_text(f"PASSED: {len(printers)} Form 4 printer(s): {[p['id'] for p in printers]}\n", "utf-8")
        return 0
    except Exception as exc:
        log.write_text(f"FAILED: {type(exc).__name__}: {getattr(exc, 'message', exc)}\n", "utf-8")
        return 1


if __name__ == "__main__":
    import sys

    if "--selftest" in sys.argv[1:]:
        sys.exit(selftest())
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # crisp text on high-DPI screens
    except (AttributeError, OSError):
        pass
    App().mainloop()
