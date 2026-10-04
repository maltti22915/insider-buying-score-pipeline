"""
============================================================================
gh_log_uploader.py
============================================================================

PURPOSE
----------------------------------------------------------------------------
Makes everything a GitHub Actions scraper prints also arrive in the main
"StockData_60 Execution Log.txt". Importing this module is enough:

    import gh_log_uploader   # first import line of the scraper

On import it copies everything written to stdout and stderr (the scraper's
own output is unchanged and still shows in the Actions run page), and when
the process exits -- normally, or after an exception -- it POSTs the captured
lines to the Apps Script Web App as {"target": "LOG", ...}, where
fn_60_03_ExternalLogHandler_StockData_60 appends them to the log file.

NO CHANGE TO SCRAPER LOGIC. Put it in the same folder as the scrapers (repo
root) and add the one import line to insider_score_scraper.py and
provider_json_scraper.py.

ENVIRONMENT (already set by the existing workflows)
----------------------------------------------------------------------------
GAS_WEBHOOK_URL  the Web App URL (if missing, nothing is sent)
SHEET_NAME, ROW_NUMBER  shown in the log entry header (optional)
GITHUB_RUN_ID    set by GitHub itself; lets you match an entry to the
                 Actions run (optional)
GH_LOG_SOURCE    overrides the source name (default: the script's file name)
GH_LOG_UPLOAD=0  turns the upload off without removing the import

SAFETY
----------------------------------------------------------------------------
Never raises, never changes the scraper's exit code, never prints the Web App
URL, sends at most the last MAX_LINES lines. If the upload fails it prints one
short line to the real stdout so the Actions page shows it.

VERSION: gh_log_uploader v1
============================================================================
"""
import atexit
import os
import sys
import threading

MAX_LINES = 2000
POST_TIMEOUT_SECONDS = 60

_lock = threading.Lock()
_chunks = []


class _Tee(object):
    """Writes to the real stream and keeps a copy of everything written."""

    def __init__(self, stream):
        self._stream = stream

    def write(self, text):
        try:
            with _lock:
                _chunks.append(text if isinstance(text, str) else str(text))
        except Exception:
            pass
        return self._stream.write(text)

    def flush(self):
        return self._stream.flush()

    def __getattr__(self, name):
        return getattr(self._stream, name)


def _build_payload():
    with _lock:
        text = "".join(_chunks)

    lines = text.splitlines()
    dropped = max(0, len(lines) - MAX_LINES)

    if dropped:
        lines = ["[... {} earlier lines not sent ...]".format(dropped)] + lines[-MAX_LINES:]

    row_number = os.environ.get("ROW_NUMBER", "").strip()
    source = os.environ.get("GH_LOG_SOURCE", "").strip()

    if not source:
        script = os.path.basename(sys.argv[0] or "") or "scraper"
        source = script[:-3] if script.endswith(".py") else script

    payload = {
        "target": "LOG",
        "source": source,
        "sheetName": os.environ.get("SHEET_NAME", "").strip(),
        "runId": os.environ.get("GITHUB_RUN_ID", "").strip(),
        "lines": lines,
    }

    if row_number.isdigit():
        payload["rowNumber"] = int(row_number)

    return payload


def _upload():
    try:
        if os.environ.get("GH_LOG_UPLOAD", "1").strip() == "0":
            return

        url = os.environ.get("GAS_WEBHOOK_URL", "").strip()

        if not url:
            return

        payload = _build_payload()

        if not payload["lines"]:
            return

        import requests

        response = requests.post(url, json=payload, timeout=POST_TIMEOUT_SECONDS)

        try:
            reply = response.json()
        except Exception:
            reply = {}

        sys.__stdout__.write(
            "[gh_log_uploader v1] log sent: ok={} saved={} lines={}\n".format(
                reply.get("ok"), reply.get("saved"), len(payload["lines"])
            )
        )
        sys.__stdout__.flush()

    except Exception as error:
        try:
            sys.__stdout__.write(
                "[gh_log_uploader v1] log upload failed: {}\n".format(
                    type(error).__name__
                )
            )
            sys.__stdout__.flush()
        except Exception:
            pass


if not isinstance(sys.stdout, _Tee):
    sys.stdout = _Tee(sys.stdout)

if not isinstance(sys.stderr, _Tee):
    sys.stderr = _Tee(sys.stderr)

atexit.register(_upload)
