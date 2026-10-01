"""
============================================================================
insider_score_scraper.py
============================================================================

PURPOSE
----------------------------------------------------------------------------
Triggered ON DEMAND, for exactly ONE company at a time, via GitHub's own
workflow_dispatch API -- called directly from this project's own Google
Apps Script row-refresh pipeline (fn_24_05) whenever the user refreshes a
specific row, rather than running on a fixed daily schedule for every
configured company at once. Uses SeleniumBase's uc
("undetected-chromedriver") mode to fetch that one company's own real
InsiderScreener company page, and POSTs the resulting raw HTML to a
Google Apps Script webhook (fn_90_01_InsiderScoreWebhook_StockData_60),
which scores it using that project's own already-built, already-verified
"Insider Buying Score" logic.

VERSION 9 (REQUESTED DIRECTLY, REAL CONFIRMED RISK): the AlphaSpread wait
no longer ends on "whichever of the two selectors appears first". v6 waited
on both as one CSS list. A real Row 34 (Chemometec) run matched
.intrinsic-value-history__verdict and the webhook then reported
VALUE_NULL; the Apps Script side treats the verdict element as the wrong
widget for "AS vs usual", and on the same page the real
.valuation-history-context__headline can still be loading when the verdict
is already present, so the combined wait could end too early.
  (1) The scraper now waits for the headline element ALONE for
      ALPHASPREAD_FALLBACK_AFTER_SECONDS (25s).
  (2) Only if the headline has not appeared by then, it keeps polling for
      the rest of ALPHASPREAD_WAIT_TIMEOUT_SECONDS (60s) and accepts the
      verdict element ONLY when it holds real, non-empty text; the headline
      still wins if it shows up at any point. This keeps the page-markup
      fallback from v6 (some pages may serve only the new component) while
      removing the early-exit on an empty verdict shell.
  (3) To go strictly headline-only, set ALPHASPREAD_ACCEPT_VERDICT_FALLBACK
      = False (the wait then runs the full timeout for the headline alone).
  (4) The matched-element logging (v7/v8) and failure diagnostics are
      unchanged; no .yml change is needed (the selectors are not in it).

VERSION 8 (REQUESTED DIRECTLY, REAL CONFIRMED BUG): the v7 element
diagnostic never actually worked. A real Row 34 (Chemometec) run printed
"could not read element content: SyntaxError: Illegal return statement"
(column 58 of the script, exactly where its own "return null;" sat)
instead of the matched element's text. In this script's own uc-mode
session, sb.execute_script evaluates the string as a bare expression
(the error object is a DevTools-protocol evaluation result), NOT as a
function body the way plain Selenium does, so a top-level "return" is
illegal and "arguments[0]" would not exist either. The same flaw sat in
save_alphaspread_diagnostics' own visible-text read (its error was
swallowed, so it only ever reported "unavailable").
  (1) New run_js helper: wraps a function body in an immediately-invoked
      function, JSON.stringify's the result inside the page (so objects
      survive either evaluation mode), and tries a "return (...)" form
      first (classic Selenium) then a bare-expression form (uc/CDP
      evaluation), JSON-decoding whatever comes back. Selectors are
      embedded with json.dumps instead of passed as arguments[0].
  (2) describe_matched_elements and the diagnostics' visible-text read
      now both use run_js.
  (3) Behaviour otherwise unchanged: both helpers stay fully guarded and
      can never affect the scrape, the webhook POST or the other
      provider's own scrape. Only the log output changes -- it should
      now finally show whether a matched element had real text or was
      an empty/loading shell (the question v7 was built to answer).

VERSION 7 (REQUESTED DIRECTLY, REAL CONFIRMED BLIND SPOTS): three
observability fixes, found by reading a real Row 34 (Chemometec) run
where v6 correctly matched the new .intrinsic-value-history__verdict
element but the AS webhook then answered "accepted but did not write
(VALUE_NULL)", and the log could not say why.
  (1) EVERY AS scrape now prints the matched element's own visible text
      (and whether that text is empty) plus an HTML snippet, not just
      the selector that matched. This is what distinguishes "the element
      was still empty/loading when the wait returned" from "the element
      had real text the webhook's parser could not read".
  (2) AS diagnostics (page summary, screenshot, HTML) are now also saved
      when the webhook answers "not written" or refuses/fails -- not only
      when the scrape itself throws. v6 only covered the timeout case, so
      the VALUE_NULL run left nothing to inspect.
  (3) When a webhook response is not valid JSON, the HTTP status code,
      content type, redirect count, body length and the first 200
      characters of the body are now logged (shared read_webhook_json
      helper, used by both the IS and AS posts), and the message no
      longer implies the write failed. The real Row 34 IS run printed
      "webhook POST itself failed: Expecting value: line 1 column 1"
      while Apps Script's own log showed the score had in fact been
      written -- an unreadable response is not the same as a failed
      write, and the log must not say so.

VERSION 6 (REQUESTED DIRECTLY, REAL CONFIRMED FAILURE): the AlphaSpread
scrape now waits for EITHER of AlphaSpread's two known "valuation
history" markup shapes, and saves real diagnostics when the wait fails.
A real GitHub Actions run for Row 34 (Chemometec, cse/chemm) showed the
Insider Buying Score half succeeding while the AS half failed with
"Element {.valuation-history-context__headline} was not found after 60
seconds" -- while fn_22_30 v87 (Apps Script side) had already learned
that AlphaSpread can serve a second, structurally different component
(intrinsic-value-history__verdict) INSTEAD of the original headline for
some stock pages. v4/v5 waited only for the original selector, so on a
page using the newer component this script could wait its full timeout
for an element that would never appear, no matter how long it waited.
v6 waits for either selector (one combined CSS selector list) and logs
which one matched. On any AS scrape failure it now also prints a compact
page summary into the run log (title, URL, which selectors are present,
whether the page looks like a Cloudflare/consent interstitial, and the
first part of the visible text) and writes the page's own screenshot and
HTML into ./diagnostics/ so the workflow can upload them as an artifact
(see insider_score_scraper.yml's own matching v6 entry). The cause of
the Row 34 failure itself is NOT yet confirmed -- the new selector is the
leading hypothesis, and the diagnostics exist so the next failure
explains itself instead of ending in a bare "not found".

VERSION 5 (REQUESTED DIRECTLY, REAL CONFIRMED GAP): abbrev_is is now ALSO
optional (default '', mirroring abbrev_as's own v4 treatment exactly),
rather than a required environment variable read. Previously a row with
a real, resolved AlphaSpread abbreviation but NO InsiderScreener coverage
at all (a genuine, real possibility -- these are two independent
providers with independent company coverage) could never trigger this
workflow at all, since the required ABBREV_IS read would raise a
KeyError the moment it was left blank. See run_bot's own real logic for
the full detail; insider_score_scraper.yml's own matching VERSION 5 entry
covers the input-declaration side of this same fix.

VERSION 4 (REQUESTED DIRECTLY, NEW WORK): this same script, and the same
already-running browser session, now ALSO optionally scrapes AlphaSpread's
own "valuation history" block for the "AS vs usual" column -- see
scrape_alphaspread_html's own docstring for the full motivation. This
project's own earlier attempts to get this one field via Google Apps
Script's own Scrape.do-based fetch pipeline (a headless-render API with a
CSS-selector wait, bounded by that API's own request-level timeout) were
shown, across an extensive real diagnostic investigation
(fn_99_01-fn_99_04), to fail unpredictably even at a 40-second wait,
because the underlying AlphaSpread component is a genuinely LAZY-LOADED
Livewire component whose real load time varies between a few seconds and
longer than any bounded API timeout can reliably wait for. A real browser
here has no equivalent per-request timeout/proxy-rotation cost, so it can
simply wait as long as this one page genuinely needs. This is entirely
optional per run (an empty/missing ABBREV_AS input skips it cleanly) and
completely independent of the existing Insider Buying Score scrape --
either one failing can never block the other.

VERSION 2 (REQUESTED DIRECTLY, ARCHITECTURE CHANGE): the original v1 of
this script ran on a fixed daily schedule, reading EVERY configured
company's own abbrevIS directly from the sheet via the Sheets API, and
scraping all of them in one run. Replaced entirely -- the actual intent
was always an on-demand, single-row refresh, triggered as part of the
existing per-row refresh pipeline already used throughout this whole
project, not a separate, independent daily bulk job. This version scrapes
exactly the one company it is told to, via its own row_number/abbrev_is
GitHub Actions inputs -- it no longer reads the sheet at all, and no
longer requires Sheets API credentials or a Service Account of any kind.

WHY THIS EXISTS AT ALL (unchanged from v1)
----------------------------------------------------------------------------
Every fetch approach reachable from Google Apps Script itself (Scrape.do's
own render+super, a targeted wait/networkidle2 variant, a direct no-proxy
request, and ZenRows' own dedicated antibot=true engine) consistently
failed InsiderScreener's own real Cloudflare challenge-platform
protection. Apps Script's own UrlFetchApp has no real browser capability
at all, and neither Scrape.do's nor ZenRows' own remote browser instances
passed this specific site's own fingerprint check either.

SeleniumBase's uc mode runs a genuinely patched Chromium instance built
specifically to defeat this exact class of detection -- confirmed
directly against the person's own already-working example project
scraping this same site's own /en/explore/{country} pages, and now
confirmed directly working against the specific /en/company/{slug} pages
this project's own scoring logic actually needs (14 of 16 companies
scored correctly on this script's own first real run, in its own earlier
v1 form).

ASYNCHRONOUS TIMING -- WORTH KNOWING
----------------------------------------------------------------------------
fn_24_05 triggers this workflow via GitHub's own workflow_dispatch API,
which returns immediately once the run has been queued -- it does not
wait for this script to actually finish. This means the rest of a row's
own refresh (SW/GF/MS/AS/everything else) completes and is visible on the
sheet well before this script has even finished launching its own
browser, let alone scraping the page and posting back. "Insider Buying
Score" will visibly update a little later than the rest of that same
row, once this run actually completes and the webhook writes the value --
not instantly alongside everything else. This is an accepted, deliberate
trade-off, not a bug -- blocking the whole row refresh until a real
browser-based scrape finishes would cost far more time than it is worth.

WHAT THIS SCRIPT DOES NOT DO
----------------------------------------------------------------------------
- Does not compute the score itself. The webhook it posts to reuses this
  project's own existing fn_22_30 parsing/scoring logic directly.
- Does not write anything to the spreadsheet directly. All writes happen
  through the webhook, which also re-verifies the row's own abbrevIS has
  not changed since the caller (fn_24_05) last resolved it, before
  writing anything.
- Does not read the spreadsheet at all, in this version -- row_number and
  abbrev_is are provided directly as inputs by the caller that triggered
  this workflow, which already has that row's own current data in hand.

REQUIRED GITHUB ACTIONS SECRETS
----------------------------------------------------------------------------
GAS_WEBHOOK_URL       -- this project's own deployed
                         fn_90_01_InsiderScoreWebhook_StockData_60 Web App
                         URL.

REQUIRED GITHUB ACTIONS INPUTS (provided by the caller triggering this
workflow, not read from anywhere by this script itself)
----------------------------------------------------------------------------
row_number  -- the specific row on the target sheet this run is for.
abbrev_is   -- OPTIONAL as of VERSION 5. That row's own current
               InsiderScreener company slug. When absent or empty, the
               Insider Buying Score scrape is skipped entirely.
sheet_name  -- the real sheet this row lives on (e.g. "Salkku", "Watch") --
               VERSION 3 addition, see that version's own changelog entry
               below for why this is now required rather than assumed.
abbrev_as   -- OPTIONAL, VERSION 4 addition. That row's own current
               AlphaSpread abbreviation (e.g. "nasdaq/adsk"). When absent
               or empty, the AlphaSpread scrape is skipped entirely and
               this run behaves exactly as it did before v4 -- Insider
               Buying Score only.

REQUIRED PYTHON PACKAGES (requirements.txt)
----------------------------------------------------------------------------
seleniumbase
requests

VERSION
----------------------------------------------------------------------------
v7 -- Requested directly, real confirmed blind spots (Row 34,
  cse/chemm): every AS scrape now logs the matched element's text and
  an HTML snippet (describe_matched_elements); AS diagnostics are also
  saved when the webhook answers "not written" or refuses/fails, via
  post_alphaspread_to_webhook now returning whether it wrote; and
  non-JSON webhook responses now log status code, content type,
  redirect count, body length and the first 200 body characters
  (read_webhook_json), with wording that no longer claims the write
  failed. Insider Buying Score scraping and scoring unchanged. See this
  file's own top PURPOSE section's own VERSION 7 paragraph.

v6 -- Requested directly, real confirmed failure (Row 34, cse/chemm): the
  AS scrape now waits for either known valuation-history markup shape
  (.valuation-history-context__headline OR
  .intrinsic-value-history__verdict) instead of only the first, logs
  which one matched, and on any AS scrape failure prints a compact page
  summary to the run log and saves the page's screenshot and HTML to
  ./diagnostics/ (uploaded as a workflow artifact by the matching
  insider_score_scraper.yml v6 step). Insider Buying Score path
  unchanged. See this file's own top PURPOSE section's own VERSION 6
  paragraph for the full detail.

v5 -- Requested directly, real confirmed gap: abbrev_is is now ALSO
  optional, mirroring abbrev_as's own v4 treatment. See this file's own
  top PURPOSE section's own VERSION 5 paragraph for the full detail.

v4 -- Requested directly, new work: added an entirely
  optional, independent AlphaSpread "valuation history" scrape
  (scrape_alphaspread_html/post_alphaspread_to_webhook), reusing this same
  script's own already-running browser session. See this file's own top
  PURPOSE section's own VERSION 4 paragraph for the full motivation and
  fn_90_01's own matching VERSION 5 changelog entry for the receiving
  webhook side. Only runs when a real ABBREV_AS environment variable is
  provided; the existing Insider Buying Score path is completely
  unchanged and unaffected either way.

v3 -- Requested directly, real confirmed bug: SHEET_NAME used to be a
  hardcoded module-level constant, always "Salkku", regardless of which
  real sheet a given row-refresh actually came from. A real production
  run showed the receiving webhook (fn_90_01) refusing a genuinely
  correct write, reporting a completely unrelated company for a row that
  in truth only ever held the expected one -- because the webhook's own
  mismatch check was comparing against Column D on the WRONG sheet
  entirely (always "Salkku", never the row's own real sheet, e.g.
  "Watch"). Fixed: sheet_name is now a real, required GitHub Actions
  input (see insider_score_scraper.yml's own matching changelog entry),
  read here via a real environment variable and passed through to the
  webhook explicitly, the same way row_number/abbrev_is already were.

v2 -- Requested directly, architecture change: on-demand single-row
  trigger (via GitHub's own workflow_dispatch inputs), replacing v1's own
  daily bulk-scrape-everything design entirely. No longer reads the sheet
  at all; no longer requires Sheets API credentials or a Service Account.

v1 -- First version -- read every configured company's own abbrevIS from
  the sheet directly (Sheets API), scraped each one's own real company
  page with SeleniumBase's uc mode, and posted the resulting HTML to the
  webhook for scoring, on a fixed daily schedule.
============================================================================
"""

