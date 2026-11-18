"""Scheduled printing for Formlabs Form 4.

Before you start: open PreForm, click File > Start PreForm Server (port 44388).
Keep this app running (the window may be minimized) until the scheduled time.

Usage:  py -3 app.py
"""

from __future__ import annotations

import ctypes
import os
import queue
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from core import PENDING, RUNNING, JobStore, PreFormBackend, Scheduler, Settings, find_server_exe, new_job

ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001
PRINTER_POLL_MS = 30_000
DATA_DIR =Path(os.environ.get("APPDATA", Path.home())) / "FormlabsScheduledPrint"


def keep_awake(on: bool) -> None:
    """Stop Windows sleeping while a print is scheduled; otherwise a 2 AM job would never fire."""
    if os.name == "nt":
        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | (ES_SYSTEM_REQUIRED if on else 0))


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Form 4 Scheduled Print")
        self.geometry("760x460")
        self.settings = Settings(DATA_DIR / "settings.json")
        self.server_var = tk.StringVar(value=self.settings.get("server_exe") or find_server_exe())
        self._server_exe = self.server_var.get()  # cached: worker threads must not touch tk variables
        self.server_var.trace_add("write", self._server_changed)
        self.backend = PreFormBackend(server_exe=lambda: self._server_exe)
        self.scheduler = Scheduler(JobStore(DATA_DIR / "jobs.json"), self.backend, on_change=self._changed)
        self.form_var = tk.StringVar()
        self.printer_var = tk.StringVar()
        self.date_var = tk.StringVar(value=datetime.now().strftime("%Y-%m-%d"))
        self.time_var = tk.StringVar(value="02:00")
        self._printers: dict[str, dict] = {}
        self._refreshing = False
        self._ui_queue: queue.SimpleQueue = queue.SimpleQueue()  # worker threads post here; only the main thread touches tk
        self._build()
        self.refresh()
        self.refresh_printers()
        self._check_server()
        self.after(PRINTER_POLL_MS, self._poll_printers)
        self._tick()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build(self) -> None:
        f = ttk.Frame(self, padding=10)
        f.pack(fill="both", expand=True)
        f.columnconfigure(1, weight=1)
        ttk.Label(f, text="1. .form file").grid(row=0, column=0, sticky="w")
        ttk.Entry(f, textvariable=self.form_var).grid(row=0, column=1, sticky="ew", padx=6)
        ttk.Button(f, text="Browse...", command=self.browse).grid(row=0, column=2)
        ttk.Label(f, text="2. Printer").grid(row=1, column=0, sticky="w", pady=6)
        pf = ttk.Frame(f)
        pf.grid(row=1, column=1, sticky="ew", padx=6)
        pf.columnconfigure(0, weight=1)
        self.printer_box = ttk.Combobox(pf, textvariable=self.printer_var)
        self.printer_box.grid(row=0, column=0, sticky="ew")
        self.printer_box.bind("<<ComboboxSelected>>", lambda _e: self._show_printer_state())
        self.printer_state = ttk.Label(pf, text="", width=34)
        self.printer_state.grid(row=0, column=1, padx=(8, 0))
        self.printer_var.trace_add("write", lambda *_: self._show_printer_state())
        ttk.Button(f, text="Refresh", command=self.refresh_printers).grid(row=1, column=2)
        ttk.Label(f, text="3. Date / time").grid(row=2, column=0, sticky="w")
        when = ttk.Frame(f)
        when.grid(row=2, column=1, sticky="w", padx=6)
        ttk.Entry(when, textvariable=self.date_var, width=12).pack(side="left")
        ttk.Entry(when, textvariable=self.time_var, width=7).pack(side="left", padx=6)
        ttk.Label(when, text="YYYY-MM-DD  HH:MM (24 h)").pack(side="left")
        ttk.Button(f, text="4. Schedule Print", command=self.schedule).grid(row=3, column=1, sticky="w", padx=6, pady=10)
        cols = ("when", "printer", "file", "status", "message")
        self.tree = ttk.Treeview(f, columns=cols, show="headings", height=9)
        for c, w in zip(cols, (120, 110, 150, 70, 260)):
            self.tree.heading(c, text=c.capitalize())
            self.tree.column(c, width=w)
        self.tree.grid(row=4, column=0, columnspan=3, sticky="nsew")
        f.rowconfigure(4, weight=1)
        bar = ttk.Frame(f)
        bar.grid(row=5, column=0, columnspan=3, sticky="e", pady=6)
        ttk.Button(bar, text="Cancel selected", command=self.cancel).pack(side="left", padx=4)
        ttk.Button(bar, text="Remove finished", command=self.remove).pack(side="left")
        ttk.Label(f, text="PreFormServer.exe").grid(row=6, column=0, sticky="w")
        ttk.Entry(f, textvariable=self.server_var).grid(row=6, column=1, sticky="ew", padx=6)
        ttk.Button(f, text="Browse...", command=self.browse_server).grid(row=6, column=2)
        self.server_state = ttk.Label(f, text="Server: checking...")
        self.server_state.grid(row=7, column=0, sticky="w")
        ttk.Label(f, text="Set the path so the app can start PreForm Server for you (also at print time).").grid(
            row=7, column=1, sticky="w", padx=6
        )
        self.server_btn = ttk.Button(f, text="Start server", command=self.toggle_server)
        self.server_btn.grid(row=7, column=2)
        self.status = ttk.Label(f, text="")
        self.status.grid(row=8, column=0, columnspan=3, sticky="w")

    def browse(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("PreForm files", "*.form")])
        if path:
            self.form_var.set(path)

    def browse_server(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("PreFormServer", "PreFormServer.exe"), ("Programs", "*.exe")])
        if path:
            self.server_var.set(path)

    def _server_changed(self, *_: object) -> None:
        self._server_exe = self.server_var.get().strip()
        self.settings.set("server_exe", self._server_exe)

    def refresh_printers(self, quiet: bool = False) -> None:
        if self._refreshing:
            return
        self._refreshing = True
        if not quiet:
            self.status.config(text="Looking for printers...")

        def work() -> None:
            try:
                found = self.backend.list_printers(start_server=False)  # listing never starts a server; the toggle does
                printers = {str(p.get("id", "")): p for p in found}
                msg = "" if printers else "No Form 4 found. Is PreForm Server running? Use Start server."
            except Exception as exc:
                printers, msg = {}, f"Cannot reach PreForm Server: {getattr(exc, 'message', exc)}"
            self._ui_queue.put(lambda: self._printers_loaded(printers, msg, quiet))

        threading.Thread(target=work, daemon=True).start()

    def _printers_loaded(self, printers: dict[str, dict], msg: str, quiet: bool) -> None:
        self._refreshing = False
        if printers or not quiet:  # a failed background poll keeps the last known list
            self._printers = printers
            self.printer_box.config(values=list(printers))
            self.status.config(text=msg)
        self._show_printer_state()

    def _show_printer_state(self) -> None:
        p = self._printers.get(self.printer_var.get().strip())
        if p is None:
            self.printer_state.config(text="", foreground="")
        elif p.get("ready_to_print_now"):
            self.printer_state.config(text="Ready to print", foreground="#1a7f37")
        else:
            status = str(p.get("status") or "unknown")
            text = "Not ready" if status.lower() == "not ready" else f"Not ready: {status}"
            self.printer_state.config(text=text, foreground="#b35900")

    def _check_server(self) -> None:
        def work() -> None:
            running, owned = self.backend.server_reachable(), self.backend.owns_server()
            self._ui_queue.put(lambda: self._show_server_state(running, owned))

        threading.Thread(target=work, daemon=True).start()

    def _show_server_state(self, running: bool, owned: bool) -> None:
        if running and owned:
            self.server_state.config(text="Server: running", foreground="#1a7f37")
            self.server_btn.config(text="Stop server", state="normal")
        elif running:
            self.server_state.config(text="Server: running (PreForm)", foreground="#1a7f37")
            self.server_btn.config(text="Stop server", state="disabled")  # started in PreForm: close it there
        else:
            self.server_state.config(text="Server: stopped", foreground="#b35900")
            self.server_btn.config(text="Start server", state="normal")

    def toggle_server(self) -> None:
        stopping = self.backend.owns_server()
        if stopping and self.scheduler.has_pending() and not messagebox.askyesno(
            "Stop server", "Print jobs are still scheduled. The app will start the server again at print time if the "
            "PreFormServer.exe path is set. Stop it now?"
        ):
            return
        self.server_btn.config(state="disabled")
        self.server_state.config(text="Server: stopping..." if stopping else "Server: starting...", foreground="")

        def work() -> None:
            try:
                self.backend.stop_server() if stopping else self.backend.start_server()
                err = ""
            except Exception as exc:
                err = f"Server: {getattr(exc, 'message', exc)}"

            def done() -> None:
                self._check_server()
                self.refresh_printers()
                if err:
                    self.status.config(text=err)

            self._ui_queue.put(done)

        threading.Thread(target=work, daemon=True).start()

    def _poll_printers(self) -> None:
        self._check_server()
        self.refresh_printers(quiet=True)
        self.after(PRINTER_POLL_MS, self._poll_printers)

    def schedule(self) -> None:
        try:
            run_at = datetime.strptime(f"{self.date_var.get().strip()} {self.time_var.get().strip()}", "%Y-%m-%d %H:%M")
            self.scheduler.add(new_job(self.form_var.get(), self.printer_var.get(), run_at))
        except ValueError as exc:
            messagebox.showerror("Cannot schedule", str(exc))

    def _selected(self) -> str | None:
        sel = self.tree.selection()
        return sel[0] if sel else None

    def cancel(self) -> None:
        if (job_id := self._selected()) is not None:
            self.scheduler.cancel(job_id)

    def remove(self) -> None:
        for job in [j for j in self.scheduler.jobs]:
            self.scheduler.remove(job.id)

    def _changed(self) -> None:
        self._ui_queue.put(self.refresh)  # may be called from a worker thread

    def refresh(self) -> None:
        self.tree.delete(*self.tree.get_children())
        for j in sorted(self.scheduler.jobs, key=lambda j: j.run_at):
            self.tree.insert("", "end", iid=j.id, values=(j.run_at.replace("T", " "), j.printer, Path(j.form_file).name, j.status, j.message))
        keep_awake(any(j.status in (PENDING, RUNNING) for j in self.scheduler.jobs))

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
    App().mainloop()
