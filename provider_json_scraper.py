"""
provider_json_scraper.py
============================================================================

PURPOSE
----------------------------------------------------------------------------
Triggered ON DEMAND, for exactly ONE sheet row at a time, via GitHub's own
workflow_dispatch API (see provider_json_scraper.yml and Apps Script's
fn_24_73_TriggerProviderJsonRefresh_StockData_60). Uses a real browser
(SeleniumBase uc mode, same as insider_score_scraper.py) to open a data
provider's page, open the provider's own "Data" dialog, convert the tables
inside it to a JSON object, and POST that object to the Apps Script webhook
(doPost -> fn_91_01_ProviderJsonWebhook_StockData_60), which writes it as
one JSON string into the sheet cell reserved for that provider.

Deliberately SEPARATE from insider_score_scraper.py (Insider Buying Score +
AlphaSpread) so this new functionality can be tested on its own and can
never affect that already-working chain.

PROVIDER MODULES
----------------------------------------------------------------------------
Each provider is one small scrape function plus one entry in PROVIDERS
(see bottom of the configuration section / run_bot). Today only:

    SW -- Simply Wall St: /stocks/{abbrevSW}/valuation -> "Data" button ->
          "Share Price vs. Fair Value" dialog.

Adding GF later = one new scrape_gf_data() function, one new optional
abbrev_gf workflow input, one new PROVIDERS entry here, and one new handler
on the Apps Script side (fn_91_03). Providers are fully isolated from one
another: one failing never blocks another.

VERSION HISTORY
----------------------------------------------------------------------------
VERSION 2
  First real run (Alibaba, row 32) failed with "Visible 'Data' buttons
  found: 0". The page's own DevTools markup showed the button as
      <button data-cy-id="chart-action-toggle-data-dcf-chart"
              aria-label="Data"> ... <span class="hidden md:inline">Data
  inside a data-testid="intersection-renderer" block, i.e. a lazily
  rendered section that probably does not exist in the DOM until it has
  been scrolled into view. The scraper never scrolled. Changes:
    * wait_for_data_buttons() now scrolls down a step on every poll, so
      lazy "intersection-renderer" sections actually render.
    * SW_TAG_DATA_BUTTONS_JS now also matches a button by aria-label
      "Data" or a data-cy-id containing "toggle-data", not only by its
      visible text (the text span is hidden below the md breakpoint).
    * The browser window is set to 1600x1200 before navigating, so the
      layout matches the desktop view the markup was inspected in.
    * When no Data button is found, a "page state" probe is logged
      (title, URL, button counts, lazy-block count, page height, first
      300 chars of body text) so the next failure explains itself, e.g.
      a Cloudflare/consent wall versus a lazy-render problem.
  NOT verified against the real page: that the data-cy-id stays stable,
  and that the "dcf-chart" Data button opens the dialog titled
  "Share Price vs. Fair Value". The dialog title check below still
  guards against saving the wrong dialog.

VERSION 1 (NEW WORK)
  First version. The dialog's real DOM was NOT available when this was
  written (only screenshots), so the extraction is deliberately generic:
  every <table> / role="table" inside the dialog becomes one section with
  its own headers and rows, plus the text just before and after it. If the
  dialog has no table-like elements at all, its visible text lines are
  sent instead (sections stay empty, textLines is filled), so something
  still lands in the sheet. The dialog's own HTML and a screenshot are
  saved to ./diagnostics on every run (SAVE_DIAGNOSTICS_ALWAYS) and
  uploaded by the workflow as an artifact -- use them to tighten the
  extraction after the first real run, then flip that constant to False.
"""

import json
import os
import re
import time
from datetime import datetime, timezone

import requests
from seleniumbase import SB

# ----------------------------------------------------------------------------
# CONFIGURATION
# ----------------------------------------------------------------------------
# Browser window size set before navigating (desktop layout, above the md
# breakpoint, so responsive "hidden md:inline" labels are shown).
WINDOW_WIDTH = 1600
WINDOW_HEIGHT = 1200

# Seconds to let a freshly opened page settle before looking for buttons.
PAGE_SETTLE_SECONDS = 4

# How long to wait for the page's own "Data" button(s) to appear.
SW_DATA_BUTTON_TIMEOUT_SECONDS = 30

# Pixels scrolled down on every poll while waiting for the "Data" button,
# so lazily rendered sections (intersection-renderer) get built.
SW_SCROLL_STEP_PIXELS = 700