import json
import os
import re

import requests
from seleniumbase import SB


# ----------------------------------------------------------------------------
# CONFIGURATION
# ----------------------------------------------------------------------------
# VERSION 3 FIX (REQUESTED DIRECTLY, REAL CONFIRMED BUG): SHEET_NAME used
# to be a hardcoded constant here, always "Salkku" -- regardless of which
# real sheet (e.g. "Watch") a given row-refresh actually came from. A real
# production run showed the receiving webhook (fn_90_01) refusing a
# genuinely correct write, reporting a completely unrelated company for a
# row that in truth only ever held the expected one -- because the
# webhook's own mismatch check was comparing against Column D on the
# WRONG sheet entirely (always "Salkku", never the row's own real sheet).
# Now read directly from the real "sheet_name" GitHub Actions input (see
# insider_score_scraper.yml's own matching v3 changelog entry, and
# fn_24_71's own matching v2 entry on the Apps Script side) inside run_bot
# below, not hardcoded here at all.

# Real Cloudflare-protected challenges can take a genuine few seconds to
# resolve even inside a real, patched browser -- confirmed necessary
# directly, since this project's own earlier Apps Script-side experiments
# (a Scrape.do-based customWait=8000/waitUntil=networkidle2 variant)
# already established that this specific challenge needs real time to
# settle, not just a real browser.
PAGE_LOAD_SETTLE_SECONDS = 6

