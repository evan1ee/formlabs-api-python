# Scheduled print for Form 4

A small Tkinter app that sends a prepared `.form` file to a Form 4 at a chosen time (for example 02:00).

## Use

1. In PreForm, open **File > Start PreForm Server** (port 44388) and leave PreForm running.
2. `pip install "formlabs-sdk @ git+https://github.com/Formlabs/formlabs-api-python@v1.0.0-alpha.post2"`
3. `py -3 app.py`, or build a standalone exe with `.build.ps1` (output: `distFormlabsScheduledPrint`; zip that folder to move it to another PC, no Python needed. `.distFormlabsScheduledPrintFormlabsScheduledPrint.exe --selftest` writes selftest.log next to the exe)
4. Pick the `.form` file, pick the printer, enter the date and time, click **Schedule Print**.

Leave the app and PreForm running until the print starts. While a job is pending the app stops Windows from sleeping.

## Behaviour

- Orientation, supports and print settings come from the `.form` file as saved. The app does not change them.
- Jobs are saved in `%APPDATA%\FormlabsScheduledPrint\jobs.json` and survive a restart.
- A job that is more than 10 minutes overdue when the app starts is marked **missed** and is not printed.
- At the scheduled time the job is sent to the printer. If the printer is ready it starts at once. If not, the job is queued on the printer.
- Failures (PreForm Server not running, printer offline) show in the Message column.

## Tests

`py -3 -m pytest tests` runs the scheduler against a fake backend.

Verified by hand against PreForm Server 3.66 (SDK built for 3.64.2): listing printers, opening a `.form`, and sending it to a virtual Form 4 all work. Only Form 4 (not 4B/4L) physical printers are offered. A real print on hardware has not been run.