# How long to wait, after one click on a "Data" button, for the
# "Share Price vs. Fair Value" dialog (with at least one table) to appear.
SW_DIALOG_TIMEOUT_SECONDS = 20

# The page can hold several "Data" buttons (one per section). They are tried
# in document order until one opens the dialog whose title matches
# SW_DIALOG_TITLE_PATTERN; this caps how many are tried.
SW_MAX_DATA_BUTTONS_TO_TRY = 6

# Regex (case-insensitive) matched against the dialog's own title text.
SW_DIALOG_TITLE_PATTERN = r"share price vs\.?\s*fair value"

# Save the dialog HTML + screenshot on EVERY run (true while this is new).
SAVE_DIAGNOSTICS_ALWAYS = True
DIAGNOSTICS_DIR = "diagnostics"

WEBHOOK_BODY_PREVIEW_CHARS = 200
WEBHOOK_TIMEOUT_SECONDS = 120


def utc_clock_text():
    """Current UTC time as HH:MM:SS, for log lines."""
    return datetime.now(timezone.utc).strftime("%H:%M:%S")


def utc_iso_text():
    """Current UTC time as an ISO 8601 string (second precision)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_js(sb, function_body):
    """
    Runs a JavaScript function BODY in the page and returns its
    JSON-decoded result (None when nothing usable came back).

    Same helper, for the same reason, as insider_score_scraper.py's run_js:
    in uc-mode sb.execute_script can evaluate its string as a bare
    expression (a top-level "return" is then a SyntaxError), while plain
    Selenium wraps it as a function body. So the body is wrapped in an
    IIFE, its result is JSON.stringify'd inside the page, and both call
    shapes are tried in order.
    """
    iife = (
        "(function(){"
        " try {"
        " var __r = (function(){" + function_body + "})();"
        " return JSON.stringify(__r === undefined ? null : __r);"
        " } catch (e) {"
        " return JSON.stringify({__js_error: String(e)});"
        " }"
        "})()"
    )

    last_error = None
    for candidate in ("return " + iife + ";", iife):
        try:
            raw = sb.execute_script(candidate)
        except Exception as error:
            last_error = error
            continue

        if raw is None:
            continue

        result = json.loads(raw) if isinstance(raw, str) else raw

        if isinstance(result, dict) and "__js_error" in result:
            raise RuntimeError(result["__js_error"])

        return result

    if last_error is not None:
        raise last_error

    return None


def read_webhook_json(response, label):
    """
    Parses a webhook response as JSON, returning the parsed object, or None
    when the body is not valid JSON (after printing enough detail --
    status, content type, redirects, length, a body preview -- to tell an
    empty body, an HTML error page and a truncated response apart).
    """
    try:
        return response.json()
    except ValueError:
        pass

    try:
        body_text = response.text or ""
    except Exception:
        body_text = ""

    preview = re.sub(r"\s+", " ", body_text).strip()[:WEBHOOK_BODY_PREVIEW_CHARS]

    print(
        "⚠️ {}: webhook response was not valid JSON | HTTP {} |"
        " content-type={} | redirects={} | body length={} chars".format(
            label,
            response.status_code,
            response.headers.get("Content-Type"),
            len(response.history),
            len(body_text),
        )
    )
    print(
        "   body (first {} chars): {}".format(
            WEBHOOK_BODY_PREVIEW_CHARS, preview if preview else "(empty)"
        )
    )

    return None


# ----------------------------------------------------------------------------
# SW (Simply Wall St) -- JavaScript run inside the page
# ----------------------------------------------------------------------------
# Lists every visible element that is a "Data" button -- matched by its own
# text being exactly "Data", OR by aria-label "Data", OR by a data-cy-id
# containing "toggle-data" (the text span is hidden below the md breakpoint,
# and the attributes are the more stable hook). Tags each with
# data-sw-scrape-idx="<n>" so Python can click a specific one, and returns
# how many there are.
SW_TAG_DATA_BUTTONS_JS = r"""
function clean(s) { return String(s || '').replace(/\s+/g, ' ').trim(); }
function visible(el) {
  return !!(el && (el.offsetWidth || el.offsetHeight ||
    (el.getClientRects && el.getClientRects().length)));
}
var old = document.querySelectorAll('[data-sw-scrape-idx]');
for (var o = 0; o < old.length; o++) {
  old[o].removeAttribute('data-sw-scrape-idx');
}
var nodes = document.querySelectorAll('button, a, [role="button"]');
var n = 0;
for (var i = 0; i < nodes.length; i++) {
  var el = nodes[i];
  var byAttr = /^data$/i.test(clean(el.getAttribute('aria-label') || '')) ||
    /toggle-data/i.test(el.getAttribute('data-cy-id') || '');
  if ((/^data$/i.test(clean(el.innerText || el.textContent)) || byAttr) &&
      visible(el)) {
    el.setAttribute('data-sw-scrape-idx', String(n));
    n++;
  }
}
return n;
"""

# Snapshot of the page's state, logged when no Data button was found, so the
# failure explains itself (blocked/consent page vs. lazy render vs. wrong
# markup).
SW_PAGE_STATE_JS = r"""
return {
  title: document.title,
  url: location.href,
  buttons: document.querySelectorAll('button').length,
  dataCyToggleData: document.querySelectorAll('[data-cy-id*="toggle-data"]').length,
  ariaLabelData: document.querySelectorAll('button[aria-label="Data"]').length,
  lazyBlocks: document.querySelectorAll('[data-testid="intersection-renderer"]').length,
  scrollHeight: document.documentElement.scrollHeight,
  scrollY: window.scrollY,
  bodyStart: String(document.body ? (document.body.innerText || '') : '')
    .replace(/\s+/g, ' ').slice(0, 300)
};
"""

# Optional, guarded cookie/consent dismissal. Clicks at most one button whose
# text is a plain "accept"-style label AND which sits inside an element that
# mentions cookies/consent/privacy. Returns the clicked label or null.
SW_DISMISS_CONSENT_JS = r"""
function clean(s) { return String(s || '').replace(/\s+/g, ' ').trim(); }
var LABEL = /^(accept( all)?( cookies)?|i agree|agree|allow all|got it)$/i;
var nodes = document.querySelectorAll('button, [role="button"]');
for (var i = 0; i < nodes.length; i++) {
  var el = nodes[i];
  var label = clean(el.innerText || el.textContent);
  if (!LABEL.test(label)) { continue; }
  var p = el.parentElement, hops = 0, banner = false;
  while (p && hops < 6) {
    if (/cookie|consent|privacy/i.test(p.textContent || '')) { banner = true; break; }
    p = p.parentElement; hops++;
  }
  if (banner) { el.click(); return label; }
}
return null;
"""

# Finds the open "Share Price vs. Fair Value" dialog and converts its tables
# to plain data. TITLE_PATTERN is substituted in by Python before running.
SW_EXTRACT_DIALOG_JS = r"""
var TITLE_RE = new RegExp(__TITLE_PATTERN__, 'i');
function clean(s) { return String(s || '').replace(/\s+/g, ' ').trim(); }
function visible(el) {
  return !!(el && (el.offsetWidth || el.offsetHeight ||
    (el.getClientRects && el.getClientRects().length)));
}
var TABLE_SEL = 'table, [role="table"], [role="grid"]';