# VERSION 4 ADDITION (REQUESTED DIRECTLY, NEW WORK): the maximum time to
# wait for AlphaSpread's own "valuation history" block to render, using a
# REAL, condition-based wait (SeleniumBase's own wait_for_element) rather
# than a fixed sleep -- the core advantage this approach has over the
# project's own earlier Scrape.do-based attempts, which were bounded by
# Scrape.do's own request-level ceiling and were shown, across several
# real diagnostic runs, to sometimes fail even at a 40-second wait while
# a separate, fresh attempt succeeded in as little as 3-5 seconds. A real
# browser with no per-request proxy/rotation cost can simply wait longer,
# with no equivalent penalty for doing so.
ALPHASPREAD_WAIT_TIMEOUT_SECONDS = 60

# VERSION 6 CHANGE (REQUESTED DIRECTLY, REAL CONFIRMED FAILURE):
# AlphaSpread appears to serve at least two structurally different markup
# shapes for the "valuation history" block (see fn_22_30 v87 on the Apps
# Script side, which already falls back from the original headline to
# intrinsic-value-history__verdict). v4/v5 waited only for the first, so
# a page using the second could never satisfy the wait. Both selectors
# are now waited on together as one CSS selector list -- whichever
# appears first ends the wait.
ALPHASPREAD_HEADLINE_SELECTORS = [
    ".valuation-history-context__headline",
    ".intrinsic-value-history__verdict",
]
ALPHASPREAD_WAIT_SELECTOR = ", ".join(ALPHASPREAD_HEADLINE_SELECTORS)

