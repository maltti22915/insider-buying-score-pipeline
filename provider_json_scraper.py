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
VERSION 11
  Requested directly: get MarketScreener (MS) data through GitHub instead of
  Scrape.do. A probe (ms_probe.py) showed a headed browser loads the MS page in
  about 7 s with the price and consensus blocks present, and fn_22_30's MS parser
  extracts every field from that HTML. New third provider "MS" (env ABBREV_MS,
  workflow input abbrev_ms): scrape_ms_data opens
  https://www.marketscreener.com/quote/stock/<abbrevMS>/, waits for any
  challenge to clear and posts the page HTML as data.html (target "MS", payload key
  abbrevMS) to the same webhook; Apps Script (fn_91_04) parses it with fn_22_30.
  Uses the same Cloudflare retry, step log, RUN_SUMMARY and re-post logic as SW.
  The Apps Script side starts in SHADOW mode (compares, writes nothing).
  NOT VERIFIED LIVE.

VERSION 10
  Requested directly ("fix first"). Log 84 had 3 unreadable webhook replies in
  13 runs (Rows 10 SW/AS: HTTP 200 text/html; Row 36 SW: HTTP 404 text/html)
  although Apps Script logged SUCCESS for Row 36. The scraper counted those as
  failures. Now post_provider_json re-posts the identical payload (up to 2 more
  times, 6 s apart, env POST_UNREADABLE_RETRIES) when the reply is unreadable or
  the POST itself fails; the write is idempotent (fixed cell), so it is safe. A
  readable reply is final. If every try is unreadable the reason becomes
  reply_unreadable_after_retries. NOT VERIFIED LIVE.

VERSION 9
  Requested directly ("optimize the process further"). Changes are based on
  the real log of 19 Simply Wall St launches (Oct 7), not on guesses:
    * headless was blocked 7 times out of 7 and never passed; headed passed
      5 of 12 launches. So the default LAUNCH_MODES is now just "headed"
      (override with env LAUNCH_MODES="headed,headless"). Each wasted headless
      launch cost about 60 s.
    * every Cloudflare challenge that cleared did so after 7.2-8.8 s, every other
      one was still there at 45 s. CF_CHALLENGE_WAIT_SECONDS is now 25 (about 3x
      the slowest observed clearing; env override CF_CHALLENGE_WAIT_SECONDS).
    * the time saved is spent on more attempts: DEFAULT_CF_RETRY_ATTEMPTS 3 -> 5
      (one headed launch each), pause 15-40 s -> 10-25 s, per-provider budget
      330 s -> 400 s. At the observed ~42% chance per headed attempt, 3 attempts
      succeed about 80% of the time, 5 attempts about 93%.
    * the 4 identical "Tried uc_gui_click_captcha()" lines per blocked launch
      are now one line with a count.
  Expected effect per row: a blocked launch costs about 55 s instead of about
  120 s (two modes of 45+ s each); a row that passes first time is unchanged.
  NOT VERIFIED LIVE beyond the log statistics above (small sample).

VERSION 8
  Requested directly: a much more detailed report in the log, so a failure says
  WHICH step failed and WHAT the page looked like ("button not found" plus the
  buttons that WERE there). Two additions, no scraping logic changed:
    * STEP lines. Every provider attempt prints, in order, lines like
        🔹 STEP SW a1/headed | 03 find_data_button | OK | count=1 | +14.2s
      (provider, attempt, browser mode, step number, step name, OK/FAIL/INFO,
      details, seconds since this browser launch). The same step names appear
      in the RUN_SUMMARY attempts as "step" (the last step reached).
    * FAILURE REPORT. Every failure that reaches the log now prints one block,
      "🔬 FAILURE REPORT | <provider> | step=<name> | reason=<text>", followed
      by indented lines: where the page is (URL, title, readyState, scroll),
      counts (buttons, links, visible buttons, inputs), every control whose text
      matches what the step was looking for (with visible/disabled flags), the
      texts of the visible buttons, any dialogs/overlays/consent banners that
      are showing, the page headings, a visible password field, and the first
      400 characters of page text. SW failures that used to print only counts
      ("no 'Data' button", "dialog never appeared") now print this block too.
  The report is read-only (it only reads the page), never raises, and is capped
  in size. A failure inside the report prints one warning line.

VERSION 7
  Requested directly: make the log easier for an AI to read as one picture of
  the run. At the end of every run (also when nothing was scraped) ONE line is
  printed, starting with the fixed marker "📋 RUN_SUMMARY " followed by a single
  JSON object (no line breaks, so one search finds it):
    {"v":"v7","sheet","row","runId","startedUtc","secondsTotal","providers":{
       "SW":{"abbrev","status","attempts":[{"n","mode","result","sec"}],
             "seconds","chars","column","reason"},
       "ASDCF":{...same fields..., "extractor":"as_dcf_extractor v3"}}}
  status is one of: ok | blocked (Cloudflare in every attempt) | error (the
  scrape or webhook failed) | not_written (scraped, webhook did not write) |
  skipped (no abbreviation). attempt result is: ok | blocked | error:<short>.
  The line is built from facts the run already has; no scraping logic changed,
  and building it can never raise (it is wrapped, a failure prints one warning).
  The summary reaches the Drive log through gh_log_uploader like every other
  line, so  grep RUN_SUMMARY  lists every run, one line each.