// 1) every visible, near-leaf element whose text IS the dialog title
var all = document.querySelectorAll('body *');
var headings = [];
for (var i = 0; i < all.length; i++) {
  var el = all[i];
  if (el.children.length > 3) { continue; }
  var t = clean(el.textContent);
  if (t.length < 80 && TITLE_RE.test(t) && visible(el)) { headings.push(el); }
}

// 2) from each, climb to the smallest ancestor that also holds a table (or
//    the words "Data Point"); the SMALLEST such ancestor over all headings
//    is the dialog (the page's own section heading, if it shares the title,
//    only reaches a much larger container, or none).
var root = null, rootLen = Infinity, rootHeading = null;
for (var h = 0; h < headings.length; h++) {
  var node = headings[h];
  while (node && node !== document.body) {
    var tx = node.textContent || '';
    if (/data point/i.test(tx) || node.querySelector(TABLE_SEL)) {
      if (tx.length < rootLen) {
        root = node; rootLen = tx.length; rootHeading = headings[h];
      }
      break;
    }
    node = node.parentElement;
  }
}
if (!root) { return {found: false, headingCount: headings.length}; }

// Title = the SHORTEST matching heading text inside the dialog (a wrapper
// element that also holds, e.g., the close button has longer text).
var title = '';
for (var q = 0; q < headings.length; q++) {
  if (root.contains(headings[q])) {
    var ht = clean(headings[q].textContent);
    if (!title || ht.length < title.length) { title = ht; }
  }
}