# VERSION 9 ADDITION: the headline is the real target; the verdict element
# is only an opt-in fallback, accepted only with non-empty text after the
# headline has had ALPHASPREAD_FALLBACK_AFTER_SECONDS to appear on its own.
ALPHASPREAD_PRIMARY_SELECTOR = ALPHASPREAD_HEADLINE_SELECTORS[0]
ALPHASPREAD_FALLBACK_SELECTOR = ALPHASPREAD_HEADLINE_SELECTORS[1]
ALPHASPREAD_ACCEPT_VERDICT_FALLBACK = True
ALPHASPREAD_FALLBACK_AFTER_SECONDS = 25

# VERSION 6 ADDITION: where AS failure diagnostics (screenshot + HTML) are
# written. Relative to the workflow's working directory; the matching
# insider_score_scraper.yml v6 step uploads this folder as an artifact.
DIAGNOSTICS_DIR = "diagnostics"

# VERSION 6 ADDITION: how many characters of the page's visible text to
# print into the run log when an AS scrape fails.
DIAGNOSTIC_TEXT_PREVIEW_CHARS = 500

# VERSION 7 ADDITIONS: how much of a matched valuation-history element's
# own text / outer HTML to print on every AS scrape, and how much of a
# non-JSON webhook response body to print (REQUESTED DIRECTLY: first 200
# characters).
ELEMENT_TEXT_PREVIEW_CHARS = 300
ELEMENT_HTML_SNIPPET_CHARS = 600
WEBHOOK_BODY_PREVIEW_CHARS = 200