VERSION 6
  Requested directly: Simply Wall St was blocked by Cloudflare in both
  browser modes on several recent runs (Rows 34 and 30), while the same row
  can pass minutes later. A provider that is blocked in EVERY launch mode is
  now retried with a fresh browser: up to CF_RETRY_ATTEMPTS attempts in total
  (default 3, env override), with a random pause of CF_RETRY_WAIT_MIN..MAX
  seconds between attempts, and never starting a new attempt once
  CF_RETRY_BUDGET_SECONDS (default 330) have passed since the provider
  started, so a run stays inside the workflow timeout (raised to 20 minutes
  in provider_json_scraper.yml v3). Only a Cloudflare block is retried: any
  other failure (page changed, button missing, webhook error) behaves exactly
  as before and is NOT repeated. A success on any attempt stops the retries.
  The SW and AlphaSpread scraping code itself is unchanged.
  NOT VERIFIED LIVE: whether a retry actually passes a challenge that blocked
  the earlier attempt (same-row pass/fail minutes apart suggests it often does).

VERSION 5
  Second provider: AlphaSpread DCF (target "ASDCF"). New optional env var
  ABBREV_AS (e.g. "nasdaq/adsk"); when set, as_dcf_extractor.py (repo root,
  next to this file) opens alphaspread.com/security/<abbrev>/dcf-valuation,
  clicks "View Calculation" then "Full Model" and returns the whole model table
  (every year column, every row), the modal header and the selected row's side
  panel. This file posts it with target "ASDCF"; fn_90_00 routes that to
  fn_91_01, whose registry sends it to fn_91_03, which stores it in the "AS
  JSON" cell. Changes here:
    * ABBREV_AS env var, a "ASDCF" entry in the providers list, scrape_as_dcf().
    * post_provider_json: the abbreviation key was built as "abbrev" + target,
      which for ASDCF would be "abbrevASDCF"; the webhook reads "abbrevAS".
      ABBREV_KEY_BY_TARGET now names the exact key (SW still "abbrevSW").
    * as_dcf_extractor is imported inside try/except: if the file is missing
      from the repository only the AS provider fails, SW is unaffected.
    * AlphaSpread diagnostics: the full page HTML (modal included) and a
      screenshot go to ./diagnostics (as_row<N>_page.html / .png) on every run
      while SAVE_DIAGNOSTICS_ALWAYS is True, and on every AS failure together
      with a one-line page-state log (title, URL, first 300 text characters).
    * First log line now carries the version.
  NOT VERIFIED LIVE: the AlphaSpread clicks, what a logged-out browser may
  open, and the AS page under the headed/headless launch modes.