function cellTexts(row) {
  var cells = row.querySelectorAll(
    'th, td, [role="columnheader"], [role="rowheader"], [role="cell"], [role="gridcell"]');
  var out = [];
  for (var c = 0; c < cells.length; c++) {
    out.push(clean(cells[c].innerText || cells[c].textContent));
  }
  return out;
}
function isHeaderRow(row) {
  if (row.closest('thead')) { return true; }
  if (row.querySelector('th, [role="columnheader"]') &&
      !row.querySelector('td, [role="cell"], [role="gridcell"]')) { return true; }
  return false;
}
function siblingText(start, dir) {
  var n = start, depth = 0;
  while (n && n !== root && depth < 6) {
    var p = (dir < 0) ? n.previousElementSibling : n.nextElementSibling;
    while (p) {
      var pt = clean(p.innerText || p.textContent);
      var holdsTable = (p.matches && p.matches(TABLE_SEL)) || p.querySelector(TABLE_SEL);
      if (pt && !holdsTable) { return pt.slice(0, 300); }
      p = (dir < 0) ? p.previousElementSibling : p.nextElementSibling;
    }
    n = n.parentElement; depth++;
  }
  return '';
}

var tableEls = root.querySelectorAll(TABLE_SEL);
var sections = [];
for (var k = 0; k < tableEls.length; k++) {
  var tbl = tableEls[k];
  var rowEls = tbl.querySelectorAll('tr, [role="row"]');
  var headers = [], rows = [];
  for (var r = 0; r < rowEls.length; r++) {
    var row = rowEls[r];
    if (row.closest(TABLE_SEL) !== tbl) { continue; }   // skip nested tables' rows
    var cellsText = cellTexts(row);
    if (!cellsText.length) { continue; }
    if (!headers.length && isHeaderRow(row)) { headers = cellsText; }
    else { rows.push(cellsText); }
  }
  if (!headers.length && !rows.length) { continue; }
  sections.push({
    before: siblingText(tbl, -1),
    after: siblingText(tbl, 1),
    headers: headers,
    rows: rows
  });
}

var lines = [];
if (!sections.length) {
  var rawLines = String(root.innerText || root.textContent || '').split(/\n+/);
  for (var L = 0; L < rawLines.length; L++) {
    var line = clean(rawLines[L]);
    if (line) { lines.push(line); }
  }
}

return {
  found: true,
  title: title,
  sections: sections,
  lines: lines,
  html: root.outerHTML,
  headingCount: headings.length
};
"""


def sw_page_url(abbrev_sw):
    """Simply Wall St valuation page for one abbrevSW (4 path segments)."""
    return "https://simplywall.st/stocks/{}/valuation".format(abbrev_sw)


def save_sw_diagnostics(sb, row_number, dialog_html, reason):
    """
    Writes the dialog's HTML (when known) and a screenshot into
    DIAGNOSTICS_DIR, so a first real run shows exactly what the page
    looked like. Fully guarded -- never raises.
    """
    try:
        os.makedirs(DIAGNOSTICS_DIR, exist_ok=True)

        if dialog_html:
            path = os.path.join(
                DIAGNOSTICS_DIR, "sw_row{}_dialog.html".format(row_number)
            )
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(dialog_html)
            print(
                "🧾 Saved dialog HTML ({} chars) -> {} [{}]".format(
                    len(dialog_html), path, reason
                )
            )

        shot_name = "sw_row{}_page.png".format(row_number)
        sb.save_screenshot(shot_name, folder=DIAGNOSTICS_DIR)
        print("📸 Saved screenshot -> {}/{}".format(DIAGNOSTICS_DIR, shot_name))

    except Exception as error:
        print("⚠️ SW diagnostics themselves failed: {}".format(error))


def log_sw_page_state(sb):
    """Logs a one-line snapshot of the page's state. Never raises."""
    try:
        info = run_js(sb, SW_PAGE_STATE_JS)
        print(
            "🔬 Page state at failure: {}".format(
                json.dumps(info, ensure_ascii=False)
            )
        )
    except Exception as info_error:
        print("⚠️ page-state probe failed: {}".format(info_error))