def run_js(sb, function_body):
    """
    VERSION 8 ADDITION (REQUESTED DIRECTLY, REAL CONFIRMED BUG): runs a
    JavaScript function BODY in the page and returns its JSON-decoded
    result (None when nothing usable came back).

    WHY: in this script's uc-mode session sb.execute_script can evaluate
    its string as a bare expression, where a top-level "return" is a
    SyntaxError ("Illegal return statement") and "arguments" does not
    exist. Plain Selenium instead wraps the string as a function body,
    where a bare expression returns nothing. So the body is wrapped in an
    IIFE, its result is JSON.stringify'd inside the page (objects then
    survive either mode), and both call shapes are tried in order.

    Raises the last error if neither shape works; callers stay guarded.
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


def scrape_company_html(sb, abbrev_is):
    """
    Fetches the real, complete HTML of one company's own InsiderScreener
    page, using SeleniumBase's own uc-mode browser.
    """
    target_url = "https://www.insiderscreener.com/en/company/{}".format(
        abbrev_is
    )

    print("🌐 Navigating to: {}".format(target_url))

    sb.uc_open_with_reconnect(target_url, reconnect_time=4)

    # Give the real Cloudflare challenge time to fully resolve, and the
    # page's own real content to render, before reading the HTML back out.
    sb.sleep(PAGE_LOAD_SETTLE_SECONDS)

    return sb.get_page_source()


def wait_for_alphaspread_block(sb):
    """
    VERSION 9 ADDITION: waits for AlphaSpread's valuation-history block.
    The headline element alone is waited on first. After
    ALPHASPREAD_FALLBACK_AFTER_SECONDS the verdict element is also accepted,
    but only when it has real, non-empty text. Raises if neither is usable
    within ALPHASPREAD_WAIT_TIMEOUT_SECONDS (the caller already catches it).
    """
    first_wait = (
        ALPHASPREAD_FALLBACK_AFTER_SECONDS
        if ALPHASPREAD_ACCEPT_VERDICT_FALLBACK
        else ALPHASPREAD_WAIT_TIMEOUT_SECONDS
    )

    try:
        sb.wait_for_element(ALPHASPREAD_PRIMARY_SELECTOR, timeout=first_wait)
        return
    except Exception as primary_error:
        if not ALPHASPREAD_ACCEPT_VERDICT_FALLBACK:
            raise primary_error

    print(
        "⚠️ Headline not present after {}s; also accepting a non-empty"
        " verdict element for up to {} more seconds.".format(
            ALPHASPREAD_FALLBACK_AFTER_SECONDS,
            ALPHASPREAD_WAIT_TIMEOUT_SECONDS
            - ALPHASPREAD_FALLBACK_AFTER_SECONDS,
        )
    )

    remaining = max(
        1, ALPHASPREAD_WAIT_TIMEOUT_SECONDS - ALPHASPREAD_FALLBACK_AFTER_SECONDS
    )

    for _ in range(int(remaining)):
        try:
            if sb.is_element_present(ALPHASPREAD_PRIMARY_SELECTOR):
                return
        except Exception:
            pass

        try:
            if sb.is_element_present(ALPHASPREAD_FALLBACK_SELECTOR):
                details = run_js(
                    sb,
                    "var el = document.querySelector("
                    + json.dumps(ALPHASPREAD_FALLBACK_SELECTOR)
                    + "); if (!el) { return ''; }"
                    " return (el.innerText || el.textContent || '');",
                )
                if isinstance(details, str) and details.strip():
                    print("ℹ️ Using non-empty verdict element as fallback.")
                    return
        except Exception:
            pass

        sb.sleep(1)

    raise Exception(
        "Neither {} nor a non-empty {} appeared within {} seconds".format(
            ALPHASPREAD_PRIMARY_SELECTOR,
            ALPHASPREAD_FALLBACK_SELECTOR,
            ALPHASPREAD_WAIT_TIMEOUT_SECONDS,
        )
    )


def scrape_alphaspread_html(sb, abbrev_as):
    """
    VERSION 4 ADDITION (REQUESTED DIRECTLY, NEW WORK): fetches the real,
    complete HTML of one company's own AlphaSpread summary page, waiting
    for the "valuation history" block's own real headline element to
    actually appear (via SeleniumBase's own condition-based
    wait_for_element) rather than a fixed sleep.

    VERSION 6 CHANGE: waits for EITHER known markup shape of that block
    (see ALPHASPREAD_HEADLINE_SELECTORS) rather than only the original
    headline element, and logs which one actually matched.

    VERSION 7 CHANGE: also logs the matched element's own text and an
    HTML snippet (describe_matched_elements), since a selector merely
    being present does not prove the lazy-loaded block had finished
    filling in. The original
    only-first-selector wait could never succeed on a page that serves
    the newer intrinsic-value-history__verdict component instead.

    WHY THIS EXISTS: this project's own earlier Apps Script pipeline
    fetched this same page via Scrape.do's own headless-render API with a
    playWithBrowser WaitSelector action, capped at a fixed timeout
    (raised progressively from 15s to 40s across several real production
    fixes). Extensive, real diagnostic testing (this project's own
    fn_99_01/fn_99_02/fn_99_03/fn_99_04 investigation) confirmed directly
    that this specific block is a genuinely LAZY-LOADED Livewire
    component (AlphaSpread's own explicit design choice, not an
    incidental slow query) whose real load time varies widely between
    attempts -- as little as 3-5 seconds on one fresh attempt, and still
    incomplete at a full 40-second wait on another, with no way to
    predict which in advance. A real browser, running here with no
    per-request proxy-rotation cost and no arbitrarily-bounded API
    timeout, can simply wait as long as this one page genuinely needs,
    the same way a real user's own browser would.

    Does NOT use uc_open_with_reconnect (that mechanism exists
    specifically to defeat InsiderScreener's own Cloudflare
    challenge-platform protection) -- AlphaSpread has shown no equivalent
    challenge in this project's own real fetch history via Scrape.do
    (confirmed working there without any comparable anti-bot bypass),
    so a plain sb.open() is used here instead, reusing the SAME already-
    running uc-mode browser session regardless (uc=True affects how the
    whole browser session presents itself, not each individual
    navigation), which costs nothing extra and keeps this function
    consistent with the rest of this same run.

    Raises whatever SeleniumBase's own wait_for_element raises
    (a real timeout exception) if neither element appears within
    ALPHASPREAD_WAIT_TIMEOUT_SECONDS -- the caller (run_bot) is
    responsible for catching this, exactly as it already does for
    scrape_company_html's own failures, so one scrape failing can never
    block the other.
    """
    target_url = "https://www.alphaspread.com/security/{}/summary".format(
        abbrev_as
    )

    print("🌐 Navigating to: {}".format(target_url))

    sb.open(target_url)

    print(
        "⏳ Waiting up to {}s for the real valuation-history element"
        " ({}) to appear (real browser, no fixed sleep)...".format(
            ALPHASPREAD_WAIT_TIMEOUT_SECONDS,
            ALPHASPREAD_PRIMARY_SELECTOR
            + (
                " (verdict fallback after {}s, non-empty only)".format(
                    ALPHASPREAD_FALLBACK_AFTER_SECONDS
                )
                if ALPHASPREAD_ACCEPT_VERDICT_FALLBACK
                else ""
            ),
        )
    )

    wait_for_alphaspread_block(sb)

    # VERSION 7: log which markup shape this page actually served AND
    # what that element actually contained, on every scrape (not only
    # failures) -- see describe_matched_elements.
    describe_matched_elements(sb)

    return sb.get_page_source()


def describe_matched_elements(sb):
    """
    VERSION 7 ADDITION (REQUESTED DIRECTLY, REAL CONFIRMED BLIND SPOT):
    for each known valuation-history selector that is present on the
    page, prints its own visible text, whether that text is empty, its
    child-element count, and a snippet of its outer HTML.

    WHY: v6 only printed which selector matched. A real Row 34 run
    matched .intrinsic-value-history__verdict and the webhook then
    reported VALUE_NULL, with nothing in the log to show whether the
    element had real text (a parser problem) or was still an empty or
    loading shell when the wait returned (a wait problem). This output
    answers that on every scrape, including successful ones, so a
    working run can be compared with a failing one.

    Fully guarded -- never raises, never affects the scrape itself.
    """
    # VERSION 8: a function BODY run via run_js (no top-level-return
    # problem in uc mode); the selector is embedded, not "arguments[0]".
    def build_script(selector):
        return (
            "var el = document.querySelector(" + json.dumps(selector) + ");"
            " if (!el) { return null; }"
            " return {text: (el.innerText || el.textContent || ''),"
            " html: (el.outerHTML || ''),"
            " children: el.children ? el.children.length : 0};"
        )

    matched_any = False

    for selector in ALPHASPREAD_HEADLINE_SELECTORS:
        try:
            if not sb.is_element_present(selector):
                continue
        except Exception:
            continue

        matched_any = True
        print("🔎 Matched valuation-history element: {}".format(selector))

        try:
            details = run_js(sb, build_script(selector))
        except Exception as error:
            print("   (could not read element content: {})".format(error))
            continue

        if not details:
            print("   (element disappeared before its content could be read)")
            continue

        text = re.sub(r"\s+", " ", details.get("text") or "").strip()
        html_snippet = re.sub(r"\s+", " ", details.get("html") or "").strip()

        print(
            "   text length: {} | text empty: {} | child elements: {}".format(
                len(text), not text, details.get("children")
            )
        )
        print(
            "   text (first {} chars): {}".format(
                ELEMENT_TEXT_PREVIEW_CHARS,
                text[:ELEMENT_TEXT_PREVIEW_CHARS] if text else "(empty)",
            )
        )
        print(
            "   HTML (first {} chars): {}".format(
                ELEMENT_HTML_SNIPPET_CHARS,
                html_snippet[:ELEMENT_HTML_SNIPPET_CHARS],
            )
        )

    if not matched_any:
        print("🔎 No known valuation-history element is present on the page.")


def read_webhook_json(response, label):
    """
    VERSION 7 ADDITION (REQUESTED DIRECTLY, REAL CONFIRMED MISLEADING
    LOG): parses a webhook response as JSON, returning the parsed object,
    or None if the body is not valid JSON.

    When parsing fails, prints the HTTP status code, content type,
    redirect count, body length, and the first WEBHOOK_BODY_PREVIEW_CHARS
    characters of the body, so an empty body, an HTML error page, and a
    truncated response can be told apart from the log alone.

    label -- a short prefix for the log lines, e.g. "Row 34 (abbrev)".
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


