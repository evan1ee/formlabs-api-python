"""Scheduled printing for Formlabs Form 4.

Before you start: open PreForm, click File > Start PreForm Server (port 44388).
Keep this app running (the window may be minimized) until the scheduled time.

Usage:  py -3 app.py
"""

from __future__ import annotations

import ctypes
import os
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from core import PENDING, RUNNING, JobStore, PreFormBackend, Scheduler, new_job

ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001
DATA_DIR = Path(os.environ.get("APPDATA", Path.home())) / "FormlabsScheduledPrint"


def keep_awake(on: bool) -> None:
    """Stop Windows sleeping while a print is scheduled; otherwise a 2 AM job would never fire."""
    if os.name == "nt":
        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | (ES_SYSTEM_REQUIRED if on else 0))


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Form 4 Scheduled Print")
        self.geometry("760x460")
        self.backend = PreFormBackend()
        self.scheduler = Scheduler(JobStore(DATA_DIR / "jobs.json"), self.backend, on_change=self._changed)
        self.form_var = tk.StringVar()
        self.printer_var = tk.StringVar()
        self.date_var = tk.StringVar(value=datetime.now().strftime("%Y-%m-%d"))
        self.time_var = tk.StringVar(value="02:00")
        self._build()
        self.refresh()
        self.refresh_printers()
        self._tick()

    def _build(self) -> None:
        f = ttk.Frame(self, padding=10)
        f.pack(fill="both", expand=True)
        f.columnconfigure(1, weight=1)
        ttk.Label(f, text="1. .form file").grid(row=0, column=0, sticky="w")
        ttk.Entry(f, textvariable=self.form_var).grid(row=0, column=1, sticky="ew", padx=6)
        ttk.Button(f, text="Browse...", command=self.browse).grid(row=0, column=2)
        ttk.Label(f, text="2. Printer").grid(row=1, column=0, sticky="w", pady=6)
        self.printer_box = ttk.Combobox(f, textvariable=self.printer_var)
        self.printer_box.grid(row=1, column=1, sticky="ew", padx=6)
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
        self.status = ttk.Label(f, text="")
        self.status.grid(row=6, column=0, columnspan=3, sticky="w")

    def browse(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("PreForm files", "*.form")])
        if path:
            self.form_var.set(path)

    def refresh_printers(self) -> None:
        self.status.config(text="Looking for printers...")

        def work() -> None:
            try:
                names = [str(p.get("id", "")) for p in self.backend.list_printers()]
                msg = "" if names else "No Form 4 found. Is the PreForm Server running?"
            except Exception as exc:
                names, msg = [], f"Cannot reach PreForm Server: {getattr(exc, 'message', exc)}"
            self.after(0, lambda: (self.printer_box.config(values=names), self.status.config(text=msg)))

        threading.Thread(target=work, daemon=True).start()

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
        self.after(0, self.refresh)  # may be called from a worker thread

    def refresh(self) -> None:
        self.tree.delete(*self.tree.get_children())
        for j in sorted(self.scheduler.jobs, key=lambda j: j.run_at):
            self.tree.insert("", "end", iid=j.id, values=(j.run_at.replace("T", " "), j.printer, Path(j.form_file).name, j.status, j.message))
        keep_awake(any(j.status in (PENDING, RUNNING) for j in self.scheduler.jobs))

    def _tick(self) -> None:
        self.scheduler.tick()
        self.after(1000, self._tick)


if __name__ == "__main__":
    App().mainloop()