def wait_for_data_buttons(sb):
    """
    Polls until at least one visible 'Data' button exists. Returns count.

    Scrolls down a step on every poll: the chart sections live inside
    lazily rendered "intersection-renderer" blocks that may not exist in
    the DOM until they have been scrolled into view.
    """
    deadline = time.monotonic() + SW_DATA_BUTTON_TIMEOUT_SECONDS
    consent_tried = False
    count = 0

    while time.monotonic() < deadline:
        count = run_js(sb, SW_TAG_DATA_BUTTONS_JS) or 0
        if count:
            return count

        if not consent_tried:
            # A consent banner can cover/replace page content; try once.
            consent_tried = True
            try:
                clicked = run_js(sb, SW_DISMISS_CONSENT_JS)
                if clicked:
                    print("🍪 Dismissed a consent banner ({})".format(clicked))
            except Exception:
                pass

        try:
            run_js(
                sb,
                "window.scrollBy(0, {}); return window.scrollY;".format(
                    int(SW_SCROLL_STEP_PIXELS)
                ),
            )
        except Exception:
            pass

        sb.sleep(1)

    return 0


def click_data_button(sb, index):
    """Native click on the index-th tagged 'Data' button, JS click fallback."""
    selector = '[data-sw-scrape-idx="{}"]'.format(index)

    try:
        sb.click(selector, timeout=5)
        return "native"
    except Exception:
        pass

    try:
        result = run_js(
            sb,
            "var b = document.querySelector("
            + json.dumps(selector)
            + "); if (!b) { return 'missing'; }"
            " b.scrollIntoView({block: 'center'}); b.click(); return 'clicked';",
        )
        return "js:{}".format(result)
    except Exception:
        return None


def poll_for_dialog(sb):
    """
    Polls for the open dialog (with at least one table, or fallback text
    lines). Returns the extractor's result dict, or None on timeout.
    """
    deadline = time.monotonic() + SW_DIALOG_TIMEOUT_SECONDS
    pattern = json.dumps(SW_DIALOG_TITLE_PATTERN)
    extract_js = SW_EXTRACT_DIALOG_JS.replace("__TITLE_PATTERN__", pattern)
    last = None

    while time.monotonic() < deadline:
        try:
            last = run_js(sb, extract_js)
        except Exception as error:
            print("⚠️ dialog extraction attempt raised: {}".format(error))
            last = None

        if last and last.get("found"):
            if last.get("sections") or last.get("lines"):
                return last

        sb.sleep(1)

    return last if (last and last.get("found")) else None


def scrape_sw_data(sb, abbrev_sw, row_number):
    """
    Opens the Simply Wall St valuation page for abbrev_sw, clicks the
    "Data" button, waits for the "Share Price vs. Fair Value" dialog and
    returns the JSON-ready dict described in the module docstring.

    Raises on navigation problems, a page with no "Data" button, or a
    dialog that never opened -- run_bot catches that per provider, so one
    provider's failure can never block another.
    """
    url = sw_page_url(abbrev_sw)
    print("🌐 Navigating to: {}".format(url))

    try:
        sb.set_window_size(WINDOW_WIDTH, WINDOW_HEIGHT)
    except Exception as size_error:
        print("⚠️ could not set window size: {}".format(size_error))

    sb.uc_open_with_reconnect(url, reconnect_time=4)
    sb.sleep(PAGE_SETTLE_SECONDS)

    button_count = wait_for_data_buttons(sb)
    print("🔎 Visible 'Data' buttons found: {}".format(button_count))

    if not button_count:
        log_sw_page_state(sb)
        save_sw_diagnostics(sb, row_number, None, "no Data button")
        raise RuntimeError("no 'Data' button appeared on the page")

    dialog = None
    last_title = None

    for index in range(min(button_count, SW_MAX_DATA_BUTTONS_TO_TRY)):
        how = click_data_button(sb, index)
        print("🖱️ Clicked 'Data' button #{} ({})".format(index, how))

        dialog = poll_for_dialog(sb)

        if dialog:
            last_title = dialog.get("title")
            print(
                "✅ Dialog found after button #{} | title={!r} |"
                " sections={} | fallback lines={}".format(
                    index,
                    last_title,
                    len(dialog.get("sections") or []),
                    len(dialog.get("lines") or []),
                )
            )
            break

        print("⏩ Button #{} opened no matching dialog; trying the next.".format(index))

        # Close whatever may have opened, so the next click is clean.
        try:
            sb.send_keys("body", "\ue00c")  # ESCAPE
            sb.sleep(1)
        except Exception:
            pass

        # Re-tag in case the page re-rendered and dropped the markers.
        run_js(sb, SW_TAG_DATA_BUTTONS_JS)

    if not dialog:
        save_sw_diagnostics(sb, row_number, None, "dialog never appeared")
        raise RuntimeError(
            "no 'Share Price vs. Fair Value' dialog opened after trying"
            " {} 'Data' button(s)".format(min(button_count, SW_MAX_DATA_BUTTONS_TO_TRY))
        )

    if SAVE_DIAGNOSTICS_ALWAYS:
        save_sw_diagnostics(sb, row_number, dialog.get("html"), "always-on")

    data = {
        "source": "simplywall.st",
        "page": "valuation",
        "url": url,
        "scrapedAtUtc": utc_iso_text(),
        "dialogTitle": dialog.get("title"),
        "sections": dialog.get("sections") or [],
    }

    if not data["sections"]:
        data["textLines"] = dialog.get("lines") or []

    return data