def save_alphaspread_diagnostics(sb, row_number, abbrev_as, reason="scrape failed"):
    """
    VERSION 6 ADDITION (REQUESTED DIRECTLY, REAL CONFIRMED FAILURE): when
    the AS scrape fails (typically the wait timing out), records what
    the browser was actually looking at so the failure explains itself.

    VERSION 7 CHANGE: also called when the scrape succeeded but the
    webhook answered "not written" or refused/failed (a real Row 34 run
    ended in VALUE_NULL with nothing saved to inspect). The new reason
    argument says which situation this is in the log.

    Does two things, each independently guarded so a failure in one (or
    in this whole function) can never raise out of it or affect the rest
    of the run:

    1. Prints a compact summary into the run log: page title, current
       URL, which of the known valuation-history selectors are present,
       whether the page looks like a Cloudflare/consent/blocked
       interstitial, the page source length, and the first part of the
       page's visible text.
    2. Writes the page's own screenshot and full HTML into
       DIAGNOSTICS_DIR, for the workflow's own upload-artifact step.

    Not a fix for anything by itself -- it only observes.
    """
    print(
        "🩺 AS diagnostics for Row {} ({}) -- reason: {}".format(
            row_number, abbrev_as, reason
        )
    )

    try:
        print("   title: {}".format(sb.get_title()))
    except Exception as error:
        print("   title: (unavailable: {})".format(error))

    try:
        print("   url: {}".format(sb.get_current_url()))
    except Exception as error:
        print("   url: (unavailable: {})".format(error))

    for selector in ALPHASPREAD_HEADLINE_SELECTORS:
        try:
            print(
                "   present {}: {}".format(
                    selector, sb.is_element_present(selector)
                )
            )
        except Exception as error:
            print("   present {}: (check failed: {})".format(selector, error))

    page_source = ""

    try:
        page_source = sb.get_page_source() or ""
        lowered = page_source.lower()
        print("   page source length: {} chars".format(len(page_source)))
        print(
            "   looks like interstitial/blocked: {}".format(
                any(
                    marker in lowered
                    for marker in (
                        "just a moment",
                        "challenge-platform",
                        "access denied",
                        "captcha",
                        "cookie consent",
                        "consent",
                    )
                )
            )
        )
        print(
            "   mentions livewire: {} | mentions wire:snapshot: {}".format(
                "livewire" in lowered, "wire:snapshot" in lowered
            )
        )
    except Exception as error:
        print("   page source: (unavailable: {})".format(error))

    try:
        visible_text = run_js(
            sb, "return document.body ? document.body.innerText : '';"
        ) or ""
        visible_text = re.sub(r"\s+", " ", visible_text).strip()
        print(
            "   visible text (first {} chars): {}".format(
                DIAGNOSTIC_TEXT_PREVIEW_CHARS,
                visible_text[:DIAGNOSTIC_TEXT_PREVIEW_CHARS],
            )
        )
    except Exception as error:
        print("   visible text: (unavailable: {})".format(error))

    safe_abbrev = re.sub(r"[^A-Za-z0-9_-]+", "_", abbrev_as)
    base_name = "as_row{}_{}".format(row_number, safe_abbrev)

    try:
        os.makedirs(DIAGNOSTICS_DIR, exist_ok=True)
    except Exception as error:
        print("   could not create {}: {}".format(DIAGNOSTICS_DIR, error))
        return

    try:
        sb.save_screenshot(base_name + ".png", folder=DIAGNOSTICS_DIR)
        print("   saved screenshot: {}/{}.png".format(DIAGNOSTICS_DIR, base_name))
    except Exception as error:
        print("   screenshot not saved: {}".format(error))

    try:
        if page_source:
            with open(
                os.path.join(DIAGNOSTICS_DIR, base_name + ".html"),
                "w",
                encoding="utf-8",
            ) as html_file:
                html_file.write(page_source)
            print("   saved HTML: {}/{}.html".format(DIAGNOSTICS_DIR, base_name))
    except Exception as error:
        print("   HTML not saved: {}".format(error))