VERSION 4
  Third real run (Alibaba, row 32): headed mode passed Cloudflare (cleared
  after 10.7s), the Data button was found, the dialog opened and 6 sections
  were extracted. The saved dialog HTML (first look at the real DOM) shows
  a clean structure: <section role="dialog" aria-label="Share Price vs.
  Fair Value"> holding 6 <table>s, each with a <caption> (e.g. "NYSE:BABA
  Discounted Cash Flow Data Sources"), a <thead> and a <tbody>. The v1-v3
  extractor already handled this correctly (verified by running it against
  that HTML in a headless browser: 6 sections, ~4.7 KB of JSON), but it
  never read <caption>, the real section label, and its "before"/"after"
  sibling text was mostly wrong (e.g. every table's "after" was the same
  "Learn more about our DCF calculations" footer). Changes:
    * Each section now carries "caption" (the table's <caption> text).
    * "before"/"after" are no longer sent (misleading; the caption replaces
      them). fn_91_01 only deletes them when over the size limit, so it
      does not depend on them; fn_91_02 (not seen when this was written)
      should be checked.
    * DEFAULT_LAUNCH_MODES is now "headed,headless": headless was blocked in
      both real runs and only wastes ~45s before the headed attempt.

VERSION 3
  Second real run (Alibaba, row 32) showed the v2 page-state probe:
  title "Just a moment...", body "Performing security verification ...
  Cloudflare". The runner was stopped by a Cloudflare challenge, so there
  was never a "Data" button to find (the v2 scroll/attribute fixes could
  not matter yet). insider_score_scraper.py uses the SAME launch
  (SB(uc=True, headless=True) + uc_open_with_reconnect) and passes
  InsiderScreener's Cloudflare, so SW's challenge is simply stricter or
  slower; the launch line alone is not the difference. Changes:
    * After navigating, the page is checked for a Cloudflare challenge
      (title / body text). While it is showing, the script waits up to
      CF_CHALLENGE_WAIT_SECONDS for it to clear on its own and, in a
      HEADED browser only, also tries sb.uc_gui_click_captcha() every
      CF_CAPTCHA_CLICK_EVERY_SECONDS (it needs a real display; it cannot
      work headless).
    * A page that stays blocked raises CloudflareBlocked (a clear message
      plus screenshot) instead of the misleading "no Data button".
    * run_bot tries LAUNCH_MODES in order (default: headless, then
      headed). Headed on a Linux runner relies on SeleniumBase starting
      xvfb itself; if the headed browser cannot start, that is logged.
      Override with env LAUNCH_MODES="headed" or "headless,headed".
    * uc_open_with_reconnect uses reconnect_time=CF_RECONNECT_SECONDS (6).
    * The window is resized only AFTER the challenge has cleared (the
      working IS script never resizes).
  NOT verified: that either extra step actually clears SW's challenge from
  a GitHub Actions IP. Datacenter IPs are often challenged regardless of
  browser mode; if both modes stay blocked, the realistic options are a
  different network path (e.g. a residential proxy) or a self-hosted
  runner, not more code here.

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
import random
import re
import time
from datetime import datetime, timezone

import requests
from seleniumbase import SB

import gh_log_uploader

# AlphaSpread DCF extractor (v5). Optional: if the file is not in the
# repository root, only the AS provider fails; SW keeps working.
try:
    import as_dcf_extractor
except ImportError:
    as_dcf_extractor = None

# ----------------------------------------------------------------------------
# CONFIGURATION
# ----------------------------------------------------------------------------
# --- Cloudflare handling (v3) ---------------------------------------------
# Browser launch modes tried in order for each provider. "headless" is what
# insider_score_scraper.py uses; "headed" runs a real (virtual-display)
# window, which Cloudflare challenges less often (headless was blocked in
# both real runs, so headed goes first). Override with the env var
# LAUNCH_MODES, e.g. "headed" or "headless,headed".
DEFAULT_LAUNCH_MODES = "headed"  # v9: headless was blocked 7/7 in the real log

# --- Cloudflare retry (v6) -------------------------------------------------
# A provider blocked in EVERY launch mode is tried again with a fresh browser.
DEFAULT_CF_RETRY_ATTEMPTS = 5        # total attempts (env CF_RETRY_ATTEMPTS)
CF_RETRY_WAIT_MIN_SECONDS = 10       # random pause between attempts
CF_RETRY_WAIT_MAX_SECONDS = 25
CF_RETRY_BUDGET_SECONDS = 400        # no new attempt after this long per provider

# Seconds to wait for a Cloudflare challenge to clear on its own.
try:
    CF_CHALLENGE_WAIT_SECONDS = int(os.environ.get("CF_CHALLENGE_WAIT_SECONDS", "25"))
except ValueError:
    CF_CHALLENGE_WAIT_SECONDS = 25  # v9: clearing took 7-9 s whenever it cleared

# Seconds given to uc_open_with_reconnect (IS script uses 4).
CF_RECONNECT_SECONDS = 6

# Headed mode only: how often to try clicking the challenge checkbox.
CF_CAPTCHA_CLICK_EVERY_SECONDS = 12

# Lower-case fragments that mean "this is a Cloudflare challenge page".
CF_CHALLENGE_MARKERS = (
    "just a moment",
    "performing security verification",
    "verify you are human",
    "attention required",
)

# Browser window size set AFTER the page has loaded (desktop layout, above the md
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

# v5: the payload key under which the webhook reads each target's abbreviation.
# Default is "abbrev" + target ("SW" -> "abbrevSW"); targets whose key differs
# from that rule are listed here (ASDCF reads the row's abbrevAS).
ABBREV_KEY_BY_TARGET = {"ASDCF": "abbrevAS"}

# v5: how much of the AlphaSpread page HTML is saved as a diagnostics file.
AS_DIAGNOSTICS_MAX_HTML_CHARS = 3000000

AS_PAGE_STATE_JS = r"""
return {
  title: document.title,
  url: location.href,
  text: (document.body ? (document.body.innerText || '') : '')
          .replace(/\s+/g, ' ').trim().slice(0, 300)
};
"""


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
  var capEl = tbl.querySelector('caption');
  sections.push({
    caption: capEl ? clean(capEl.innerText || capEl.textContent) : '',
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


# ----------------------------------------------------------------------------
# v8: step trace and standard failure report
# ----------------------------------------------------------------------------
_STEP_CTX = {"provider": "", "attempt": 0, "mode": "", "t0": 0.0, "n": 0, "last": ""}

PAGE_REPORT_JS = r"""
var norm = function (s) { return String(s == null ? '' : s).replace(/\s+/g, ' ').trim(); };
var vis = function (el) {
  var r = el.getClientRects();
  if (!(r && r.length)) { return false; }
  var st = window.getComputedStyle(el);
  return st.visibility !== 'hidden' && st.display !== 'none';
};
var txt = function (el) { return norm(el.innerText !== undefined ? el.innerText : el.textContent); };
var pat = new RegExp(__PATTERN__, 'i');
var btns = Array.prototype.slice.call(document.querySelectorAll('button, [role="button"]'));
var links = Array.prototype.slice.call(document.querySelectorAll('a'));
var visBtns = btns.filter(vis);
var cands = [];
Array.prototype.slice.call(document.querySelectorAll('button, a, [role="button"], [role="tab"], [aria-label]')).forEach(function (el) {
  if (cands.length >= 12) { return; }
  var label = txt(el) + ' ' + (el.getAttribute('aria-label') || '') + ' ' + (el.getAttribute('title') || '');
  if (pat.test(label)) {
    cands.push({ tag: el.tagName.toLowerCase(), text: txt(el).slice(0, 60), aria: (el.getAttribute('aria-label') || '').slice(0, 50),
                 visible: vis(el), disabled: !!el.disabled, id: el.id || '', cls: norm(el.className && el.className.baseVal !== undefined ? el.className.baseVal : el.className).slice(0, 60) });
  }
});
var overlays = [];
Array.prototype.slice.call(document.querySelectorAll('[role="dialog"], [aria-modal="true"], dialog, [class*="modal"], [class*="cookie"], [class*="consent"], [id*="cookie"], [id*="consent"]')).forEach(function (el) {
  if (overlays.length >= 8 || !vis(el)) { return; }
  overlays.push({ tag: el.tagName.toLowerCase(), cls: norm(el.className && el.className.baseVal !== undefined ? el.className.baseVal : el.className).slice(0, 50), text: txt(el).slice(0, 120) });
});
var pw = false;
Array.prototype.slice.call(document.querySelectorAll('input[type="password"]')).forEach(function (el) { if (vis(el)) { pw = true; } });
return {
  url: location.href, title: document.title, readyState: document.readyState,
  scrollY: Math.round(window.scrollY || 0), scrollHeight: document.documentElement.scrollHeight || 0,
  buttons: btns.length, links: links.length, visibleButtons: visBtns.length,
  inputs: document.querySelectorAll('input, textarea, select').length,
  candidates: cands,
  buttonTexts: visBtns.slice(0, 30).map(function (b) { return (txt(b) || b.getAttribute('aria-label') || '(no text)').slice(0, 40); }),
  overlays: overlays,
  headings: Array.prototype.slice.call(document.querySelectorAll('h1, h2, h3')).filter(vis).slice(0, 8).map(function (h) { return txt(h).slice(0, 60); }),
  passwordField: pw,
  bodyStart: norm(document.body ? document.body.innerText : '').slice(0, 400)
};
"""


def step_begin(provider, attempt, mode):
    """Starts a new step trace for one browser launch."""
    _STEP_CTX.update({"provider": provider, "attempt": attempt, "mode": mode,
                      "t0": time.monotonic(), "n": 0, "last": ""})


def step(name, status="OK", **details):
    """Prints one numbered STEP line. Never raises."""
    try:
        _STEP_CTX["n"] += 1
        _STEP_CTX["last"] = name
        extra = "".join(" | {}={}".format(k, v) for k, v in details.items())
        print("🔹 STEP {} a{}/{} | {:02d} {} | {}{} | +{:.1f}s".format(
            _STEP_CTX["provider"], _STEP_CTX["attempt"], _STEP_CTX["mode"],
            _STEP_CTX["n"], name, status, extra, time.monotonic() - _STEP_CTX["t0"]))
    except Exception:
        pass


def failure_report(sb, step_name, reason, looking_for="."):
    """
    Prints the standard FAILURE REPORT block for the current provider. Read-only,
    never raises. looking_for is a regular expression for the control the step
    wanted (e.g. "^data$" or "calculation|model|dcf").
    """
    provider = _STEP_CTX.get("provider") or "?"

    try:
        step(step_name, "FAIL", reason=str(reason).replace("\n", " ")[:120])
        print("🔬 FAILURE REPORT | {} | step={} | reason={}".format(
            provider, step_name, str(reason).replace("\n", " ")[:200]))

        info = run_js(sb, PAGE_REPORT_JS.replace("__PATTERN__", json.dumps(looking_for)))

        if not isinstance(info, dict):
            print("🔬   (the page returned no readable report)")
            return

        print("🔬   where: url={} | title={!r} | readyState={} | scrollY={} of {}".format(
            info.get("url"), (info.get("title") or "")[:80], info.get("readyState"),
            info.get("scrollY"), info.get("scrollHeight")))
        print("🔬   counts: buttons={} (visible {}) | links={} | inputs={} | password field showing={}".format(
            info.get("buttons"), info.get("visibleButtons"), info.get("links"),
            info.get("inputs"), info.get("passwordField")))

        candidates = info.get("candidates") or []
        print("🔬   controls matching /{}/: {}".format(looking_for, len(candidates)))

        for number, c in enumerate(candidates, 1):
            print("🔬     {}. <{}> {!r} | aria={!r} | visible={} | disabled={} | id={!r} | class={!r}".format(
                number, c.get("tag"), c.get("text"), c.get("aria"), c.get("visible"),
                c.get("disabled"), c.get("id"), c.get("cls")))

        print("🔬   visible button texts: {}".format(json.dumps(info.get("buttonTexts") or [], ensure_ascii=False)[:700]))

        overlays = info.get("overlays") or []
        if overlays:
            print("🔬   overlays/dialogs/banners showing: {}".format(json.dumps(overlays, ensure_ascii=False)[:600]))
        else:
            print("🔬   overlays/dialogs/banners showing: none")

        print("🔬   headings: {}".format(json.dumps(info.get("headings") or [], ensure_ascii=False)[:400]))
        print("🔬   page text starts: {}".format((info.get("bodyStart") or "")[:400]))

    except Exception as report_error:
        print("⚠️ could not build the failure report: {}".format(report_error))


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


class CloudflareBlocked(RuntimeError):
    """The page is still a Cloudflare challenge after all waiting."""


def is_challenge_page(sb):
    """True when the title or visible text looks like a Cloudflare challenge."""
    try:
        title = (sb.get_title() or "").lower()
    except Exception:
        title = ""

    try:
        body = run_js(
            sb,
            "return String(document.body ? (document.body.innerText || '') : '')"
            ".slice(0, 600);",
        ) or ""
    except Exception:
        body = ""

    haystack = title + " " + str(body).lower()
    return any(marker in haystack for marker in CF_CHALLENGE_MARKERS)


def wait_past_challenge(sb, headless):
    """
    Waits up to CF_CHALLENGE_WAIT_SECONDS for a Cloudflare challenge to
    clear. In headed mode also tries sb.uc_gui_click_captcha() now and then.
    Returns True when the challenge is gone (or was never there).
    """
    if not is_challenge_page(sb):
        return True

    print("🛡️ Cloudflare challenge detected -- waiting for it to clear...")
    started = time.monotonic()
    last_click_at = None
    clicks = [0]

    def clicks_note():
        if clicks[0]:
            print("🖱️ Tried uc_gui_click_captcha() x{}".format(clicks[0]))

    while time.monotonic() - started < CF_CHALLENGE_WAIT_SECONDS:
        sb.sleep(2)

        if not is_challenge_page(sb):
            clicks_note()
            print(
                "🛡️ Challenge cleared after {:.1f}s".format(
                    time.monotonic() - started
                )
            )
            return True

        if not headless:
            now = time.monotonic()
            if last_click_at is None or now - last_click_at >= CF_CAPTCHA_CLICK_EVERY_SECONDS:
                last_click_at = now
                try:
                    sb.uc_gui_click_captcha()
                    clicks[0] += 1
                except Exception as click_error:
                    print("⚠️ uc_gui_click_captcha failed: {}".format(click_error))

    clicks_note()
    return not is_challenge_page(sb)


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


def scrape_sw_data(sb, abbrev_sw, row_number, headless=True):
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

    sb.uc_open_with_reconnect(url, reconnect_time=CF_RECONNECT_SECONDS)
    sb.sleep(PAGE_SETTLE_SECONDS)
    step("open_page", "OK", url=url)

    if not wait_past_challenge(sb, headless):
        step("cloudflare_check", "FAIL", reason="challenge page still showing")
        log_sw_page_state(sb)
        save_sw_diagnostics(sb, row_number, None, "blocked by Cloudflare")
        raise CloudflareBlocked(
            "page is still a Cloudflare challenge after {}s ({} browser)".format(
                CF_CHALLENGE_WAIT_SECONDS, "headless" if headless else "headed"
            )
        )

    step("cloudflare_check", "OK")

    try:
        sb.set_window_size(WINDOW_WIDTH, WINDOW_HEIGHT)
    except Exception as size_error:
        print("⚠️ could not set window size: {}".format(size_error))

    button_count = wait_for_data_buttons(sb)
    print("🔎 Visible 'Data' buttons found: {}".format(button_count))

    if not button_count:
        log_sw_page_state(sb)
        failure_report(
            sb, "find_data_button",
            "no 'Data' button appeared within {}s".format(SW_DATA_BUTTON_TIMEOUT_SECONDS),
            looking_for="^data$|toggle-data|\\bdata\\b")
        save_sw_diagnostics(sb, row_number, None, "no Data button")
        raise RuntimeError("no 'Data' button appeared on the page")

    step("find_data_button", "OK", count=button_count)

    dialog = None
    last_title = None

    for index in range(min(button_count, SW_MAX_DATA_BUTTONS_TO_TRY)):
        how = click_data_button(sb, index)
        print("🖱️ Clicked 'Data' button #{} ({})".format(index, how))
        step("click_data_button", "OK" if how else "FAIL", index=index, how=how)

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
            step("read_dialog", "OK", title=repr(last_title), sections=len(dialog.get("sections") or []))
            break

        step("read_dialog", "FAIL", index=index, reason="no matching dialog opened")
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
        failure_report(
            sb, "read_dialog",
            "no 'Share Price vs. Fair Value' dialog opened after {} 'Data' button(s)".format(
                min(button_count, SW_MAX_DATA_BUTTONS_TO_TRY)),
            looking_for="^data$|fair value|valuation")
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
# AlphaSpread DCF provider (v5)
# ----------------------------------------------------------------------------
def save_as_diagnostics(sb, row_number, reason):
    """
    Writes the AlphaSpread page's full HTML (the open modal included) and a
    screenshot into DIAGNOSTICS_DIR. Fully guarded -- never raises.
    """
    try:
        os.makedirs(DIAGNOSTICS_DIR, exist_ok=True)

        html = sb.get_page_source() or ""
        html_name = "as_row{}_page.html".format(row_number)
        with open(
            os.path.join(DIAGNOSTICS_DIR, html_name), "w", encoding="utf-8"
        ) as handle:
            handle.write(html[:AS_DIAGNOSTICS_MAX_HTML_CHARS])
        print(
            "🧾 Saved AlphaSpread page HTML ({} chars) -> {}/{} [{}]".format(
                min(len(html), AS_DIAGNOSTICS_MAX_HTML_CHARS),
                DIAGNOSTICS_DIR, html_name, reason
            )
        )

        shot_name = "as_row{}_page.png".format(row_number)
        sb.save_screenshot(shot_name, folder=DIAGNOSTICS_DIR)
        print("📸 Saved screenshot -> {}/{}".format(DIAGNOSTICS_DIR, shot_name))

    except Exception as error:
        print("⚠️ AS diagnostics themselves failed: {}".format(error))


def log_as_page_state(sb):
    """Logs title, URL and the first 300 visible characters. Never raises."""
    try:
        info = run_js(sb, AS_PAGE_STATE_JS)
        print(
            "🔬 AlphaSpread page state: {}".format(
                json.dumps(info, ensure_ascii=False)
            )
        )
    except Exception as info_error:
        print("⚠️ AS page-state probe failed: {}".format(info_error))


MS_MIN_HTML_CHARS = 30000


def scrape_ms_data(sb, abbrev_ms, row_number, headless=True):
    """
    v11: opens the MarketScreener quote page for abbrev_ms, waits for any
    challenge to clear and returns {"html", "url", "title", "htmlChars"}.
    The parsing happens in Apps Script (fn_22_30, target MS), not here.
    """
    url = "https://www.marketscreener.com/quote/stock/{}/".format(abbrev_ms)
    print("🌐 Navigating to: {}".format(url))
    sb.uc_open_with_reconnect(url, reconnect_time=CF_RECONNECT_SECONDS)
    sb.sleep(PAGE_SETTLE_SECONDS)
    step("open_page", "OK", url=url)

    if not wait_past_challenge(sb, headless):
        step("challenge_check", "FAIL", reason="challenge page still showing")
        raise CloudflareBlocked(
            "MarketScreener page is still a challenge after {}s ({} browser)".format(
                CF_CHALLENGE_WAIT_SECONDS, "headless" if headless else "headed"))
    step("challenge_check", "OK")

    html = sb.get_page_source() or ""
    title = sb.get_title() or ""
    if len(html) < MS_MIN_HTML_CHARS or not any(
            m in html for m in ("Last Close", "Consensus", "Capitalization")):
        step("read_page", "FAIL", chars=len(html), title=title[:60])
        failure_report(sb, "read_page", "page too small or without price/consensus blocks ({} chars)".format(len(html)),
                       looking_for="Last Close|Consensus|Capitalization")
        raise RuntimeError("MarketScreener page looks incomplete ({} chars, title {!r})".format(len(html), title[:60]))
    step("read_page", "OK", chars=len(html), title=title[:60])
    return {"html": html, "url": url, "title": title, "htmlChars": len(html)}


def scrape_as_dcf(sb, abbrev_as, row_number, headless=True):
    """
    Opens AlphaSpread's DCF page for abbrev_as, opens View Calculation ->
    Full Model and returns the JSON-ready dict built by as_dcf_extractor.
    Read-only: the extractor only ever clicks those two labels. Raises on any
    problem; run_bot catches that per provider, so SW is never blocked.
    """
    if as_dcf_extractor is None:
        raise RuntimeError(
            "as_dcf_extractor.py is not in the repository root -- AlphaSpread"
            " DCF skipped"
        )

    try:
        sb.set_window_size(WINDOW_WIDTH, WINDOW_HEIGHT)
    except Exception as size_error:
        print("⚠️ could not set window size: {}".format(size_error))

    try:
        step("run_extractor", "INFO", abbrev=abbrev_as)
        data = as_dcf_extractor.scrape_as_dcf_data(sb, abbrev_as)
        step("extract_table", "OK", periods=len(data.get("periods") or []),
             sections=len(data.get("sections") or []))

    except Exception as error:
        failure_report(sb, "as_dcf_" + (str(error).split(":")[0].strip().lower() or "failed")[:40],
                       str(error), looking_for="view calculation|full model|calculation|dcf")
        log_as_page_state(sb)
        save_as_diagnostics(sb, row_number, "scrape failed")

        if isinstance(error, as_dcf_extractor.AsDcfLoginRequired):
            print(
                "🔒 AlphaSpread asked for a login instead of opening the DCF"
                " model -- nothing was written."
            )

        raise

    if SAVE_DIAGNOSTICS_ALWAYS:
        save_as_diagnostics(sb, row_number, "always-on")

    return data


# ----------------------------------------------------------------------------
# Posting
# ----------------------------------------------------------------------------
# v7: facts about the last webhook post, read by run_bot's summary
_LAST_POST = {}


# v10: an unreadable reply (Google HTML error page although Apps Script
# succeeded) or a failed/timed-out POST is retried: the write goes to a fixed
# cell, so posting the same payload again only overwrites it with the same value.
POST_UNREADABLE_RETRIES = int(os.environ.get("POST_UNREADABLE_RETRIES", "2"))
POST_RETRY_PAUSE_SECONDS = 6


def post_provider_json(webhook_url, target, row_number, abbrev, sheet_name, data):
    """
    v10 wrapper: posts, and re-posts the identical payload (up to
    POST_UNREADABLE_RETRIES times) when the reply was unreadable or the POST
    itself failed. Any readable reply (written / refused / not written) is final.
    """
    posted = False
    for post_try in range(1, POST_UNREADABLE_RETRIES + 2):
        posted = _post_provider_json_once(webhook_url, target, row_number, abbrev, sheet_name, data)
        reason = str(_LAST_POST.get("reason") or "")
        if posted or not (reason == "reply_unreadable" or reason.startswith("post_failed")):
            if posted and post_try > 1:
                print("   (v10) confirmed on post try {}".format(post_try))
            return posted
        if post_try <= POST_UNREADABLE_RETRIES:
            print("🔁 Row {} {}: reply unreadable/POST failed ({}) -- re-posting the same payload in {} s (try {} of {})".format(
                row_number, target, reason, POST_RETRY_PAUSE_SECONDS, post_try + 1, POST_UNREADABLE_RETRIES + 1))
            time.sleep(POST_RETRY_PAUSE_SECONDS)
    _LAST_POST["reason"] = reason + "_after_retries"
    return posted


def _post_provider_json_once(webhook_url, target, row_number, abbrev, sheet_name, data):
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
        ABBREV_KEY_BY_TARGET.get(target.upper(), "abbrev" + target.upper()): abbrev,
        "data": data,
    }

    label = "Row {} ({}) {}".format(row_number, abbrev, target)

    try:
        response = requests.post(
            webhook_url, json=payload, timeout=WEBHOOK_TIMEOUT_SECONDS
        )
    except Exception as post_error:
        print("❌ {}: webhook POST itself failed: {}".format(label, post_error))
        _LAST_POST.clear(); _LAST_POST.update({"ok": False, "reason": "post_failed:" + type(post_error).__name__})
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
        _LAST_POST.clear(); _LAST_POST.update({"ok": False, "reason": "reply_unreadable"})
        return False

    if body.get("ok") and body.get("shadow"):
        # v11: MS shadow mode -- the webhook parsed and compared, wrote nothing, on purpose.
        print("✅ {}: parsed in SHADOW mode (nothing written): {}".format(label, json.dumps(body.get("summary"), ensure_ascii=False)[:400]))
        _LAST_POST.clear(); _LAST_POST.update({"ok": True, "chars": body.get("chars"), "column": "shadow"})
        return True

    if body.get("ok") and body.get("written"):
        print(
            "✅ {}: JSON written ({} chars, column {})".format(
                label, body.get("chars"), body.get("column")
            )
        )
        _LAST_POST.clear(); _LAST_POST.update({"ok": True, "chars": body.get("chars"), "column": body.get("column")})
        return True

    if body.get("ok"):
        print(
            "⏩ {}: webhook accepted but did not write ({})".format(
                label, body.get("reason")
            )
        )
        _LAST_POST.clear(); _LAST_POST.update({"ok": False, "reason": "not_written:" + str(body.get("reason"))})
        return False

    print("❌ {}: webhook refused/failed ({})".format(label, body.get("reason")))
    _LAST_POST.clear(); _LAST_POST.update({"ok": False, "reason": "refused:" + str(body.get("reason"))})
    return False


# ----------------------------------------------------------------------------
# v7: one-line machine-readable run summary
# ----------------------------------------------------------------------------
def print_run_summary(trace, sheet_name, row_number, run_started, run_started_utc):
    """Prints "📋 RUN_SUMMARY {json}" -- one line, never raises."""
    try:
        providers_out = {}

        for target, info in trace.items():
            entry = dict(info)

            if target == "ASDCF" and as_dcf_extractor is not None:
                entry["extractor"] = getattr(as_dcf_extractor, "VERSION", "?")

            providers_out[target] = entry

        summary = {
            "v": "v11",
            "sheet": sheet_name,
            "row": row_number,
            "runId": os.environ.get("GITHUB_RUN_ID", ""),
            "startedUtc": run_started_utc,
            "secondsTotal": round(time.monotonic() - run_started),
            "providers": providers_out,
        }
        print("📋 RUN_SUMMARY " + json.dumps(summary, ensure_ascii=False, separators=(",", ":")))
    except Exception as summary_error:
        print("⚠️ could not build RUN_SUMMARY: {}".format(summary_error))


# ----------------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------------
def run_bot():
    print("🤖 Booting up the provider-JSON scraper v11 (single-row mode)...")

    webhook_url = os.environ["GAS_WEBHOOK_URL"]
    row_number = int(os.environ["ROW_NUMBER"])
    sheet_name = os.environ["SHEET_NAME"]

    run_started = time.monotonic()
    run_started_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    trace = {}  # v7: per provider facts for the RUN_SUMMARY line

    # Every provider's abbreviation is OPTIONAL (default ''), exactly like
    # insider_score_scraper.py's abbrev_is / abbrev_as: a row may have any
    # subset of them, and an empty one just skips that provider.
    abbrev_sw = os.environ.get("ABBREV_SW", "").strip()
    abbrev_as = os.environ.get("ABBREV_AS", "").strip()  # v5
    abbrev_ms = os.environ.get("ABBREV_MS", "").strip()  # v11
    # Future: abbrev_gf = os.environ.get("ABBREV_GF", "").strip()

    print(
        "🎯 Sheet={} | Row={} | SW={} | AS={} | MS={}".format(
            sheet_name, row_number, abbrev_sw or "(none)", abbrev_as or "(none)", abbrev_ms or "(none)"
        )
    )

    # (target key, abbreviation, scrape function). Add GF here later.
    providers = [
        ("SW", abbrev_sw, scrape_sw_data),
        ("ASDCF", abbrev_as, scrape_as_dcf),
        ("MS", abbrev_ms, scrape_ms_data),
    ]

    if not any(abbrev for _, abbrev, _ in providers):
        print(
            "⏩ Row {}: no provider abbreviation was provided --"
            " nothing to scrape this run.".format(row_number)
        )
        print_run_summary(trace, sheet_name, row_number, run_started, run_started_utc)
        return

    modes_text = os.environ.get("LAUNCH_MODES", DEFAULT_LAUNCH_MODES)
    launch_modes = [
        m.strip().lower() for m in modes_text.split(",") if m.strip()
    ] or ["headless"]

    for target, abbrev, scrape in providers:
        if not abbrev:
            print(
                "⏩ Row {}: no abbreviation for {} -- skipping.".format(
                    row_number, target
                )
            )
            trace[target] = {"abbrev": "", "status": "skipped", "attempts": []}
            continue

        info = {"abbrev": abbrev, "status": "error", "attempts": []}
        trace[target] = info
        provider_clock = time.monotonic()

        # Each provider in its OWN try/except: one failing can never
        # block another from still being attempted and posted.
        try:
            attempts = max(1, int(os.environ.get("CF_RETRY_ATTEMPTS", DEFAULT_CF_RETRY_ATTEMPTS)))
        except ValueError:
            attempts = DEFAULT_CF_RETRY_ATTEMPTS

        provider_started = time.monotonic()

        for attempt in range(1, attempts + 1):
            if attempt > 1:
                pause = random.uniform(CF_RETRY_WAIT_MIN_SECONDS, CF_RETRY_WAIT_MAX_SECONDS)
                print("🔁 {}: blocked by Cloudflare in every mode -- retry {}/{} after {:.0f}s".format(
                    target, attempt, attempts, pause))
                time.sleep(pause)

            finished = False  # True = succeeded or failed for a non-Cloudflare reason: no retry

            for mode in launch_modes:
                headless = mode != "headed"
                browser_ready = False
                print("🚀 {}: launching {} browser{}".format(
                    target, mode, "" if attempt == 1 else " (attempt {})".format(attempt)))
                launch_clock = time.monotonic()
                _LAST_POST.clear()
                step_begin(target, attempt, mode)

                try:
                    with SB(uc=True, headless=headless) as sb:
                        browser_ready = True
                        data = scrape(sb, abbrev, row_number, headless)
                        posted = post_provider_json(
                            webhook_url, target, row_number, abbrev, sheet_name, data
                        )
                        step("post_to_sheet", "OK" if posted else "FAIL",
                             chars=_LAST_POST.get("chars"), column=_LAST_POST.get("column"),
                             reason=_LAST_POST.get("reason"))
                    info["attempts"].append({"n": attempt, "mode": mode, "result": "ok" if posted else "scraped_not_written",
                                             "step": _STEP_CTX["last"], "sec": round(time.monotonic() - launch_clock)})
                    info["status"] = "ok" if posted else "not_written"
                    for key in ("chars", "column", "reason"):
                        if _LAST_POST.get(key) is not None:
                            info[key] = _LAST_POST.get(key)
                    finished = True
                    break

                except CloudflareBlocked as blocked:
                    print(
                        "🛑 Row {} ({}): {} blocked in {} mode: {}".format(
                            row_number, abbrev, target, mode, blocked
                        )
                    )
                    info["attempts"].append({"n": attempt, "mode": mode, "result": "blocked",
                                             "step": _STEP_CTX["last"], "sec": round(time.monotonic() - launch_clock)})
                    info["status"] = "blocked"
                    continue

                except Exception as scrape_error:
                    print(
                        "❌ Row {} ({}): {} scrape itself failed ({} mode): {}".format(
                            row_number, abbrev, target, mode, scrape_error
                        )
                    )
                    info["attempts"].append({"n": attempt, "mode": mode,
                                             "result": "error:" + str(scrape_error).replace("\n", " ")[:80],
                                             "step": _STEP_CTX["last"], "sec": round(time.monotonic() - launch_clock)})
                    info["status"] = "error"
                    if not browser_ready:
                        # The browser itself could not start (e.g. no display
                        # for headed mode) -- try the next mode.
                        continue
                    finished = True
                    break

            if finished:
                break

            if time.monotonic() - provider_started >= CF_RETRY_BUDGET_SECONDS:
                print("⏹️ {}: retry time budget ({}s) used up -- giving up on this provider.".format(
                    target, CF_RETRY_BUDGET_SECONDS))
                break

        info["seconds"] = round(time.monotonic() - provider_clock)

    print_run_summary(trace, sheet_name, row_number, run_started, run_started_utc)
    print("🧹 Task complete!")


if __name__ == "__main__":
    run_bot()
