# Scheduled print for Form 4

A small Tkinter app that sends a prepared `.form` file to a Form 4 at a chosen time (for example 02:00).

## Use

1. Either open PreForm and choose **File > Start PreForm Server** (port 44388), or set the **PreFormServer.exe** path in the app (it is found automatically under `Program Files\Formlabs` when present) and the app starts the server itself when it needs one. A server that is already running is reused.
2. `pip install "formlabs-sdk @ git+https://github.com/Formlabs/formlabs-api-python@v1.0.0-alpha.post2"`
3. `py -3 app.py`, or build a standalone exe with `.build.ps1` (output: `distFormlabsScheduledPrint`; zip that folder to move it to another PC, no Python needed. `.distFormlabsScheduledPrintFormlabsScheduledPrint.exe --selftest` writes selftest.log next to the exe)
4. Pick the `.form` file, pick the printer, enter the date and time, click **Schedule Print**.

Leave the app and PreForm running until the print starts. While a job is pending the app stops Windows from sleeping.

## Getting PreFormServer.exe

PreForm Insider does not include `PreFormServer.exe`. For the app to start the server itself, download the PreForm Server zip for Windows from https://formlabs.com/support/Formlabs-API-downloads-and-release-notes/ , unzip it (for example to `C:\PreFormServer`) and set the path in the app. Any `PreFormServer.exe` under `C:\PreFormServer` (including the nested folder the zip creates) is found automatically. Without it, start the server from PreForm (File > Start PreForm Server) instead.

## Window

- **New print**: pick the file, the printer and the start time. Quick buttons set "In 1 hour", "Next 02:00" or "Next 08:00". A line under the form says what is missing, or exactly what will happen ("Will print part.form on Form4-LinenLynx, Thu 19 Nov at 02:00 (in 7 h 29 min)"). Schedule Print is enabled only when everything is valid.
- **Printers**: every detected printer with its name, status (for example "Ready to print" or "Printing") and connection. Click a row to choose that printer.
- **Scheduled prints**: status with a countdown for pending jobs. Double-click a row for details.
- **Settings**: the PreFormServer.exe location.

## Behaviour

- **Start server / Stop server** button: starts PreForm Server (needs the `PreFormServer.exe` path) and keeps it running, so the printer status stays live and there is no startup delay at print time. A server you started in PreForm itself is shown as running but only PreForm can close it. Quitting the app stops a server the app started, and warns if jobs are still scheduled.

- The printer list shows whether the selected Form 4 is ready to print right now, refreshed every 30 seconds while a server is running.

- Orientation, supports and print settings come from the `.form` file as saved. The app does not change them.
- Jobs are saved in `%APPDATA%\FormlabsScheduledPrint\jobs.json` and survive a restart.
- A job that is more than 10 minutes overdue when the app starts is marked **missed** and is not printed.
- At the scheduled time the job is sent to the printer. If the printer is ready it starts at once. If not, the job is queued on the printer.
- Failures (PreForm Server not running, printer offline) show in the Message column.

## Releases

Pushing a tag such as `scheduled-print-v0.1.0` runs `.github/workflows/scheduled-print.yml`, which tests, builds the exe and publishes `FormlabsScheduledPrint-<version>-win64.zip` (with SHA256SUMS.txt) as a GitHub Release. Other users download the zip, unzip it and run the exe. Every push to main also uploads the zip as a workflow artifact.

## If something goes wrong

The app never guesses about a print that may already have been sent. What it does in each case:

| Situation at the start time | What happens |
|---|---|
| Printer not ready (busy, door open, no cartridge...) | The job shows **Waiting for printer**, rechecks every 15 s and starts as soon as the printer is ready. The wait is set in Settings (default 60 min; 0 = do not wait). |
| Printer never becomes ready in that time | The job is only queued on the printer and shown as **Queued only**: it will not start by itself, start it from the printer's screen. |
| PreForm Server not running or cannot start | Retried during the same wait time. If it never comes back the job **Failed** with "nothing was sent". |
| Printer turned not-ready just before sending | Retried; PreForm refuses the job before uploading, so it cannot print twice. |
| Connection lost or timed out while sending | **Failed**, not retried: the job may already be on the printer, so check its queue before scheduling again. |
| `.form` file moved or deleted | **Failed** at once, with the file name. |
| PreForm rejected the job (out of bounds, not sliceable, login needed...) | **Failed** with PreForm's message. |
| App was closed or the PC was off at the start time | **Missed**: nothing is printed late (more than 10 minutes after the time). Closed while waiting: Missed. Closed while sending: Failed with a reminder to check the printer queue. |
| A second copy of the app is opened | It closes itself, because two copies would start the same print twice. |
| The job list cannot be saved (disk full, permissions) | The app keeps running and shows a red error. |
| A `.form` file with several scenes | Only the first scene is sent, and the job says so. |

Jobs that did not start by themselves are counted in red at the bottom of the window.

## Tests

`py -3 -m pytest tests` runs the scheduler against a fake backend.

Verified by hand against PreForm Server 3.66 (SDK built for 3.64.2): listing printers, opening a `.form`, and sending it to a virtual Form 4 all work. Only Form 4 (not 4B/4L) physical printers are offered. A real print on hardware has not been run.