def print_purchase_breakdown(purchase_details):
    """
    Prints the full per-purchase breakdown the webhook passed back --
    each real transaction that fed into the final score, with its own
    date, role, role points, planned-discount multiplier, magnitude
    multiplier (added directly, new work: the transaction's own real
    USD-equivalent value, banded into a 0.7x-1.5x multiplier), and final
    points. Requested directly, debugging convenience: this print
    output lands in GitHub Actions' own run log, a single, easy-to-reach
    place to see exactly which transactions produced a given score,
    without needing this project's own separate Apps Script Executions
    panel for the webhook at all.
    """
    if not purchase_details:
        print("   (no purchases counted within the 6-month window)")
        return

    for detail in purchase_details:
        usd_value = detail.get("usdEquivalentValue")
        currency = detail.get("currency")

        if usd_value is not None:
            value_text = "~${:,.0f} ({})".format(usd_value, currency)
        elif currency:
            value_text = "unrecognized currency ({})".format(currency)
        else:
            value_text = "value not found"

        print(
            "   {} | {} | role={} | rolePoints={} | plannedMultiplier={} | "
            "value={} | magnitudeMultiplier={} | points={:.1f}".format(
                detail.get("date"),
                detail.get("typeText"),
                detail.get("role"),
                detail.get("rolePoints"),
                detail.get("multiplier"),
                value_text,
                detail.get("magnitudeMultiplier"),
                detail.get("points", 0),
            )
        )


def post_to_webhook(webhook_url, row_number, abbrev_is, sheet_name, html):
    """
    Posts this company's own scraped HTML to the Apps Script webhook,
    which re-verifies the row still matches and writes the computed
    score, using this project's own existing fn_22_30 scoring logic.

    sheet_name -- VERSION 3 FIX (REQUESTED DIRECTLY, REAL CONFIRMED
    BUG): now a real parameter, passed through from run_bot's own real
    SHEET_NAME environment variable read, rather than a hardcoded
    module-level constant. A real production run showed the webhook
    refusing a genuinely correct write, reporting a completely
    unrelated company for a row that in truth only ever held the
    expected one -- because this function was always sending
    "Salkku" regardless of which real sheet the refresh actually came
    from, so the webhook's own mismatch check was comparing against
    the wrong sheet's own Column D entirely.

    timeout=120 -- confirmed necessary directly from a real v1 run: two
    companies with a genuinely large transaction history (AppLovin,
    Constellation Software) failed at a shorter timeout, one with a
    clean read timeout and the other with an empty response body (the
    connection dropping before a timeout could even register cleanly) --
    both companies' own real InsiderScreener pages are large enough that
    the whole POST-and-score round trip can genuinely take longer than a
    short timeout allows.
    """
    payload = {
        "sheetName": sheet_name,
        "rowNumber": row_number,
        "abbrevIS": abbrev_is,
        "html": html,
    }

    try:
        response = requests.post(webhook_url, json=payload, timeout=120)

    except Exception as post_error:
        print(
            "❌ Row {} ({}): webhook POST itself failed: {}".format(
                row_number, abbrev_is, post_error
            )
        )
        return

    # VERSION 7: parse separately from the POST, so an unreadable body is
    # reported as exactly that. A real Row 34 run printed a "POST itself
    # failed" error here while the webhook had in fact scored and written
    # the value.
    response_body = read_webhook_json(
        response, "Row {} ({})".format(row_number, abbrev_is)
    )

    if response_body is None:
        print(
            "   The response could not be read, so it is unknown whether the"
            " webhook wrote the score -- check the sheet or Apps Script"
            " Executions before assuming it failed."
        )
        return

    if response_body.get("ok") and response_body.get("written"):
        print(
            "✅ Row {} ({}): scored {}".format(
                row_number,
                abbrev_is,
                response_body.get("insiderBuyingScore"),
            )
        )
        print_purchase_breakdown(response_body.get("purchaseDetails"))

    elif response_body.get("ok"):
        print(
            "⏩ Row {} ({}): webhook accepted but did not write ({})".format(
                row_number, abbrev_is, response_body.get("reason")
            )
        )
        print_purchase_breakdown(response_body.get("purchaseDetails"))

    else:
        print(
            "❌ Row {} ({}): webhook refused/failed ({})".format(
                row_number, abbrev_is, response_body.get("reason")
            )
        )


def post_alphaspread_to_webhook(webhook_url, row_number, abbrev_as, sheet_name, html):
    """
    VERSION 4 ADDITION (REQUESTED DIRECTLY, NEW WORK): posts this
    company's own scraped AlphaSpread HTML to the SAME Apps Script
    webhook URL already used for Insider Buying Score
    (fn_90_01_InsiderScoreWebhook_StockData_60) -- Apps Script Web Apps
    support only one doPost entry point per deployment, so rather than
    deploying and maintaining a second, separate Web App URL (and a
    second GitHub Actions secret to match), this reuses the existing
    deployed URL, and the payload's own new "target": "AS" field tells
    the webhook which of its two scoring paths to run. See that
    function's own matching VERSION 5 changelog entry for the receiving
    side of this.

    Deliberately a SEPARATE function from post_to_webhook, not a shared
    one with an if/else inside -- the two payload shapes, response
    shapes, and log messages are different enough (no purchaseDetails
    breakdown for AS, a plain vsUsualText field instead) that a shared
    function would need its own internal branching anyway, and this way
    each function's own docstring stays focused on the one path it
    actually handles.

    VERSION 7 CHANGE: returns True only when the webhook confirmed it
    actually wrote the value, and False for every other outcome (not
    written, refused/failed, unreadable response, POST failure), so
    run_bot can save page diagnostics whenever the value did not land.

    timeout=120, same reasoning as post_to_webhook's own matching
    parameter -- not yet confirmed necessary specifically for AS's own
    payload size (which is a single page's HTML, not a company's own
    full growing transaction history), but kept consistent since there
    is no real cost to doing so and it protects against the same class
    of large-page/slow-round-trip issue if AS's own page size ever grows.
    """
    payload = {
        "target": "AS",
        "sheetName": sheet_name,
        "rowNumber": row_number,
        "abbrevAS": abbrev_as,
        "html": html,
    }

    try:
        response = requests.post(webhook_url, json=payload, timeout=120)

    except Exception as post_error:
        print(
            "❌ Row {} ({}): AS webhook POST itself failed: {}".format(
                row_number, abbrev_as, post_error
            )
        )
        return False

    response_body = read_webhook_json(
        response, "Row {} ({}) AS".format(row_number, abbrev_as)
    )

    if response_body is None:
        print(
            "   The response could not be read, so it is unknown whether the"
            " webhook wrote the value -- check the sheet or Apps Script"
            " Executions before assuming it failed."
        )
        return False

    if response_body.get("ok") and response_body.get("written"):
        print(
            "✅ Row {} ({}): AS vs usual = \"{}\"".format(
                row_number,
                abbrev_as,
                response_body.get("vsUsualText"),
            )
        )
        return True

    if response_body.get("ok"):
        print(
            "⏩ Row {} ({}): AS webhook accepted but did not write ({})".format(
                row_number, abbrev_as, response_body.get("reason")
            )
        )
        return False

    print(
        "❌ Row {} ({}): AS webhook refused/failed ({})".format(
            row_number, abbrev_as, response_body.get("reason")
        )
    )
    return False