# ----------------------------------------------------------------------------
# Posting
# ----------------------------------------------------------------------------
def post_provider_json(webhook_url, target, row_number, abbrev, sheet_name, data):
    """
    POSTs one provider's JSON to the Apps Script webhook (the SAME Web App
    URL as insider_score_scraper.py -- one doPost per project -- routed
    there by the payload's own "target" field). Returns True only when the
    webhook confirmed it actually wrote the cell.
    """
    # The webhook reads the abbreviation under the exact key its provider
    # registry names: abbrevSW for target "SW", abbrevGF for "GF", ...
    payload = {
        "target": target,
        "sheetName": sheet_name,
        "rowNumber": row_number,
        "abbrev" + target.upper(): abbrev,
        "data": data,
    }

    label = "Row {} ({}) {}".format(row_number, abbrev, target)

    try:
        response = requests.post(
            webhook_url, json=payload, timeout=WEBHOOK_TIMEOUT_SECONDS
        )
    except Exception as post_error:
        print("❌ {}: webhook POST itself failed: {}".format(label, post_error))
        return False

    reply_received_at = utc_clock_text()
    body = read_webhook_json(response, label)

    try:
        print(
            "   {} webhook reply (UTC {}): ".format(target, reply_received_at)
            + json.dumps(body, ensure_ascii=False)[:1500]
        )
    except Exception:
        pass

    if body is None:
        print(
            "   The response could not be read, so it is unknown whether the"
            " webhook wrote the value -- check the sheet or Apps Script"
            " Executions before assuming it failed."
        )
        return False

    if body.get("ok") and body.get("written"):
        print(
            "✅ {}: JSON written ({} chars, column {})".format(
                label, body.get("chars"), body.get("column")
            )
        )
        return True

    if body.get("ok"):
        print(
            "⏩ {}: webhook accepted but did not write ({})".format(
                label, body.get("reason")
            )
        )
        return False

    print("❌ {}: webhook refused/failed ({})".format(label, body.get("reason")))
    return False


# ----------------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------------
def run_bot():
    print("🤖 Booting up the provider-JSON scraper (single-row mode)...")

    webhook_url = os.environ["GAS_WEBHOOK_URL"]
    row_number = int(os.environ["ROW_NUMBER"])
    sheet_name = os.environ["SHEET_NAME"]

    # Every provider's abbreviation is OPTIONAL (default ''), exactly like
    # insider_score_scraper.py's abbrev_is / abbrev_as: a row may have any
    # subset of them, and an empty one just skips that provider.
    abbrev_sw = os.environ.get("ABBREV_SW", "").strip()
    # Future: abbrev_gf = os.environ.get("ABBREV_GF", "").strip()

    print(
        "🎯 Sheet={} | Row={} | SW={}".format(
            sheet_name, row_number, abbrev_sw or "(none)"
        )
    )

    # (target key, abbreviation, scrape function). Add GF here later.
    providers = [
        ("SW", abbrev_sw, scrape_sw_data),
    ]

    if not any(abbrev for _, abbrev, _ in providers):
        print(
            "⏩ Row {}: no provider abbreviation was provided --"
            " nothing to scrape this run.".format(row_number)
        )
        return

    with SB(uc=True, headless=True) as sb:
        for target, abbrev, scrape in providers:
            if not abbrev:
                print(
                    "⏩ Row {}: no abbreviation for {} -- skipping.".format(
                        row_number, target
                    )
                )
                continue

            # Each provider in its OWN try/except: one failing can never
            # block another from still being attempted and posted.
            try:
                data = scrape(sb, abbrev, row_number)
                post_provider_json(
                    webhook_url, target, row_number, abbrev, sheet_name, data
                )
            except Exception as scrape_error:
                print(
                    "❌ Row {} ({}): {} scrape itself failed: {}".format(
                        row_number, abbrev, target, scrape_error
                    )
                )

    print("🧹 Task complete!")


if __name__ == "__main__":
    run_bot()