def run_bot():
    print("🤖 Booting up the row-refresh scraper (single-row mode)...")

    webhook_url = os.environ["GAS_WEBHOOK_URL"]
    row_number = int(os.environ["ROW_NUMBER"])
    sheet_name = os.environ["SHEET_NAME"]

    # VERSION 5 FIX (REQUESTED DIRECTLY, REAL CONFIRMED GAP): abbrev_is
    # is now ALSO read as an OPTIONAL environment variable (default '',
    # mirroring abbrev_as's own v4 treatment exactly), rather than a
    # required os.environ[...] lookup. Previously a row with a real,
    # resolved AlphaSpread abbreviation but NO InsiderScreener coverage
    # at all (a genuine, real possibility -- these are two independent
    # providers with independent company coverage) could never trigger
    # this workflow at all, since insider_score_scraper.yml's own
    # abbrev_is input was required: true and this line would raise a
    # KeyError the moment it was left blank. See
    # insider_score_scraper.yml's own matching VERSION 5 entry for the
    # input-declaration side of this same fix.
    abbrev_is = os.environ.get("ABBREV_IS", "").strip()

    # VERSION 4 ADDITION (REQUESTED DIRECTLY, NEW WORK): abbrev_as is
    # read as an OPTIONAL environment variable (default '', not a
    # required os.environ[...] lookup) -- not every real trigger of this
    # workflow will necessarily have a real, resolved abbrevAS available
    # for that row yet (or a caller not yet updated to pass it at all),
    # and this must never turn what used to be a working Insider Buying
    # Score run into a hard failure just because the newer, optional AS
    # piece was not supplied. See insider_score_scraper.yml's own
    # matching VERSION 4 entry for this same input declared optional
    # there too.
    abbrev_as = os.environ.get("ABBREV_AS", "").strip()

    print(
        "🎯 Sheet={} | Row={} | IS={} | AS={}".format(
            sheet_name, row_number, abbrev_is or "(none)", abbrev_as or "(none)"
        )
    )

    if not abbrev_is and not abbrev_as:
        print(
            "⏩ Row {}: neither abbrev_is nor abbrev_as was provided --"
            " nothing to scrape this run.".format(row_number)
        )
        return

    with SB(uc=True, headless=True) as sb:
        # ------------------------------------------------------------------
        # Insider Buying Score -- only attempted when a real abbrev_is was
        # actually provided (VERSION 5: this check itself is new; the
        # scrape/post call inside was already wrapped in its own
        # try/except from v4, so a failure here still cannot block the AS
        # scrape below).
        # ------------------------------------------------------------------
        if abbrev_is:
            try:
                html = scrape_company_html(sb, abbrev_is)
                post_to_webhook(webhook_url, row_number, abbrev_is, sheet_name, html)

            except Exception as scrape_error:
                print(
                    "❌ Row {} ({}): IS scrape itself failed: {}".format(
                        row_number, abbrev_is, scrape_error
                    )
                )
        else:
            print(
                "⏩ Row {}: no abbrev_is provided -- skipping Insider Buying"
                " Score scrape this run.".format(row_number)
            )

        # ------------------------------------------------------------------
        # VERSION 4 ADDITION (REQUESTED DIRECTLY, NEW WORK): AlphaSpread
        # "valuation history" scrape, reusing this SAME already-running
        # browser session -- only attempted when a real abbrev_as was
        # actually provided. A separate, independent try/except, so an
        # IS-side failure above (or an AS-side failure here) can never
        # block the other from still being attempted and posted.
        #
        # VERSION 6: on failure, also records real page diagnostics (see
        # save_alphaspread_diagnostics) before moving on. That call is
        # itself fully guarded, so it can never turn an AS failure into
        # a bigger one.
        # ------------------------------------------------------------------
        if abbrev_as:
            diagnostics_reason = None

            try:
                as_html = scrape_alphaspread_html(sb, abbrev_as)
                as_written = post_alphaspread_to_webhook(
                    webhook_url, row_number, abbrev_as, sheet_name, as_html
                )

                if not as_written:
                    diagnostics_reason = (
                        "scrape succeeded but the webhook did not write"
                    )

            except Exception as as_scrape_error:
                print(
                    "❌ Row {} ({}): AS scrape itself failed: {}".format(
                        row_number, abbrev_as, as_scrape_error
                    )
                )
                diagnostics_reason = "AS scrape itself failed"

            # VERSION 7: diagnostics are now saved for BOTH situations --
            # a scrape that threw (v6) and a scrape that worked but whose
            # value the webhook did not write (e.g. VALUE_NULL).
            if diagnostics_reason:
                try:
                    save_alphaspread_diagnostics(
                        sb, row_number, abbrev_as, diagnostics_reason
                    )
                except Exception as diagnostics_error:
                    print(
                        "⚠️ AS diagnostics themselves failed: {}".format(
                            diagnostics_error
                        )
                    )

    print("🧹 Task complete!")


if __name__ == "__main__":
    run_bot()
