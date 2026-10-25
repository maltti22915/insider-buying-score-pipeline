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
VERSION 23
  v73: AS Hist: 'less than 1% of days' is understood (NVDA / PM failed with 'sentence not understood'), the 'More details' window too; a loose sentence fallback ('this cheap or cheaper on N% of days'); the summary page is opened again when the browser stayed on another page (EVO / NVDA); a failed read logs diag= with the page text about 'usual' / 'history' / 'of days'.
  v72: FIX of v61: AlphaSpread URL path of an abbreviation with a space uses %20 (sto/lifco%20b), not '-' (sto/lifco-b and sto/atco-a give 404 pages in the logs); as_dcf_extractor v8 does the same. The abbreviation search (Column D) was right all along.
  v71: an abbrevAS written with %20 (sto/lifco%20b) is used as it is in every AlphaSpread URL (no space to replace) and the Buybacks ticker is decoded (LIFCO B).
  v70: the widget fallback (current buyback yield when the table row is locked) waits for the lazy render: up to 3 reads with scroll / wait / reload, and the FAIL line logs diag= with the page text around 'Buyback' (v69 read it once, without waiting, and failed for ORCL).
  v69: FIX v68 read the NEXT company's row when the stock's own cells were hidden (BILI got Alphabet's -1.04/1.88/2.05/1.2): the four cells must now follow the ticker directly, 'Unlock' = missing; ORCL's own row is 'Unlock' for visitors, so the current yield is then taken from the 'Buyback Yield -6.44%' widget (investor-returns/i/buybacks), 3Y / 5Y / 10Y stay missing (Shr chg = now alone, Shr \u0394 '-').
  v68: Buybacks table: NO first-row fallback (v67 read a peer row for ORCL: now -1.04 instead of -6.44); the stock's row is found by ticker only, values are the first 4 value tokens after the ticker; when the row is not found the step logs diag= (table text) so the layout can be checked.
  v67: SHARE COUNT spec 2026-10-24: buyback read ONLY from the Buybacks table of .../dividends#buybacks (columns Company | Buyback Yield | Average Yield 3Y | 5Y | 10Y), row of the stock by ticker (first row if the ticker is not found); values now / y3 / y5 / y10, a dash cell = missing, a real 0.00% is a number; the summary widget and dividend block are not read any more; posted as bb {cur, y3, y5, y10, avg5=y5}.
  v66: PARTIAL Quality Model refresh (env QM_ONLY = workflow input qm_only, e.g. 'Shr chg' or 'ROIC,Moat'): the stage groups statement pages / analyst estimates / buyback run only when one of their inputs is missing; a buyback-only run opens no extra page; the payload is posted with partial=True and the sheet keeps all stored values it does not carry (fn_91_11 v7).
  v65: buyback also readable from the summary-page 'Investor Returns' widget ('Buyback Yield -6.44%', next to 'Dividend Yield 1.62%' which v62 had taken as the buyback for ORCL); no 5Y average there (avg5 stays empty).
  v64: Quality Model completion pass also starts when the main pass produced NO Quality Model payload at all (ORCL 2026-10-23: hist blocked, quality/qm steps did not run, Row JSON stayed without QM data); a 'stages after the DCF' log line shows which stages run.
  v63: AlphaSpread buyback is read from .../investor-returns/i/buybacks (fallback: old dividends page) and ONLY from the 'Buyback Yield' block - the dividend block's Current/Average Yield is never taken (fixes dividend payers CSU/NKE/UNH/JPM/META/PM showing dividend yield as Shr chg).
  v62: a DCF page that is still the Cloudflare page ends the attempt at once (as_dcf_extractor v7 AsDcfCloudflare -> CloudflareBlocked, no ratio/quality pages, no 45 s wait); pause before an ASDCF relaunch 15-30 s (was 30-60 s).
  v61: AlphaSpread URLs use '-' instead of spaces in the path (sto/atco a -> sto/atco-a); as_qm_data v1.16 / as_ttm_metrics v1.7: capex and operating-cash-flow of the previous year + OCF margins (CAPEX_SURGE), Wall St widget value 0 = missing.
  v40: Simply Wall St gives only the SW Price value and the SW JSON: the future / dividend pages (target SWP) are no longer opened (env SW_SUBPAGES=future,dividend brings them back).
  v60: Cloudflare fast stop: after a failed DCF the first blocked page ends the AlphaSpread session at once (pages are tried once, no 12/24/36 s waits; the remaining ratio pages are skipped) so run_bot retries with a fresh browser inside its time budget (NOW 2026-10-22 took 1030 s, all blocked).
  v59: the old Quality v4 post (target ASQ) is no longer sent: the sheet has no such columns and refused it on every run (NO_QUALITY_COLUMNS). Env AS_POST_QUALITY_V4=1 brings it back.
  v58: Earn LT (long-term operating-income CAGR, fallback net income: est.earn_lt, earn_lt_years, earn_lt_basis) and Earn g (TTM operating income growth: ttm.earn_g) in the Quality Model payload (as_qm_data v1.15, as_ttm_metrics v1.6).
  v57: stricter COMPOUNDER gates: Net Income long-term CAGR (analyst-estimates page) and 10Y price change (summary page) stored in the Quality Model payload (as_qm_data v1.14).
  v56: AlphaSpread insider block no longer read (all insider data comes from InsiderScreener); as_qm_data v1.13.
  v55: Quality Model spec 2026-10-21: insider bought/sold USD (0-12 months) read on the summary visit (as_qm_data v1.11 read_insider -> qm.ins); capex/OCF/SG&A TTM levels (as_ttm_metrics v1.5 -> qm.ttm); buyback block with only zeros is retried and never stored as 0 (_bb_ready).
  v54: completion pass: when the Quality Model payload still lacks inputs the missing parts are read again in a fresh browser (up to AS_QM_FILL_PASSES=2) and posted again; as_qm_data v1.9 qm_missing().
  v53: qm.fin = True for financials (profile FIN of the quality step); Apps Script then skips ND/EBITDA scoring and its exclusion.
  v52: margins missing on the AlphaSpread page are computed from the statements (as_quality_metrics v6 details['margins'], as_qm_data v1.8); metrics neither source can give are listed in qm.na so Apps Script does not re-scrape for them.
  v51: ROIC missing on the AlphaSpread page (UNH has no ROIC card) -> the yearly ROIC computed from the statements (Quality step) is used for the Quality Model (as_qm_data v1.7, step qm_roic_computed).
  v50: the Wall St widget counts as read only when it has values (else the Quality Model step reads summary again); solvency retry; qm_prof diagnostics; version index printed at run start and in RUN_SUMMARY ("versions"), every module has VERSION.
  v49: each AlphaSpread URL is opened once per stock: the Wall St Estimates widget is read during the summary visit of fetch_as_hist (as_qm_data.read_wall_st); as_qm_data opens summary only when that visit did not happen or was blocked.
  v48: Quality Model (QL / Dir / Outl / Q) replaces Quality v2: new step fetch_as_qm (as_qm_data.py) reads the analyst-estimates and solvency pages and bundles them with the profitability checklist, buyback, moat and TTM block already read; posted as target ASQM (fn_91_12) into "QM JSON". The 10-year statement scrape (fetch_as_fin / as_fin_data) is retired. Env AS_FIN="0" still skips it.
  v47: Quality v2 -- new step fetch_as_fin (as_fin_data.py): annual income statement / balance sheet / cash flow (unit selector set to Millions), solvency, moat and 3Y ROIC pages become the "AS Fin JSON" posted as target ASFIN (fn_91_11). Env AS_FIN="0" skips it (the sheet keeps a JSON younger than 30 days).
  v46: AlphaSpread run blocked by Cloudflare (DCF failed + 2 blocked pages): stops at once and is retried with a fresh browser after 30-60 s (up to 3 attempts, budget 800 s); the scores step no longer waits 20 s on a challenge page.
  v45: AS Profitability / Solvency cards: scrolls the card heading into view and reloads the page once when no score shows (AMZN had empty cards).
  v45: Trend fix: the AlphaSpread TTM view click retries 3 x 12 s; "Now" is computed from the income TTM alone when the cash-flow TTM is missing (only the FCF-margin signal is dropped).
  v44: a Cloudflare block (or any error) inside the SB context manager is no longer swallowed: it is re-raised after the browser closes, so the run counts it as "blocked" (and retries) instead of 'cannot access local variable posted'.
  v44: the AlphaSpread buyback read retries up to 3 more times (scroll to the buybacks block, wait, re-read; the last try reloads the page) before it reports FAIL 'no buyback numbers on the page'.
  v43: SW run also reads the SW Management + Ownership pages after the valuation dialog and posts the "Skin" score + note (target SKIN, handler fn_91_10; scoring in sw_skin.py; env SW_SKIN=0 switches it off).
  v42: Simply Wall St now runs on SeleniumBase CDP mode (CdpSB adapter, sb.cdp.solve_captcha): sw_probe v2 passed 12 of 12 for CDP against 2 of 6 for the old uc engine (hour 12 UTC, normally the worst). SW_ENGINE=uc switches back.
  v41: the 'View All' details read is OFF by default (AS_SCORE_DETAILS=1 turns it on): the live runs showed that AlphaSpread hides the score and checks on /profitability and /solvency for the logged-out bot ('score is Hidden', fewer than 3 checks), and each try cost 20-40 s per row.
  v39: after AS Hist the scraper opens the AlphaSpread Profitability and Solvency analysis pages, clicks 'View All' and reads ALL due-diligence checks (name, value such as '90% > 91%', green/yellow/red status) into ratios.scores.<kind>.checks; the cell notes then list every check. AS_SCORE_DETAILS=0 disables. A failure keeps the 4 reasons from the summary card.
  v38: the score's font colour is read from the deepest element whose whole text is 'NN' or 'NN / 100' (v37 log: scores OK but profitColor/solvColor empty because the number is not a leaf element).
  v37: score cards are read from the card's visible text lines (title, reasons, 'NN' or 'NN / 100', 'View ... Analysis') instead of one element per number; the FAIL step prints the first lines it saw. v36 log: both headings were in the page text but no number was found.
  v36: the font colour AlphaSpread itself uses for the score number (computed style of the '99' / '80') is read too (card.color, '#rrggbb') so the sheet can show the score in the same colour.
  v35: AlphaSpread 'Profitability Score' and 'Solvency Score' cards (0-100 plus the tick-mark reasons, e.g. 'Exceptional 3Y Average ROIC') are read from the same summary page visit as AS Hist and sent in the ASRP payload as ratios.scores = {profit, solv}. Columns 'AS Profit' / 'AS Solv' (fn_91_07 v6, fn_24_69). AS_SCORES=0 disables.
  v34: SW gives up on a Cloudflare challenge after SW_CF_WAIT_SECONDS (default 15, env override) instead of 25. Log analysis of 240 SW attempts: every challenge that cleared did so within 7-11 s; the others never cleared, so the extra 10 s only delayed the next retry. Other providers still use CF_CHALLENGE_WAIT_SECONDS (25).
  v26: one final row recalculation per parallel run instead of four (handlers get skipRecalc; the parent sends ASRP recalcOnly last). SINGLE_RECALC=0 restores the old behaviour.
  v25: MarketScreener 'Access Denied' (Akamai block of the runner address) is no longer final: home-page warm-up, then Scrape.do fallback (steps ms_warmup / ms_scrapedo); SW retries capped at SW_MAX_ATTEMPTS (3; blocks come in clusters per runner address, later tries rarely pass).
  v24: GuruFocus off by default (GF_ENABLED=1); providers run in parallel child processes (PARALLEL=0 = old sequential run), webhook posts serialised by a file lock. v23: the quality_v4 step prints the scorer version (scorer=v5.0). Q v4 + Moat: fetch_as_quality also opens the AlphaSpread Economic Moat page, computes Q v4 (as_quality_v4.py) and the moat
  rating (as_moat.py) and sends them in the ASQ payload as quality.v4 / quality.moat; the Now block is computed with the Q v4
  profile (financials skip FCF and gross margin). Needs as_quality_v4.py, as_moat.py, as_ttm_metrics.py in the repo root.
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

import html
import fcntl
import sys
import threading
import tempfile
import subprocess
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

# v34: SW only -- every challenge that cleared in the logs did so within 7-11 s.
try:
    SW_CF_WAIT_SECONDS = int(os.environ.get("SW_CF_WAIT_SECONDS", "15"))
except ValueError:
    SW_CF_WAIT_SECONDS = 15

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
ABBREV_KEY_BY_TARGET = {"ASDCF": "abbrevAS", "ASRP": "abbrevAS", "ASQ": "abbrevAS", "ASFIN": "abbrevAS", "ASQM": "abbrevAS", "SWP": "abbrevSW", "SKIN": "abbrevSW", "GFP": "abbrevGF"}

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


# ----------------------------------------------------------------------------
# v42: SeleniumBase CDP mode for Simply Wall St (sw_probe v2 result: CDP + solve_captcha passed 12 of 12 at 12:51 UTC, the
# webdriver "uc" baseline 2 of 6, headless uc 0 of 6). CdpSB gives the CDP browser the few sb.* methods the SW code uses,
# so the proven SW dialog code stays unchanged. Env SW_ENGINE=uc switches back to the old webdriver engine.
# ----------------------------------------------------------------------------
SW_ENGINE = os.environ.get("SW_ENGINE", "cdp").strip().lower()


class CdpSB(object):
    """Thin adapter: the sb.* calls of the SW scraper on top of sb.cdp (pure CDP, no webdriver)."""

    def __init__(self, sb):
        self.sb = sb
        self.opened = False

    def uc_open_with_reconnect(self, url, reconnect_time=None):
        if not self.opened:
            self.sb.activate_cdp_mode(url)
            self.opened = True
        else:
            self.sb.cdp.open(url)

    def sleep(self, seconds):
        time.sleep(seconds)

    def execute_script(self, script):
        return self.sb.cdp.evaluate(script)

    def get_page_source(self):
        return self.sb.cdp.get_page_source()

    def get_title(self):
        return self.sb.cdp.get_title()

    def get_current_url(self):
        return self.sb.cdp.get_current_url()

    def uc_gui_click_captcha(self):
        self.sb.cdp.solve_captcha()

    def click(self, selector, timeout=None):
        self.sb.cdp.click(selector)

    def set_window_size(self, width, height):
        try:
            self.sb.cdp.set_window_size(width, height)
        except Exception:
            pass

    def send_keys(self, selector, text):
        try:
            self.sb.cdp.press_keys(selector, text)
        except Exception:
            pass

    def save_screenshot(self, name, folder=None):
        try:
            return self.sb.cdp.save_screenshot(name, folder)
        except Exception:
            return None


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
                      "t0": time.monotonic(), "n": 0, "last": "", "blocked": 0})


def step(name, status="OK", **details):
    """Prints one numbered STEP line. Never raises."""
    try:
        _STEP_CTX["n"] += 1
        _STEP_CTX["last"] = name
        if status == "FAIL" and details.get("reason") == "blocked":   # v46: counted so that a blocked AlphaSpread run stops early and is retried
            _STEP_CTX["blocked"] = _STEP_CTX.get("blocked", 0) + 1
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


def wait_past_challenge(sb, headless, wait_seconds=None):
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

    limit = CF_CHALLENGE_WAIT_SECONDS if wait_seconds is None else wait_seconds
    while time.monotonic() - started < limit:
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



# ----------------------------------------------------------------------------
# v13: Simply Wall St future / dividend / valuation pages (replace Scrape.do)
# ----------------------------------------------------------------------------
_SW_PAGES = {}
_SW_SKIN = {}
SW_SKIN_ENABLED = os.environ.get("SW_SKIN", "1") != "0"
SW_SKIN_SECTIONS = ("Leadership Team", "Board Members", "Ownership Breakdown", "Recent Insider Transactions")
SW_PAGE_MIN_CHARS = 20000
# v40: Simply Wall St brings only the valuation dialog (SW Price value + SW JSON). The future / dividend pages are
# opened only when the env SW_SUBPAGES lists them (e.g. "future,dividend"); default = none.
SW_SUBPAGES = tuple(x.strip() for x in os.environ.get("SW_SUBPAGES", "").split(",") if x.strip())


def slim_html(html):
    """Drops script/style/noscript/svg blocks: the Apps Script parser only reads the text."""
    html = re.sub(r"<script\b[^>]*>.*?</script>", " ", html or "", flags=re.S | re.I)
    html = re.sub(r"<style\b[^>]*>.*?</style>", " ", html, flags=re.S | re.I)
    html = re.sub(r"<noscript\b[^>]*>.*?</noscript>", " ", html, flags=re.S | re.I)
    html = re.sub(r"<svg\b[^>]*>.*?</svg>", " ", html, flags=re.S | re.I)
    return html


def fetch_sw_subpage(sb, abbrev_sw, name, headless):
    """Opens https://simplywall.st/stocks/<abbrev>/<name> and returns its slimmed HTML ('' on failure)."""
    url = "https://simplywall.st/stocks/{}/{}".format(abbrev_sw, name)
    try:
        print("🌐 Navigating to: {}".format(url))
        sb.uc_open_with_reconnect(url, reconnect_time=CF_RECONNECT_SECONDS)
        sb.sleep(PAGE_SETTLE_SECONDS)
        if not wait_past_challenge(sb, headless, SW_CF_WAIT_SECONDS):
            step("page_" + name, "FAIL", reason="challenge page still showing")
            return ""
        sb.sleep(2)
        html = slim_html(sb.get_page_source() or "")
        ok = len(html) >= SW_PAGE_MIN_CHARS
        step("page_" + name, "OK" if ok else "FAIL", chars=len(html))
        return html if ok else ""
    except Exception as page_error:
        print("⚠️ SW {} page failed: {}".format(name, page_error))
        step("page_" + name, "FAIL", reason=str(page_error).replace("\n", " ")[:80])
        return ""


SKIN_LINES_JS = (
    "var r = document.querySelector('main') || document.body;"
    "return String(r.innerText || '').split('\\n').map(function(x){return x.replace(/\\s+/g,' ').trim();}).filter(Boolean);"
)
SKIN_SCROLL_TO_JS = (
    "var label = %s; var els = [].slice.call(document.querySelectorAll('h1,h2,h3,h4,h5,div,span,p'));"
    "for (var i = 0; i < els.length; i++) { var e = els[i]; if (e.children.length > 2) { continue; }"
    " var tx = (e.innerText || '').replace(/\\s+/g,' ').trim();"
    " if (tx === label) { e.scrollIntoView({block:'center'}); return 'ok'; } } return 'notfound';"
)


def fetch_sw_skin_lines(sb, abbrev_sw, page, headless):
    """v43: opens the SW management / ownership page, scrolls its lazy sections in and returns the page text lines."""
    url = "https://simplywall.st/stocks/{}/{}".format(abbrev_sw, page)
    sb.uc_open_with_reconnect(url, reconnect_time=CF_RECONNECT_SECONDS)
    sb.sleep(PAGE_SETTLE_SECONDS)
    if not wait_past_challenge(sb, headless, SW_CF_WAIT_SECONDS):
        raise RuntimeError("skin: {} page still a challenge".format(page))
    sb.sleep(2)
    height = int(run_js(sb, "return document.body.scrollHeight;") or 6000)
    y = 0
    while y < height + 600 and y < 20000:
        run_js(sb, "window.scrollTo(0, {}); return 1;".format(y))
        time.sleep(0.8)
        y += 350
        height = max(height, int(run_js(sb, "return document.body.scrollHeight;") or height))
    for label in SW_SKIN_SECTIONS:
        run_js(sb, SKIN_SCROLL_TO_JS % json.dumps(label))
        for _ in range(6):
            time.sleep(1.2)
            cur = run_js(sb, SKIN_LINES_JS) or []
            if not any(str(l).startswith("Loading") for l in cur):
                break
    return run_js(sb, SKIN_LINES_JS) or []


def fetch_sw_skin(sb, abbrev_sw, headless):
    """v43: Management + Ownership pages -> Skin score dict (sw_skin.score_page_lines). Never raises."""
    _SW_SKIN.clear()
    if not SW_SKIN_ENABLED:
        return
    try:
        import sw_skin
        mgmt = fetch_sw_skin_lines(sb, abbrev_sw, "management", headless)
        own = fetch_sw_skin_lines(sb, abbrev_sw, "ownership", headless)
        res = sw_skin.score_page_lines(abbrev_sw, mgmt, own)
        _SW_SKIN.update(res)
        step("skin", "OK", score=res["score"], lines="{}/{}".format(len(mgmt), len(own)))
    except Exception as skin_error:
        print("⚠️ SW skin failed: {}".format(skin_error))
        step("skin", "FAIL", reason=str(skin_error).replace("\n", " ")[:80])


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

    if not wait_past_challenge(sb, headless, SW_CF_WAIT_SECONDS):
        step("cloudflare_check", "FAIL", reason="challenge page still showing")
        log_sw_page_state(sb)
        save_sw_diagnostics(sb, row_number, None, "blocked by Cloudflare")
        raise CloudflareBlocked(
            "page is still a Cloudflare challenge after {}s ({} browser)".format(
                SW_CF_WAIT_SECONDS, "headless" if headless else "headed"
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

    # v13: the three pages the Apps Script SW parser reads. The valuation page is the one open
    # right now (taken before any dialog is opened); future and dividend are opened afterwards
    # and the valuation page is then opened again for the "Data" dialog.
    _SW_PAGES.clear()
    valuation_html = slim_html(sb.get_page_source() or "")
    if len(valuation_html) >= SW_PAGE_MIN_CHARS:
        _SW_PAGES["valuation"] = valuation_html
    step("page_valuation", "OK" if "valuation" in _SW_PAGES else "FAIL", chars=len(valuation_html))
    def fetch_sw_subpages_now():
        # v14: future and dividend are opened AFTER the dialog attempt (success or failure), so
        # the valuation page is never reloaded before the "Data" dialog (a reload once lost the buttons).
        for sub_name in SW_SUBPAGES:
            sub_html = fetch_sw_subpage(sb, abbrev_sw, sub_name, headless)
            if sub_html:
                _SW_PAGES[sub_name] = sub_html

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
        fetch_sw_subpages_now()
        raise RuntimeError(
            "no 'Share Price vs. Fair Value' dialog opened after trying"
            " {} 'Data' button(s)".format(min(button_count, SW_MAX_DATA_BUTTONS_TO_TRY))
        )

    if SAVE_DIAGNOSTICS_ALWAYS:
        save_sw_diagnostics(sb, row_number, dialog.get("html"), "always-on")

    fetch_sw_subpages_now()
    fetch_sw_skin(sb, abbrev_sw, headless)  # v43

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


def fetch_ms_via_scrapedo(url):
    """v25: MarketScreener fallback when the runner's browser gets Akamai 'Access Denied'. Returns the page HTML, or '' on failure / no token."""
    token = (os.environ.get("SCRAPE_DO_TOKEN") or os.environ.get("SCRAPEDO_TOKEN") or "").strip()
    if not token:
        print("ℹ️ MS: no SCRAPE_DO_TOKEN in the environment -- Scrape.do route skipped.")
        return ""
    from urllib.parse import quote_plus
    for extra in ("&render=true", "&render=true&super=true"):
        try:
            response = requests.get("https://api.scrape.do?token={}&url={}{}".format(token, quote_plus(url), extra), timeout=120)
            if response.status_code == 200 and len(response.text) >= MS_MIN_HTML_CHARS and any(m in response.text for m in ("Last Close", "Consensus", "Capitalization")):
                return response.text
            print("ℹ️ MS Scrape.do ({}): http {} / {} chars -- not usable.".format(extra, response.status_code, len(response.text)))
        except Exception as request_error:
            print("ℹ️ MS Scrape.do ({}): {}".format(extra, type(request_error).__name__))
    return ""


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

    def ms_page_ok(page_html):
        return len(page_html) >= MS_MIN_HTML_CHARS and any(m in page_html for m in ("Last Close", "Consensus", "Capitalization"))

    html = sb.get_page_source() or ""
    title = sb.get_title() or ""
    if not ms_page_ok(html):
        step("read_page", "FAIL", chars=len(html), title=title[:60])
        # v25: "Access Denied" (reference #18.xxx, errors.edgesuite.net) is an Akamai block of the runner's address, not a Cloudflare challenge.
        # 1) warm-up: open the home page first (Akamai sets its cookies there), then the quote page again.
        # 2) if still denied: fetch the quote page through Scrape.do (residential address, only used on this failure).
        try:
            sb.uc_open_with_reconnect("https://www.marketscreener.com/", reconnect_time=CF_RECONNECT_SECONDS)
            sb.sleep(3)
            sb.uc_open_with_reconnect(url, reconnect_time=CF_RECONNECT_SECONDS)
            sb.sleep(PAGE_SETTLE_SECONDS)
            html = sb.get_page_source() or ""
            title = sb.get_title() or ""
            step("ms_warmup", "OK" if ms_page_ok(html) else "FAIL", chars=len(html), title=title[:60])
        except Exception as warm_error:
            step("ms_warmup", "FAIL", reason=type(warm_error).__name__)
    if not ms_page_ok(html):
        via_html = fetch_ms_via_scrapedo(url)
        if via_html:
            html, title = via_html, "MarketScreener (via Scrape.do)"
            step("ms_scrapedo", "OK", chars=len(html))
        else:
            step("ms_scrapedo", "FAIL", reason="no token, or the page was incomplete")
    if not ms_page_ok(html):
        step("read_page", "FAIL", chars=len(html), title=title[:60])
        failure_report(sb, "read_page", "page too small or without price/consensus blocks ({} chars)".format(len(html)),
                       looking_for="Last Close|Consensus|Capitalization")
        raise RuntimeError("MarketScreener page looks incomplete ({} chars, title {!r})".format(len(html), title[:60]))
    step("read_page", "OK", chars=len(html), title=title[:60])
    return {"html": html, "url": url, "title": title, "htmlChars": len(html)}


# ----------------------------------------------------------------------------
# v14: GuruFocus term pages (replace Scrape.do) -- posted as target "GFP"
# ----------------------------------------------------------------------------
GF_PAGES = (
    ("pe", "term/pettm/"),
    ("peForward", "term/forward-pe-ratio/"),
    ("buyback", "term/buyback-yield/"),
    ("roce", "term/ROCE/"),
    ("roe", "term/ROE/"),
    ("pfcf", "term/price-to-free-cash-flow/"),
    ("pocf", "term/price-to-operating-cash-flow/"),
    ("gfValue", "term/gf_value/"),
    ("gfScore", "term/gf_score/"),
    ("netMargin", "term/netmargin/"),
    ("revenue", "term/Revenue/"),
    ("moat", "term/moat-score/"),
)
GF_PAGE_MIN_CHARS = 1500
GF_MAX_ATTEMPTS = int(os.environ.get("GF_MAX_ATTEMPTS", "2"))  # v15
# v24: GuruFocus is switched off by default (GF_ENABLED=1 turns it back on). The AlphaSpread ratio pages already give P/E, P/OCF, P/FCF.
GF_ENABLED = os.environ.get("GF_ENABLED", "0").strip() == "1"
# v24: providers run in parallel, one browser process each (PARALLEL=0 restores the old one-after-the-other run).
PARALLEL_PROVIDERS = os.environ.get("PARALLEL", "1").strip() != "0"
# v26: in a parallel run the four recalculating handlers (MS, SW, SWP, ASRP) each re-did the whole row calculation (20-25 s apiece, under the
# sheet lock). Now they only write their cells (payload skipRecalc) and ONE recalculation (target ASRP, recalcOnly) runs after all providers finished.
# Needs the AlphaSpread abbreviation (the recalc request goes through the ASRP handler) and Apps Script fn_91_01 v5, fn_91_04 v6, fn_91_05 v2, fn_91_07 v2.
SINGLE_RECALC = os.environ.get("SINGLE_RECALC", "1").strip() != "0"
_POST_FLAGS = {}   # extra payload keys for every post of this process (set in child processes / for the final recalc)
PARALLEL_START_GAP_SECONDS = float(os.environ.get("PARALLEL_START_GAP", "8"))   # staggered browser starts (undetected-chromedriver patches a shared driver file)
POST_LOCK_PATH = os.path.join(tempfile.gettempdir(), "provider_json_post.lock")


def text_only_page(html):
    """Title + visible text only (the Apps Script GF parser reads nothing else); keeps the post small."""
    html = html or ""
    title_match = re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.S | re.I)
    title = title_match.group(1).strip() if title_match else ""
    body = slim_html(html)
    body = re.sub(r"<title[^>]*>.*?</title>", " ", body, flags=re.S | re.I)
    body = re.sub(r"<[^>]+>", " ", body)
    body = re.sub(r"\s+", " ", body).strip()
    return "<html><head><title>{}</title></head><body>{}</body></html>".format(title, body)


def fetch_gf_pages_via_scrapedo(abbrev_gf):
    """
    v16: GuruFocus sits behind a Cloudflare check that blocks GitHub's browser, but the project's
    other GitHub scraper reads GuruFocus through Scrape.do (render=true) with the token in the
    repository secret. Same here: one request per term page, in parallel (max 4 at a time).
    Returns {subpage: text_only_html}; empty when no token is set or everything failed.
    """
    token = (os.environ.get("SCRAPE_DO_TOKEN") or os.environ.get("SCRAPEDO_TOKEN") or "").strip()
    if not token:
        print("ℹ️ GF: no SCRAPE_DO_TOKEN in the environment -- Scrape.do route skipped.")
        return {}

    from concurrent.futures import ThreadPoolExecutor
    from urllib.parse import quote_plus

    def one(item):
        name, path = item
        target = "https://www.gurufocus.com/{}{}".format(path, abbrev_gf)
        api = "https://api.scrape.do?token={}&url={}&render=true".format(token, quote_plus(target))
        for attempt in (1, 2):
            try:
                response = requests.get(api, timeout=90)
                if response.status_code == 200 and len(response.text) > 5000:
                    page = text_only_page(response.text)
                    if len(page) >= GF_PAGE_MIN_CHARS:
                        return name, page, "ok", len(page)
                    return name, "", "too_small", len(page)
                status = "http{}".format(response.status_code)
            except Exception as request_error:
                status = type(request_error).__name__
            time.sleep(3 * attempt)
        return name, "", status, 0

    pages = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        for name, page, status, chars in pool.map(one, GF_PAGES):
            step("page_" + name, "OK" if page else "FAIL", via="scrape.do", result=status, chars=chars)
            if page:
                pages[name] = page
    return pages


def scrape_gf_data(sb, abbrev_gf, row_number, headless=True):
    """
    v14: opens each GuruFocus term page for abbrev_gf in the same browser session and returns
    {"pages": {subpage: html}}. Parsing happens in Apps Script (fn_22_30, target GF).
    A Cloudflare block on the FIRST page raises CloudflareBlocked (retried by run_bot);
    a later page that fails is just left out.
    """
    pages = fetch_gf_pages_via_scrapedo(abbrev_gf)
    if len(pages) >= 6:
        print("📄 GF pages via Scrape.do: {}".format(", ".join(sorted(pages.keys()))))
        return {"pages": pages}
    if pages:
        print("⚠️ GF: only {} page(s) via Scrape.do -- the browser tries the rest.".format(len(pages)))

    for index, (name, path) in enumerate(GF_PAGES):
        if name in pages:
            continue
        url = "https://www.gurufocus.com/{}{}".format(path, abbrev_gf)
        print("🌐 Navigating to: {}".format(url))
        try:
            sb.uc_open_with_reconnect(url, reconnect_time=CF_RECONNECT_SECONDS)
            sb.sleep(PAGE_SETTLE_SECONDS)
            cleared = wait_past_challenge(sb, headless)
            if not cleared and not headless:
                # v15: GuruFocus' Cloudflare check is stricter than Simply Wall St's: try SeleniumBase's
                # newer Turnstile handler (when this version has it) before giving up.
                for handler_name in ("uc_gui_handle_captcha", "uc_gui_handle_cf"):
                    handler = getattr(sb, handler_name, None)
                    if handler is None:
                        continue
                    try:
                        print("🖱️ GF: trying sb.{}()".format(handler_name))
                        handler()
                        sb.sleep(4)
                        if not is_challenge_page(sb):
                            cleared = True
                            break
                    except Exception as handler_error:
                        print("⚠️ sb.{} failed: {}".format(handler_name, handler_error))
            if not cleared:
                step("page_" + name, "FAIL", reason="challenge page still showing")
                if index == 0:
                    raise CloudflareBlocked("GuruFocus page is still a challenge ({} browser)".format(
                        "headless" if headless else "headed"))
                continue
            sb.sleep(2)
            html = text_only_page(sb.get_page_source() or "")
            ok = len(html) >= GF_PAGE_MIN_CHARS
            step("page_" + name, "OK" if ok else "FAIL", chars=len(html))
            if ok:
                pages[name] = html
        except CloudflareBlocked:
            raise
        except Exception as page_error:
            print("⚠️ GF {} page failed: {}".format(name, page_error))
            step("page_" + name, "FAIL", reason=str(page_error).replace("\n", " ")[:80])
    if not pages:
        raise RuntimeError("no GuruFocus page could be read")
    print("📄 GF pages collected: {}".format(", ".join(sorted(pages.keys()))))
    return {"pages": pages}


# ----------------------------------------------------------------------------
# v17: AlphaSpread ratio pages (P/E, P/OCF, P/FCFE) read in the SAME browser as the DCF
# ----------------------------------------------------------------------------
_AS_RATIOS = {}
AS_RATIO_PAGES = (("pe", "price-to-earnings"), ("pocf", "price-to-ocf"), ("pfcf", "price-to-fcfe"))


def _as_strip_text(page_source):
    page_source = re.sub(r"(?is)<(script|style|noscript).*?</\1>", " ", page_source)
    page_source = re.sub(r"(?s)<[^>]+>", " ", page_source)
    return re.sub(r"\s+", " ", html.unescape(page_source)).strip()


def _as_num(text):
    found = re.search(r"-?\d[\d,]*\.?\d*", text or "")
    return float(found.group(0).replace(",", "")) if found else None


_FAST_BLOCK = {"on": False}   # v60: set after a failed DCF: one quick try per page, no long Cloudflare waits


def _as_open_cf(sb, url, reconnect=4, attempts=3):
    """v48: opens an AlphaSpread page; when Cloudflare shows ("Just a moment") it waits, clicks the verification box and opens the page
    again (up to `attempts` times). Returns True when the page is not a Cloudflare page. Never raises."""
    if _FAST_BLOCK.get("on"):
        attempts = 1   # v60
    for attempt in range(1, attempts + 1):
        try:
            sb.uc_open_with_reconnect(url, reconnect)
            if "just a moment" not in (sb.get_title() or "").lower():
                return True
            sb.sleep(3 if _FAST_BLOCK.get("on") else 12 * attempt)
            try:
                sb.uc_gui_click_captcha()
                sb.sleep(4.0)
            except Exception:
                pass
            if "just a moment" not in (sb.get_title() or "").lower():
                return True
        except Exception:
            sb.sleep(3.0)
    return "just a moment" not in (sb.get_title() or "").lower()


def _as_extract_ratio(text):
    """Headline numbers of one AlphaSpread ratio page (verified on the real page text in as_probe v1)."""
    out = {}
    found = re.search(r"([\d.,]+)\s*Current\b", text) or re.search(r"Current\s*([\d.,]+)", text)
    if found:
        out["current"] = _as_num(found.group(1))
    for label, key in (("3-y average", "avg3y"), ("5-y average", "avg5y"), ("10-y average", "avg10y"),
                       ("3-Year Average", "avg3y"), ("5-Year Average", "avg5y"), ("10-Year Average", "avg10y"),
                       ("Industry Average", "industry"), ("Country Average", "country")):
        found = re.search(re.escape(label) + r"\s*(?:of\s*)?(-?[\d.,]+)", text, re.I)
        if found and key not in out:
            out[key] = _as_num(found.group(1))
    return out


def fetch_as_ratios(sb, abbrev_as):
    """Never raises: the DCF must not depend on it. Fills _AS_RATIOS = {pe|pocf|pfcf: {current, avg3y, ...}}."""
    _AS_RATIOS.clear()
    base = "https://www.alphaspread.com/security/{}/relative-valuation/ratio/".format(as_path(abbrev_as))
    for name, slug in AS_RATIO_PAGES:
        try:
            _as_open_cf(sb, base + slug, 4)
            source = sb.get_page_source()
            if "just a moment" in (sb.get_title() or "").lower() or len(source) < 3000:
                step("ratio_" + name, "FAIL", reason="blocked")
                if _FAST_BLOCK.get("on"):
                    break   # v60: blocked right after a failed DCF -> skip the remaining ratio pages
                continue
            values = _as_extract_ratio(_as_strip_text(source))
            if values.get("current") is not None:
                _AS_RATIOS[name] = values
            step("ratio_" + name, "OK" if values.get("current") is not None else "FAIL", **{k: v for k, v in values.items() if k in ("current", "avg5y", "industry")})
        except Exception as ratio_error:
            step("ratio_" + name, "FAIL", reason=type(ratio_error).__name__)


_BB_VAL = r"(?:[-\u2212\u2013]?\s*\d[\d.,]*\s*%|[\u2014\u2013-])"   # v67: "-6.44%", "3.31%", or a dash / em dash = missing


def _bb_cell(token):
    """v67: one cell of the Buybacks table -> float, or None for a dash / empty cell. A real 0.00% is returned as 0.0 (never missing)."""
    token = (token or "").strip().replace("\u2212", "-").replace("\u2013", "-")
    if "%" not in token:
        return None
    return _as_num(token.replace(" ", ""))


def _as_extract_buyback(text, ticker=None):
    """v69: reads ONLY the Buybacks table (Company | Buyback Yield | Average Yield (3Y) | (5Y) | (10Y)). The row of the stock is found by its ticker and
    its FOUR cells must follow the ticker directly (a cell is a value, a dash, or "Unlock" = hidden for visitors without a subscription). v68 took the
    next four value tokens wherever they were and so read the NEXT company's row when the stock's own cells were "Unlock" (BILI got Alphabet's numbers).
    Returns {now, y3, y5, y10, match, src} (None = missing or locked cell) or {"diag": ..., "locked": True/False}."""
    head = re.search(r"Buyback Yield\s+Average Yield\s*\(3Y\)\s+Average Yield\s*\(5Y\)\s+Average Yield\s*\(10Y\)", text, re.I)
    if not head:
        at = text.find("Buyback")
        return {"diag": "no table header | " + (text[max(0, at - 80):at + 400] if at >= 0 else "no 'Buyback' text on the page"), "locked": False}
    scope = text[head.end():head.end() + 2500]
    stop = re.search(r"Dividend\s+(?:Yield|History|Payout|Growth)", scope, re.I)
    if stop:
        scope = scope[:stop.start()]
    cell = r"(" + _BB_VAL + r"|Unlock)"
    found = None
    if ticker:
        found = re.search(r"(?<![A-Za-z0-9.])" + re.escape(ticker) + r"(?![A-Za-z0-9])\s+" + cell + r"\s+" + cell + r"\s+" + cell + r"\s+" + cell, scope, re.I)
    if not found:
        return {"diag": "ticker " + str(ticker) + " not found | " + scope[:400], "locked": False}
    vals = [None if g.lower() == "unlock" else _bb_cell(g) for g in found.groups()]
    if all(v is None for v in vals):
        return {"diag": "row of " + str(ticker) + " is locked (Unlock) or empty", "locked": True}
    return {"now": vals[0], "y3": vals[1], "y5": vals[2], "y10": vals[3], "match": "ticker", "src": "table"}


def _as_extract_buyback_widget(text):
    """v69: only the CURRENT buyback yield from the 'Buyback Yield -6.44%' widget (the table row is locked for visitors); 3Y / 5Y / 10Y stay missing."""
    found = re.search(r"Buyback Yield\s*:?\s*([-\u2212]?\s*\d[\d.,]*)\s*%", text)
    if not found:
        return {}
    return {"now": _as_num(found.group(1).replace("\u2212", "-").replace(" ", "")), "y3": None, "y5": None, "y10": None, "match": "widget", "src": "summary"}


def _bb_ready(values):
    """v67: usable when the current buyback yield (now) is read. Missing 3Y / 5Y / 10Y cells stay None; a real 0.00 is a number, never missing."""
    return isinstance(values, dict) and values.get("now") is not None


def _qm_bb(bb):
    """v67: the buyback numbers as posted to the sheet: cur = now, y3 / y5 / y10 (None = missing), avg5 = y5 (old name, kept)."""
    return {"cur": bb.get("now"), "y3": bb.get("y3"), "y5": bb.get("y5"), "y10": bb.get("y10"), "avg5": bb.get("y5")}


def _bb_ticker(abbrev_as):
    """v67: the ticker part of abbrevAS ('nyse/orcl' -> 'ORCL')."""
    from urllib.parse import unquote   # v71: 'sto/lifco%20b' -> 'LIFCO B' (the ticker as the Buybacks table shows it)
    return unquote(str(abbrev_as or "").split("/")[-1]).strip().upper() or None


def fetch_as_buyback(sb, abbrev_as):
    """v67: opens https://www.alphaspread.com/security/{exchange}/{ticker}/dividends#buybacks, waits until the Buybacks table has rendered
    and reads its row for the stock (now / 3Y / 5Y / 10Y) into _AS_RATIOS['buyback']. Never raises."""
    url = "https://www.alphaspread.com/security/{}/dividends#buybacks".format(as_path(abbrev_as))
    ticker = _bb_ticker(abbrev_as)
    try:
        _as_open_cf(sb, url, 5)
        source = sb.get_page_source()
        if "just a moment" in (sb.get_title() or "").lower() or len(source) < 3000:
            step("buyback", "FAIL", reason="blocked")
            return
        values = _as_extract_buyback(_as_strip_text(source), ticker)
        # the table renders lazily - up to 3 extra tries (scroll to the Buybacks table, wait, re-read; the last try reloads the page)
        for attempt in range(3):
            if _bb_ready(values) or values.get("locked"):   # v69: a locked row will not unlock by waiting
                break
            try:
                if attempt == 2:
                    sb.uc_open_with_reconnect(url, 5)
                sb.execute_script("var e=document.getElementById('buybacks')||document.querySelector('[id*=buyback]');"
                                  "if(e){e.scrollIntoView({block:'center'});}else{window.scrollTo(0,document.body.scrollHeight/2);}")
                sb.sleep(4 + 3 * attempt)
                sb.execute_script("window.scrollBy(0,400);")
                sb.sleep(2)
                values = _as_extract_buyback(_as_strip_text(sb.get_page_source()), ticker)
            except Exception:
                pass
        if not _bb_ready(values) or (values.get("now") is not None and all(values.get(k) is None for k in ("y3", "y5", "y10"))) or values.get("locked"):
            # v69: the table row is hidden ("Unlock") or has only the current yield -> the current yield from the widget page (3Y / 5Y / 10Y stay missing)
            wdiag = ""
            try:
                wurl = "https://www.alphaspread.com/security/{}/investor-returns/i/buybacks".format(as_path(abbrev_as))
                _as_open_cf(sb, wurl, 5)
                widget = {}
                for wtry in range(3):   # v70: the widget renders lazily, like the table: wait / scroll / re-read (the last try reloads the page)
                    wtext = _as_strip_text(sb.get_page_source())
                    widget = _as_extract_buyback_widget(wtext)
                    if widget.get("now") is not None:
                        break
                    at = wtext.find("Buyback")
                    wdiag = ("widget not found | " + wtext[max(0, at - 60):at + 300]) if at >= 0 else ("no 'Buyback' text, page length " + str(len(wtext)))
                    try:
                        if wtry == 2:
                            sb.uc_open_with_reconnect(wurl, 5)
                        sb.execute_script("window.scrollTo(0,document.body.scrollHeight/3);")
                        sb.sleep(4 + 3 * wtry)
                    except Exception:
                        pass
                if widget.get("now") is not None and not _bb_ready(values):
                    values = dict(widget, diag=(values or {}).get("diag", ""))
                elif widget.get("now") is not None and values.get("now") is not None and abs(widget["now"] - values["now"]) > 0.05:
                    step("buyback", "INFO", note="table now differs from widget", table=values.get("now"), widget=widget["now"])
            except Exception:
                pass
            if not _bb_ready(values) and wdiag:
                values = dict(values or {}, diag=((values or {}).get("diag", "") + " || " + wdiag))
        if _bb_ready(values):
            _AS_RATIOS["buyback"] = values
            step("buyback", "OK", ticker=ticker, **{k: v for k, v in values.items() if k != "diag"})
        else:
            step("buyback", "FAIL", reason="no Buybacks table row for the ticker (or no current yield) on the page", ticker=ticker, diag=(values or {}).get("diag", ""))
    except Exception as buyback_error:
        step("buyback", "FAIL", reason=type(buyback_error).__name__)


AS_HIST_HEADLINE_SELECTOR = ".valuation-history-context__headline"
AS_HIST_CONTEXT_SELECTOR = ".valuation-history-context__headline-context"


def _as_parse_hist(headline, context):
    """v30: turns the AlphaSpread 'valuation history' sentence into a 0-100 rank = share of the past-5-year days on which the
    stock was MORE expensive (against its AS value) than today. 100 = cheaper than on every day, 0 = dearer than on every day.
      'It was this cheap or cheaper on just 21% of days ...'     -> 100 - 21 = 79
      'Still overvalued, but less so than on 88% of days ...'    -> 88
      'It was this expensive or more expensive on just 9% ...'   -> 9
      '... more so than on 30% of days ...'                      -> 100 - 30 = 70
      'valued in line with its history' (no percentage)          -> 50
    Returns (rank or None, rule text)."""
    text = re.sub(r"\s+", " ", "{} {}".format(headline or "", context or "")).strip()
    rules = (
        (r"this cheap or cheaper on (?:just |only |about |less than |fewer than |under )?(\d{1,3})\s*%", lambda n: 100 - n, "cheap-or-cheaper"),
        (r"less so than on (?:less than |fewer than )?(\d{1,3})\s*%", lambda n: n, "less-so-than"),
        (r"this expensive or more expensive on (?:just |only |about |less than |fewer than |under )?(\d{1,3})\s*%", lambda n: n, "expensive-or-more"),
        (r"more so than on (?:less than |fewer than )?(\d{1,3})\s*%", lambda n: 100 - n, "more-so-than"),
    )
    for pattern, convert, name in rules:
        found = re.search(pattern, text, re.I)
        if found:
            number = int(found.group(1))
            if 0 <= number <= 100:
                return convert(number), name
    if re.search(r"in line with (?:its|their) (?:own )?history", text, re.I):
        return 50, "in-line"
    return None, "no-rule"


_AS_HIST_PROBE_JS = (
    "var h = document.querySelector('.valuation-history-context__headline');"
    "var c = document.querySelector('.valuation-history-context__headline-context');"
    "var box = document.querySelector('.valuation-history-context');"
    "var body = document.body ? (document.body.innerText || '') : '';"
    "var hasText = /\\bis (valued in line with|cheaper than usual|more expensive than usual|near its usual|above its usual|below its usual)/i.test(body);"
    "return {headline: h ? (h.innerText || '') : '', context: c ? (c.innerText || '') : '', box: !!box, hasText: hasText,"
    " loading: !!document.querySelector('.valuation-history-context--loading'),"
    " y: Math.round(window.scrollY || 0), height: Math.round(document.body.scrollHeight || 0), vh: Math.round(window.innerHeight || 0)};"
)


def _as_hist_text_fallback(text):
    """v31/v33: no headline element -> take the sentence from the visible page text. It starts at "<TICKER> is ..." (so menu text
    before it is not taken along) and runs through the following sentence ('APP is valued in line with its history. A discount of this
    size has been typical over the past 5 years.')."""
    text = re.sub(r"[ \t\xa0]+", " ", text or "")
    found = re.search(r"\b([A-Z0-9][A-Z0-9.\-]{0,11} is (?:valued in line with (?:its|their) (?:own )?history|(?:cheaper|more expensive|pricier|dearer) than usual|(?:near|above|below|well above|well below) its usual valuation)\.?[^\n]{0,300})", text)
    return found.group(1).strip() if found else ""


def _as_hist_loose_fallback(text):
    """v73: last resort when the usual 'TICKER is cheaper than usual...' sentence is not found: any sentence of the page that says how often
    the stock was this cheap / expensive ('... was this cheap or cheaper on just 21% of days ...'), so the percentage can still be parsed."""
    text = re.sub(r"[ \t\xa0]+", " ", text or "")
    found = re.search(r"([^.\n]{0,160}(?:this cheap or cheaper|this expensive or more expensive|less so than|more so than)[^.\n]{0,60}?\d{1,3}\s*%[^.\n]{0,40})", text, re.I)
    return found.group(1).strip() if found else ""


_AS_HIST_OPEN_JS = (
    "var want = 'more details', best = null;"
    "document.querySelectorAll('a, button, span').forEach(function (e) {"
    "  if (!best && (e.textContent || '').trim().toLowerCase() === want && e.offsetParent !== null) { best = e; } });"
    "if (!best) { return 'none'; } best.scrollIntoView({block: 'center'}); best.click(); return 'clicked';"
)


def _as_parse_hist_modal(text):
    """v32: the 'More details' window gives the exact figure the one-line sentence often leaves out, e.g.
    'APP is near its usual valuation / Cheaper than on 63% of days over 5 years / Today - 41% undervalued /
     When APP was expensive -9% Typical return ... When APP was cheap +25% Typical return ...'.
    'Cheaper than on N% of days' -> rank N (today is cheaper than on N% of the days); 'More expensive than on N%' -> 100 - N.
    Returns a dict with whatever was found: rank, label, today (signed %: + undervalued, - overvalued), exp_return, cheap_return."""
    text = re.sub(r"[ \t\xa0]+", " ", text or "")
    out = {}
    found = re.search(r"(Cheaper|More expensive|Dearer|Pricier) than on (?:less than |fewer than |<\s*)?(\d{1,3})\s*%\s*of days", text, re.I)
    if found and 0 <= int(found.group(2)) <= 100:
        n = int(found.group(2))
        out["rank"] = n if found.group(1).lower() == "cheaper" else 100 - n
    found = re.search(r"\bis ((?:near|above|below|well above|well below)[^\n.]{0,40}(?:usual|history)[^\n.]{0,30}|(?:cheaper|more expensive|pricier|dearer) than usual|valued in line with[^\n.]{0,30})", text, re.I)
    if found:
        out["label"] = found.group(1).strip()
    found = re.search(r"Today\s*[\u00b7\u2022\-:]?\s*(\d{1,3})\s*%\s*(undervalued|overvalued)", text, re.I)
    if found:
        out["today"] = int(found.group(1)) * (1 if found.group(2).lower() == "undervalued" else -1)
    found = re.search(r"was expensive\s*([+\-\u2212]?\d{1,3})\s*%", text, re.I)
    if found:
        out["exp_return"] = int(found.group(1).replace("\u2212", "-"))
    found = re.search(r"was cheap\s*([+\-\u2212]?\d{1,3})\s*%", text, re.I)
    if found:
        out["cheap_return"] = int(found.group(1).replace("\u2212", "-"))
    return out


def _as_hist_open_details(sb):
    """v32: clicks 'More details' and returns the window's text ('' when it does not open). Never raises."""
    try:
        if sb.execute_script(_AS_HIST_OPEN_JS) != "clicked":
            return ""
        deadline = time.time() + 12
        text = ""
        while time.time() < deadline:
            sb.sleep(1.0)
            text = sb.execute_script("return document.body ? (document.body.innerText || '') : '';") or ""
            if re.search(r"\bof days\b[^\n]{0,20}\bover\b|Typical return", text, re.I):
                return text
        return text
    except Exception:
        return ""


_AS_SCORES_JS = r"""
var res = {profit: null, solv: null, hasProfit: false, hasSolv: false};
function norm(s) { return String(s || '').replace(/\s+/g, ' ').trim(); }
var body = document.body ? (document.body.innerText || '') : '';
res.hasProfit = /Profitability Score/i.test(body);
res.hasSolv = /Solvency Score/i.test(body);
function okState(el) {
  var icon = null;
  try { icon = el.querySelector('svg, i, img, [class*="icon"]'); } catch (e) {}
  var node = icon || el;
  var cls = '';
  try { cls = String((node.className && node.className.baseVal !== undefined) ? node.className.baseVal : node.className) + ' ' + String(el.className || ''); } catch (e) {}
  cls = cls.toLowerCase();
  if (/(check|tick|success|positive|green|good)/.test(cls)) { return true; }
  if (/(times|xmark|cross|close|danger|negative|\bred\b|bad|warning)/.test(cls)) { return false; }
  try {
    var st = getComputedStyle(node);
    var c = (st.color || '') + ' ' + (st.fill || '') + ' ' + (st.stroke || '');
    var m = c.match(/rgb\((\d+),\s*(\d+),\s*(\d+)/);
    if (m) {
      var r = +m[1], g = +m[2], b = +m[3];
      if (g > r + 30 && g > b) { return true; }
      if (r > g + 30 && r > b) { return false; }
    }
  } catch (e) {}
  return null;
}
function findCard(kind) {
  var re = new RegExp('^.{1,25} ' + kind + ' Score$', 'i');
  var viewRe = new RegExp('View ' + kind + ' Analysis', 'i');
  var els = document.querySelectorAll('h1,h2,h3,h4,h5,h6,div,span,p,a');
  for (var i = 0; i < els.length; i++) {
    var t = norm(els[i].textContent);
    if (t.length < 60 && re.test(t) && els[i].children.length <= 3) {
      var node = els[i];
      for (var up = 0; up < 12 && node; up++) {
        var tx = norm(node.textContent);
        if (tx.length < 2500 && viewRe.test(tx)) { return {node: node, title: t}; }
        node = node.parentElement;
      }
    }
  }
  return null;
}
var SKIP = /( (Profitability|Solvency) Score$|Due Diligence$|^View |^\/ ?100$|^(PROFITABILITY|SOLVENCY|SCORE)$)/i;
function linesOf(text) { return String(text || '').split(/\n+/).map(norm).filter(function (l) { return l; }); }
function readCard(kind) {
  var headRe = new RegExp(kind + ' Score$', 'i');
  var found = findCard(kind);
  var card = found ? found.node : null;
  var lines = card ? linesOf(card.innerText) : null;
  if (!lines || !lines.length) {
    lines = linesOf(document.body ? document.body.innerText : '');
  }
  var h = -1;
  for (var i = 0; i < lines.length; i++) { if (headRe.test(lines[i]) && lines[i].length < 60) { h = i; break; } }
  if (h < 0) { return null; }
  lines = lines.slice(h);
  var out = {title: lines[0], score: null, items: [], href: '', color: '', dbg: lines.slice(0, 12).join(' | ').slice(0, 300), cardFound: !!card};
  var seen = {};
  for (var n = 1; n < lines.length && n < 40; n++) {
    var line = lines[n];
    if (/^View /i.test(line)) { break; }
    var m = line.match(/^(\d{1,3})(?:\s*\/\s*100)?$/);
    if (m) { if (out.score === null) { out.score = parseInt(m[1], 10); } continue; }
    if (!SKIP.test(line) && line.length >= 6 && line.length <= 90 && !seen[line]) { seen[line] = 1; out.items.push({t: line, ok: null}); }
  }
  if (card) {
    var leaves = [];
    card.querySelectorAll('*').forEach(function (e) { if (e.children.length === 0 && norm(e.textContent)) { leaves.push(e); } });
    out.items.forEach(function (item) {
      for (var k = 0; k < leaves.length; k++) {
        if (norm(leaves[k].textContent) === item.t) { item.ok = okState(leaves[k].parentElement || leaves[k]); break; }
      }
    });
    if (out.score !== null) {
      // v38: the number often sits next to a "/ 100" child inside one element, so it is not a leaf. Take the deepest element whose
      // whole text is "NN" or "NN / 100" and read the colour of that element.
      var scoreRe = /^(\d{1,3})(?:\s*\/\s*100)?$/;
      var best = null;
      card.querySelectorAll('*').forEach(function (e) {
        var m2 = norm(e.textContent).match(scoreRe);
        if (m2 && parseInt(m2[1], 10) === out.score) {
          var childMatches = false;
          for (var c = 0; c < e.children.length; c++) {
            var m3 = norm(e.children[c].textContent).match(scoreRe);
            if (m3 && parseInt(m3[1], 10) === out.score) { childMatches = true; break; }
          }
          if (!childMatches) { best = e; }
        }
      });
      if (best) {
        try {
          var cc = getComputedStyle(best).color || '';
          var cm = cc.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/);
          if (cm) {
            var hx = function (v) { var s2 = Math.max(0, Math.min(255, +v)).toString(16); return s2.length < 2 ? '0' + s2 : s2; };
            out.color = '#' + hx(cm[1]) + hx(cm[2]) + hx(cm[3]);
          }
        } catch (e) {}
      }
    }
    var links = card.querySelectorAll('a[href]');
    for (var z = 0; z < links.length; z++) {
      if (/view/i.test(norm(links[z].textContent))) { out.href = links[z].href || ''; break; }
    }
  }
  return out;
}
res.profit = readCard('Profitability');
res.solv = readCard('Solvency');
return res;
"""


def _as_scores_clean(card):
    """v35: one card dict from the page script -> {score, title, items:[{t, ok}], href} or None when no usable score."""
    if not isinstance(card, dict):
        return None
    score = card.get("score")
    if isinstance(score, float) and score == int(score):
        score = int(score)
    if not isinstance(score, int) or score < 0 or score > 100:
        return None
    items = []
    for item in (card.get("items") or [])[:8]:
        if isinstance(item, dict) and str(item.get("t") or "").strip():
            items.append({"t": str(item["t"]).strip()[:90], "ok": item.get("ok") if item.get("ok") in (True, False) else None})
    color = str(card.get("color") or "").strip().lower()
    if not re.match(r"^#[0-9a-f]{6}$", color):
        color = ""
    cleaned = {"score": score, "title": str(card.get("title") or "")[:60], "items": items, "href": str(card.get("href") or "")[:300], "color": color}
    if card.get("checks"):
        cleaned["checks"] = card.get("checks")
    return cleaned


def _as_fetch_scores_on_page(sb, url, _retry=False):
    """v35: the summary page is already open (fetch_as_hist). Reads the Profitability and Solvency cards, scrolling down in steps
    until both show a score (they may be lazy loaded like the history block). Stores _AS_RATIOS['scores']. Never raises."""
    if os.environ.get("AS_SCORES", "1") == "0":
        return
    try:
        if "just a moment" in (sb.get_title() or "").lower():   # v46: Cloudflare page instead of the summary: do not wait 20 s for cards
            step("scores", "FAIL", reason="blocked")
            return
        deadline = time.time() + int(os.environ.get("AS_SCORES_WAIT", "20"))
        result = {}
        scroll_y = 0
        rounds = 0
        while time.time() < deadline:
            rounds += 1
            try:
                result = sb.execute_script(_AS_SCORES_JS) or {}
            except Exception:
                result = {}
            profit = _as_scores_clean(result.get("profit"))
            solv = _as_scores_clean(result.get("solv"))
            if profit and solv:
                break
            try:  # v45: bring the card heading itself into view (a lazy card may stay empty until it is really on screen)
                if rounds >= 3:
                    sb.execute_script(
                        "var t = (arguments[0] % 2) ? 'Profitability Score' : 'Solvency Score', f = null;"
                        "document.querySelectorAll('h1,h2,h3,h4,div,span').forEach(function (e) {"
                        "  if (!f && e.children.length === 0 && (e.textContent || '').trim().slice(-t.length) === t) { f = e; } });"
                        "if (f) { f.scrollIntoView({block: 'center'}); }", rounds)
                    sb.sleep(1.5)
            except Exception:
                pass
            try:
                height = int(sb.execute_script("return Math.round(document.body.scrollHeight || 0);") or 0)
                scroll_y = scroll_y + 600
                if height and scroll_y > height:
                    scroll_y = 0
                sb.execute_script("window.scrollTo(0, {});".format(scroll_y))
            except Exception:
                pass
            sb.sleep(1.2)
        profit = _as_scores_clean(result.get("profit"))
        solv = _as_scores_clean(result.get("solv"))
        if not profit and not solv and not _retry:
            step("scores", "INFO", note="no score yet: reloading the page once")  # v45
            try:
                sb.uc_open_with_reconnect(url, 4)
                sb.sleep(4.0)
            except Exception:
                pass
            return _as_fetch_scores_on_page(sb, url, True)
        if not profit and not solv:
            try:
                os.makedirs(DIAGNOSTICS_DIR, exist_ok=True)
                with open(os.path.join(DIAGNOSTICS_DIR, "as_scores_row{}.html".format(os.environ.get("ROW_NUMBER", ""))), "w", encoding="utf-8") as handle:
                    handle.write(sb.get_page_source()[:400000])
            except Exception:
                pass
            pr, sv = result.get("profit") or {}, result.get("solv") or {}
            step("scores", "FAIL", reason="no score found", hasProfit=result.get("hasProfit"), hasSolv=result.get("hasSolv"), rounds=rounds,
                 profitCard=pr.get("cardFound"), profitScore=pr.get("score"), profitText=repr(pr.get("dbg"))[:260],
                 solvCard=sv.get("cardFound"), solvScore=sv.get("score"), solvText=repr(sv.get("dbg"))[:260])
            return
        scores = {"url": url}
        if profit:
            scores["profit"] = profit
        if solv:
            scores["solv"] = solv
        _AS_RATIOS["scores"] = scores
        step("scores", "OK", profit=(profit or {}).get("score"), solv=(solv or {}).get("score"),
             profitItems=len((profit or {}).get("items") or []), solvItems=len((solv or {}).get("items") or []),
             profitColor=(profit or {}).get("color"), solvColor=(solv or {}).get("color"), rounds=rounds)
    except Exception as scores_error:
        step("scores", "FAIL", reason=type(scores_error).__name__)


_AS_CHECKS_JS = r"""
var out = {found: false, checks: [], expanded: false, dbg: ''};
function norm(s) { return String(s || '').replace(/\s+/g, ' ').trim(); }
function rgbOf(str) {
  var m = String(str || '').match(/rgba?\((\d+),\s*(\d+),\s*(\d+)(?:,\s*([\d.]+))?/);
  if (!m) { return null; }
  if (m[4] !== undefined && parseFloat(m[4]) === 0) { return null; }
  return [+m[1], +m[2], +m[3]];
}
function classify(c) {
  var r = c[0], g = c[1], b = c[2];
  if (r > 200 && g > 130 && b < 110) { return 'warn'; }
  if (r > 150 && g < 110 && b < 130) { return 'bad'; }
  if (g > r + 20 && g > b) { return 'ok'; }
  return null;
}
function statusOf(svg) {
  var cands = [];
  try {
    var cs = getComputedStyle(svg);
    cands.push(cs.fill, cs.stroke, cs.color);
    var inner = svg.querySelector('path,circle');
    if (inner) { var ci = getComputedStyle(inner); cands.push(ci.fill, ci.stroke); }
  } catch (e) {}
  for (var i = 0; i < cands.length; i++) {
    var c = rgbOf(cands[i]);
    if (c) { var k = classify(c); if (k) { return k; } }
  }
  var cls = String(svg.getAttribute('class') || '') + ' ' + String(svg.parentElement ? svg.parentElement.className : '');
  cls = cls.toLowerCase();
  if (/(check|success)/.test(cls)) { return 'ok'; }
  if (/(times|xmark|cross|danger|error)/.test(cls)) { return 'bad'; }
  if (/(warn|exclam|minus)/.test(cls)) { return 'warn'; }
  return null;
}
var head = null;
document.querySelectorAll('*').forEach(function (e) {
  if (!head && e.children.length === 0 && /^Due Diligence Checks/i.test(norm(e.textContent))) { head = e; }
});
if (!head) { return out; }
var cont = head;
for (var up = 0; up < 8; up++) {
  if (!cont.parentElement) { break; }
  cont = cont.parentElement;
  if (cont.querySelectorAll('svg').length >= 4) { break; }
}
out.found = true;
out.expanded = /\bHide\b/.test(norm(cont.innerText || ''));
var seen = {};
cont.querySelectorAll('svg').forEach(function (svg) {
  var pill = svg.parentElement;
  for (var u = 0; u < 4 && pill && pill !== cont && norm(pill.textContent).length < 6; u++) { pill = pill.parentElement; }
  if (!pill || pill === cont) { return; }
  if (pill.querySelectorAll('svg').length > 1) { return; }
  var txt = norm(pill.innerText || pill.textContent);
  if (!txt || /^(View All|Hide)$/i.test(txt) || txt.length > 140) { return; }
  var m = txt.match(/^(.*?)\s+(-?[\d.,]+\s*(?:%|x|B|M|K|T)?(?:\s*>\s*-?[\d.,]+\s*(?:%|x|B|M|K|T)?)?)$/);
  var name = m ? m[1] : txt;
  var val = m ? m[2] : '';
  if (name.length < 4 || seen[txt]) { return; }
  seen[txt] = 1;
  out.checks.push({t: name.slice(0, 90), v: val.slice(0, 24), s: statusOf(svg)});
});
out.dbg = norm(cont.innerText || '').slice(0, 200);
return out;
"""

_AS_VIEW_ALL_JS = (
    "var best = null;"
    "document.querySelectorAll('a, button, span, div').forEach(function (e) {"
    "  if (!best && e.children.length <= 2 && (e.textContent || '').replace(/\\s+/g, ' ').trim().toLowerCase() === 'view all' && e.offsetParent !== null) { best = e; } });"
    "if (!best) { return 'none'; } best.scrollIntoView({block: 'center'}); best.click(); return 'clicked';"
)


def fetch_as_score_details(sb, abbrev_as):
    """v39: opens the AlphaSpread Profitability / Solvency pages named by the summary cards, clicks 'View All' and stores every
    due-diligence check under _AS_RATIOS['scores'][kind]['checks']. Never raises; on any failure the summary card's reasons stay."""
    if os.environ.get("AS_SCORE_DETAILS", "0") != "1" or os.environ.get("AS_SCORES", "1") == "0":
        return
    scores = _AS_RATIOS.get("scores")
    if not isinstance(scores, dict):
        return
    base = "https://www.alphaspread.com/security/{}".format(as_path(abbrev_as))
    for kind, page in (("profit", "profitability"), ("solv", "solvency")):
        card = scores.get(kind)
        if not isinstance(card, dict):
            continue
        href = str(card.get("href") or "")
        url = href if ("alphaspread.com" in href and page[:6] in href.lower()) else "{}/{}".format(base, page)
        try:
            sb.uc_open_with_reconnect(url, 5)
            sb.sleep(1.5)
            deadline = time.time() + int(os.environ.get("AS_SCORE_DETAILS_WAIT", "20"))
            data = {}
            while time.time() < deadline:
                try:
                    data = sb.execute_script(_AS_CHECKS_JS) or {}
                except Exception:
                    data = {}
                if data.get("found") and len(data.get("checks") or []) >= 3:
                    break
                try:
                    sb.execute_script("window.scrollTo(0, 500);")
                except Exception:
                    pass
                sb.sleep(1.2)
            clicked = ""
            if data.get("found") and not data.get("expanded"):
                try:
                    clicked = sb.execute_script(_AS_VIEW_ALL_JS) or ""
                except Exception:
                    clicked = ""
                if clicked == "clicked":
                    sb.sleep(1.5)
                    try:
                        data = sb.execute_script(_AS_CHECKS_JS) or data
                    except Exception:
                        pass
            checks = []
            for item in (data.get("checks") or [])[:40]:
                if isinstance(item, dict) and str(item.get("t") or "").strip():
                    status = item.get("s") if item.get("s") in ("ok", "warn", "bad") else None
                    checks.append({"t": str(item["t"]).strip()[:90], "v": str(item.get("v") or "").strip()[:24], "s": status})
            if len(checks) >= 3:
                card["checks"] = checks
                step("scores_detail", "OK", kind=kind, checks=len(checks), expanded=data.get("expanded"), viewAll=clicked or "-",
                     ok=sum(1 for c in checks if c["s"] == "ok"), warn=sum(1 for c in checks if c["s"] == "warn"), bad=sum(1 for c in checks if c["s"] == "bad"),
                     unknown=sum(1 for c in checks if c["s"] is None))
            else:
                try:
                    os.makedirs(DIAGNOSTICS_DIR, exist_ok=True)
                    with open(os.path.join(DIAGNOSTICS_DIR, "as_{}_row{}.html".format(page, os.environ.get("ROW_NUMBER", ""))), "w", encoding="utf-8") as handle:
                        handle.write(sb.get_page_source()[:400000])
                except Exception:
                    pass
                step("scores_detail", "FAIL", kind=kind, reason="fewer than 3 checks", found=data.get("found"), viewAll=clicked or "-",
                     text=repr(data.get("dbg"))[:200], url=url[-60:])
        except Exception as detail_error:
            step("scores_detail", "FAIL", kind=kind, reason=type(detail_error).__name__)


def fetch_as_hist(sb, abbrev_as):
    """v30/v31: reads the AlphaSpread 'valuation history' sentence (.../summary) and stores {rank, headline, context, url} under
    _AS_RATIOS['hist']. The block is a lazy Livewire component below the fold (v30 never saw it after 40 s without scrolling), so v31
    scrolls in steps until it appears. On failure it saves diagnostics/as_hist_row<N>.html. Never raises."""
    url = "https://www.alphaspread.com/security/{}/summary".format(as_path(abbrev_as))
    _QM_WALL.clear()   # v49: never reuse the widget of the previous stock
    try:
        _as_open_cf(sb, url, 5)
        if "/summary" not in (sb.get_current_url() or ""):   # v73: the browser stayed on another page (EVO / NVDA were read on .../revenue): open the summary page again
            try:
                sb.uc_open_with_reconnect(url, 5)
            except Exception:
                pass
        if "just a moment" in (sb.get_title() or "").lower():
            step("hist", "FAIL", reason="blocked")
            return
        sb.sleep(2.0)
        deadline = time.time() + int(os.environ.get("AS_HIST_WAIT", "45"))
        probe = {}
        scroll_y = 0
        rounds = 0
        while time.time() < deadline:
            rounds += 1
            try:
                probe = sb.execute_script(_AS_HIST_PROBE_JS) or {}
            except Exception:
                probe = {}
            if (probe.get("headline") or "").strip() and not probe.get("loading"):
                break
            if probe.get("hasText") and rounds >= 2:
                break  # v33: the class name of the headline is not always there; the sentence is in the text
            try:
                if probe.get("box"):
                    sb.execute_script("document.querySelector('.valuation-history-context').scrollIntoView({block: 'center'});")
                else:
                    height = int(probe.get("height") or 0)
                    step_px = max(500, int(probe.get("vh") or 700) - 100)
                    scroll_y = scroll_y + step_px
                    if height and scroll_y > height:
                        scroll_y = 0
                    sb.execute_script("window.scrollTo(0, {});".format(scroll_y))
            except Exception:
                pass
            sb.sleep(1.5)
        _as_fetch_scores_on_page(sb, url)  # v35: Profitability / Solvency cards, same page visit
        if os.environ.get("AS_FIN", "1") != "0":   # v49: Wall St Estimates widget, same page visit (the summary page is opened once)
            try:
                import as_qm_data
                _QM_WALL.clear()
                _QM_WALL.update(as_qm_data.read_wall_st(sb, step))
                _QM_WALL["visited"] = (_QM_WALL.get("rev") is not None or _QM_WALL.get("earn") is not None)   # empty (widget still "Loading") -> the QM step reads the page again
            except Exception:
                pass
        headline = (probe.get("headline") or "").strip()
        context = (probe.get("context") or "").strip()
        if not headline:
            try:
                visible_text = sb.execute_script("return document.body ? (document.body.innerText || '') : '';") or ""
            except Exception:
                visible_text = ""
            fallback = _as_hist_text_fallback(visible_text) or _as_hist_text_fallback(_as_strip_text(sb.get_page_source())) or _as_hist_loose_fallback(visible_text)
            if fallback:
                headline, context = fallback, ""
                step("hist", "INFO", note="headline element missing, sentence found in the page text")
        if not headline:
            try:
                os.makedirs(DIAGNOSTICS_DIR, exist_ok=True)
                with open(os.path.join(DIAGNOSTICS_DIR, "as_hist_row{}.html".format(os.environ.get("ROW_NUMBER", "")) ), "w", encoding="utf-8") as handle:
                    handle.write(sb.get_page_source()[:AS_PAGE_SAVE_CHARS if "AS_PAGE_SAVE_CHARS" in globals() else 400000])
            except Exception:
                pass
            try:   # v73: what the page says about its history / usual valuation, to see why the sentence is missing
                at_hist = [m.start() for m in re.finditer(r"usual|history|of days|Unlock", visible_text)]
                snippet = " ~ ".join(re.sub(r"\s+", " ", visible_text[max(0, a - 60):a + 140]) for a in at_hist[:3])[:420]
            except Exception:
                snippet = ""
            step("hist", "FAIL", reason="headline did not appear", rounds=rounds, box=probe.get("box"), loading=probe.get("loading"),
                 scrollHeight=probe.get("height"), title=(sb.get_title() or "")[:60], url=(sb.get_current_url() or "")[:90], diag=snippet or "no 'usual' / 'history' / 'of days' text")
            return
        rank, rule = _as_parse_hist(headline, context)
        # v32: the 'More details' window has the exact figure ("Cheaper than on 63% of days over 5 years"); the one-line
        # sentence often has none ("valued in line with its history"). The window's figure wins when it is there.
        modal = {}
        try:
            modal = _as_parse_hist_modal(_as_hist_open_details(sb))
        except Exception:
            modal = {}
        if modal.get("rank") is not None:
            rank, rule = modal["rank"], "details-window"
        if rank is None:
            step("hist", "FAIL", reason="sentence not understood", headline=headline[:90], context=context[:140], modal=",".join(sorted(modal.keys())))
            return
        _AS_RATIOS["hist"] = {"rank": rank, "rule": rule, "headline": headline[:160], "context": context[:260], "url": url,
                              "label": modal.get("label"), "today": modal.get("today"),
                              "expReturn": modal.get("exp_return"), "cheapReturn": modal.get("cheap_return")}
        step("hist", "OK", rank=rank, rule=rule, today=modal.get("today"), rounds=rounds, headline=headline[:60])
    except Exception as hist_error:
        step("hist", "FAIL", reason=type(hist_error).__name__)


def post_as_ratios_if_any(webhook_url, row_number, abbrev, sheet_name, info):
    """Posts the collected AS ratios once (target ASRP); never touches the DCF result."""
    if not _AS_RATIOS:
        return
    ratios = dict(_AS_RATIOS)
    _AS_RATIOS.clear()
    saved_post = dict(_LAST_POST)
    try:
        posted = post_provider_json(webhook_url, "ASRP", row_number, abbrev, sheet_name, {"ratios": ratios})
        info["ratios"] = {"posted": bool(posted), "got": sorted(ratios.keys()),
                          "reason": None if posted else _LAST_POST.get("reason")}
    except Exception as ratios_error:
        print("❌ AS ratios post failed: {}".format(ratios_error))
        info["ratios"] = {"posted": False, "got": sorted(ratios.keys()), "reason": str(ratios_error)[:80]}
    finally:
        _LAST_POST.clear()
        _LAST_POST.update(saved_post)


# ----------------------------------------------------------------------------
# v18: structural quality metrics (as_quality_metrics.py) from the AlphaSpread statement pages
# ----------------------------------------------------------------------------
_AS_QUALITY = {}
_QM_SRC = {}   # v48: moat block + TTM "now" block, kept even when an annual statement page is blocked and fetch_as_quality gives up
_QM_WALL = {}   # v49: Wall St Estimates widget read during the summary visit of fetch_as_hist
_QM_PROF = {"html": ""}   # v48: profitability page of the current stock, reused by the Quality Model step
AS_QUALITY_PAGES = (("profitability", "profitability"), ("income", "financials/income-statement"),
                    ("balance", "financials/balance-sheet"), ("cashflow", "financials/cash-flow-statement"))


# v21: the statement pages have an Annual / Quarterly / TTM switch. Income + cash flow -> TTM, balance sheet -> Quarterly.
AS_TTM_TOGGLE = {"income": ("TTM", r"TTM\s+[A-Z][a-z]{2}\s+\d{4}"), "cashflow": ("TTM", r"TTM\s+[A-Z][a-z]{2}\s+\d{4}"),
                 "balance": ("Quarterly", r"Q\d\s*FY\d{4}")}


def _as_click_view(sb, toggle):
    """v45: clicks the view switch by its visible text (up to 3 attempts, 12 s each) and returns the page source once the new header shows; '' on failure."""
    label, ready_pattern = toggle
    key = "quality_view_" + label.lower()
    js = ("var want = arguments[0], best = null;"
          "document.querySelectorAll('button, a, label, li, span, div').forEach(function (e) {"
          "  if (e.children.length === 0 && (e.textContent || '').trim() === want) { best = best || e; } });"
          "if (!best) { return 'none'; } best.scrollIntoView({block: 'center'}); best.click(); return 'clicked';")
    reason = "header did not change"
    for attempt in range(1, 4):
        try:
            if sb.execute_script(js, label) != "clicked":
                reason = "toggle not found"
                sb.sleep(2.0)
                continue
            for _ in range(12):
                sb.sleep(1.0)
                source = sb.get_page_source()
                if re.search(ready_pattern, re.sub(r"<[^>]+>", " ", source)):
                    step(key, "OK", chars=len(source), attempt=attempt)
                    return source
            reason = "header did not change"
        except Exception as view_error:
            reason = type(view_error).__name__
            sb.sleep(2.0)
    step(key, "FAIL", reason=reason, attempts=3)
    return ""


def fetch_as_quality(sb, abbrev_as):
    """Never raises: the DCF must not depend on it. Fills _AS_QUALITY with the metrics dict (see as_quality_metrics)."""
    _AS_QUALITY.clear()
    _QM_SRC.clear()
    _QM_PROF["html"] = ""
    try:
        import as_quality_metrics
    except Exception as import_error:
        step("quality", "FAIL", reason="as_quality_metrics.py missing: " + type(import_error).__name__)
        return
    base = "https://www.alphaspread.com/security/{}/".format(as_path(abbrev_as))
    pages, ttm_pages, q_pages = {}, {}, {}
    for name, path in AS_QUALITY_PAGES:
        try:
            source = ""
            for open_try in (1, 2, 3):   # v48: a Cloudflare page in the middle of the run is retried (wait, verification click, reopen)
                sb.uc_open_with_reconnect(base + path, 4)
                source = ""
                for _ in range(14):
                    source = sb.get_page_source()
                    ready = ("3Y Average ROIC" in source) if name == "profitability" else bool(re.search(r"FY\s*20\d\d", source))
                    if ready:
                        break
                    if "just a moment" in (sb.get_title() or "").lower() and _ >= 4:
                        break
                    sb.sleep(1.5)
                if "just a moment" not in (sb.get_title() or "").lower():
                    break
                step("quality_" + name, "INFO", note="Cloudflare page, retry {}".format(open_try))
                sb.sleep(20 * open_try)
                try:
                    sb.uc_gui_click_captcha()
                    sb.sleep(4.0)
                except Exception:
                    pass
            if "just a moment" in (sb.get_title() or "").lower():
                step("quality_" + name, "FAIL", reason="blocked")
                continue
            pages[name] = source
            step("quality_" + name, "OK", chars=len(source))
            if name == "profitability":
                _QM_PROF["html"] = source
            if name in AS_TTM_TOGGLE:  # v21: same page, other view (TTM / Quarterly); never blocks the annual metrics
                ttm_pages[name] = _as_click_view(sb, AS_TTM_TOGGLE[name])
                if name in ("income", "cashflow") and not ttm_pages[name]:  # v45: TTM toggle failed -> the Quarterly toggle (reliable) gives 4-quarter sums
                    q_pages[name] = _as_click_view(sb, ("Quarterly", r"Q\d\s*FY\d{4}"))
        except Exception as page_error:
            step("quality_" + name, "FAIL", reason=type(page_error).__name__)
    moat_source = ""
    try:  # v22: AlphaSpread "Economic Moat" page (rating + advantage tags); never blocks the metrics
        _as_open_cf(sb, base + "qualitative/block/economic-moat", 4)
        for _ in range(12):
            moat_source = sb.get_page_source()
            if "What is Economic Moat?" in moat_source or "How we rate moats" in moat_source:   # old / new (2026-10-20) page layout
                break
            sb.sleep(1.5)
        step("quality_moat_page", "OK", chars=len(moat_source))
    except Exception as moat_page_error:
        step("quality_moat_page", "FAIL", reason=type(moat_page_error).__name__)
    try:   # v48: moat + TTM block for the Quality Model, independent of the annual statement pages
        if moat_source:
            import as_moat
            _QM_SRC["moat"] = as_moat.parse_moat(moat_source)
        if ttm_pages.get("income") or q_pages.get("income"):
            import as_ttm_metrics
            _QM_SRC["now"] = as_ttm_metrics.compute_now(ttm_pages.get("income", ""), ttm_pages.get("cashflow", ""), ttm_pages.get("balance", ""),
                                                        income_q_html=q_pages.get("income", ""), cashflow_q_html=q_pages.get("cashflow", ""))
        step("qm_src", "OK", moat=(_QM_SRC.get("moat") or {}).get("rating"), ttm=bool((_QM_SRC.get("now") or {}).get("signals")))
    except Exception as qm_src_error:
        step("qm_src", "FAIL", reason=type(qm_src_error).__name__ + ": " + str(qm_src_error)[:60])
    if not all(k in pages for k in ("income", "balance", "cashflow")):
        step("quality", "FAIL", reason="statement pages missing: " + ",".join(sorted(pages.keys())))
        return
    try:
        result = as_quality_metrics.compute_metrics(pages.get("profitability", ""), pages["income"], pages["balance"], pages["cashflow"])
    except Exception as compute_error:
        step("quality", "FAIL", reason="compute " + type(compute_error).__name__ + ": " + str(compute_error)[:60])
        return
    diag = result.get("diagnostics", {})
    _AS_QUALITY.update({
        "metrics": result["metrics"], "scores": result["scores"], "partial_structural": result["partial_structural"],
        "coverage_pct": result["coverage_pct"], "display": result["display"], "flags": result["flags"],
        "scrapedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "details": result.get("details"),  # v20: the numbers behind each cell (for the cell notes)
        "diag": {"roic3y_source": diag.get("roic3y_source"), "last5": diag.get("last5"), "notes": diag.get("notes"),
                 "income_cols": (diag.get("income") or {}).get("columns"), "warnings": [v.get("warning") for v in (diag.get("income"), diag.get("balance"), diag.get("cashflow")) if v and v.get("warning")]},
    })
    v4_block = None
    try:  # v22: Q v4 (as_quality_v4.py) next to the old Struct; the sheet shows both until the old columns are removed
        import as_quality_v4
        v4_full = as_quality_v4.compute_v4(pages.get("profitability", ""), pages["income"], pages["balance"], pages["cashflow"])
        det = v4_full.get("details") or {}
        v4_block = {k: v4_full.get(k) for k in ("v", "profile", "metrics", "scores", "weights", "q", "q_capped", "coverage_pct", "flags", "warnings", "display")}
        v4_block["diag"] = {k: det.get(k) for k in ("profile_reason", "diag_roic_sbc_med5", "diag_sbc_pct_rev", "diag_roic_netcash_med5", "diag_nii_share_pretax",
                                                     "goodwill_pct", "interest_cover", "rev_cagr_long")}
        _AS_QUALITY["v4"] = v4_block
        step("quality_v4", "OK", scorer=v4_full.get("v"), q=v4_full.get("q_capped"), profile=v4_full.get("profile"), cov=v4_full.get("coverage_pct"), flags=",".join(v4_full.get("flags") or []) or "none")
    except Exception as v4_error:
        step("quality_v4", "FAIL", reason=type(v4_error).__name__ + ": " + str(v4_error)[:60])
    try:
        import as_moat
        if moat_source:
            moat_block = as_moat.parse_moat(moat_source)
            _AS_QUALITY["moat"] = moat_block
            step("quality_moat", "OK", rating=moat_block.get("rating"), tags=",".join(moat_block.get("advantages") or []) or "none", warnings=";".join(moat_block.get("warnings") or []) or "none")
    except Exception as moat_error:
        step("quality_moat", "FAIL", reason=type(moat_error).__name__ + ": " + str(moat_error)[:60])
    now_block = None
    if ttm_pages.get("income") or q_pages.get("income"):  # v45: cash flow is optional (only the FCF margin signal needs it); Quarterly view is the fallback
        try:
            import as_ttm_metrics
            now_block = as_ttm_metrics.compute_now(ttm_pages.get("income", ""), ttm_pages.get("cashflow", ""), ttm_pages.get("balance", ""),
                                                   profile=(v4_block or {}).get("profile") or "NF",
                                                   income_q_html=q_pages.get("income", ""), cashflow_q_html=q_pages.get("cashflow", ""))
            _AS_QUALITY["now"] = now_block
            step("quality_now", "OK", now=now_block.get("now"), signals=now_block.get("signals"), warnings=";".join(now_block.get("warnings") or []) or "none")
        except Exception as now_error:
            step("quality_now", "FAIL", reason=type(now_error).__name__ + ": " + str(now_error)[:60])
    else:
        step("quality_now", "FAIL", reason="income TTM view missing")
    step("quality", "OK", struct=result["partial_structural"], cov=result["coverage_pct"], flags=",".join(result["flags"]) or "none", roic_scale=diag.get("roic_scale"), roic_min5=(result["metrics"].get("roic_min5") if result.get("metrics") else None))


_AS_QM = {}
_RUN_START = time.monotonic()
_QM_LAST = {}   # v54: {'missing': [...]} of the last Quality Model payload


def _as_fin_open_page(sb, url, ready_pattern):
    """v47/v48: opens one AlphaSpread page and waits until ready_pattern shows in the page text; '' when it stays a Cloudflare page.
    v48: 3 attempts, each with a wait and a verification click when Cloudflare shows."""
    for attempt in (1, 2, 3):
        sb.uc_open_with_reconnect(url, 4)
        source = ""
        for tick in range(14):
            source = sb.get_page_source()
            if re.search(ready_pattern, re.sub(r"<[^>]+>", " ", source)):
                return source
            if "just a moment" in (sb.get_title() or "").lower() and tick >= 3:
                break
            sb.sleep(1.5)
        if "just a moment" in (sb.get_title() or "").lower():
            sb.sleep(20 * attempt)
            try:
                sb.uc_gui_click_captcha()
                sb.sleep(4.0)
            except Exception:
                pass
            continue
        return source
    return ""


# v66: PARTIAL Quality Model refresh. The sheet (fn_94_03 refresh plan -> fn_24_05 -> fn_24_73 input qm_only) lists the inputs that are missing in the
# stored Row JSON ("Shr chg,ROIC,..."); only the pages that can give them are read, the payload is posted with partial=True and the sheet
# (fn_91_11) keeps every stored value the payload does not carry.
QM_STATEMENT_LABELS = {"ROIC", "Op mgn", "FCF mgn", "Gross Margin", "Rev g", "ND/EBITDA", "Moat"}   # statement + profitability + moat pages (fetch_as_quality)
QM_EST_LABELS = {"Rev LT", "Rev est", "OpInc est", "Earn est"}                                      # analyst-estimates page + Wall St widget
QM_BUYBACK_LABELS = {"Shr chg"}                                                                       # buyback block (read in the ratio stage)


def qm_only_labels():
    """Labels from env QM_ONLY ('' = the whole Quality Model is read)."""
    return {part.strip() for part in os.environ.get("QM_ONLY", "").split(",") if part.strip()}


def qm_need(group):
    """True when the stage of this label group has to run: always without QM_ONLY, else only when one of its labels is missing."""
    only = qm_only_labels()
    return (not only) or bool(only & group)


def fetch_as_qm(sb, abbrev_as):
    """v48: Quality Model raw data (QM JSON): profitability checklist, analyst estimates, solvency + buyback / moat / TTM already read. Never raises.
    Env AS_FIN="0" (workflow input as_fin) skips it."""
    _AS_QM.clear()
    if os.environ.get("AS_FIN", "1") == "0":
        step("qm", "INFO", note="AS_FIN=0: Quality Model data not refreshed")
        return
    try:
        import as_qm_data
    except Exception as import_error:
        step("qm", "FAIL", reason="as_qm_data.py missing: " + type(import_error).__name__)
        return
    try:   # v48: the buyback block is blocked now and then -> one more try before the Quality Model is assembled
        if not (isinstance(_AS_RATIOS, dict) and _AS_RATIOS.get("buyback")):
            sb.sleep(15)
            fetch_as_buyback(sb, abbrev_as)
    except Exception:
        pass
    only = qm_only_labels()
    if only and not (only & (QM_STATEMENT_LABELS | QM_EST_LABELS)):
        # v66: only the buyback is missing: nothing else is opened, the value read in the ratio stage is posted alone
        bb = _AS_RATIOS.get("buyback") if isinstance(_AS_RATIOS, dict) else None
        if isinstance(bb, dict) and bb.get("now") is not None:
            _AS_QM.update({"v": 1, "fetched": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "flags": [], "partial": True,
                           "bb": _qm_bb(bb)})
            _QM_LAST["missing"] = []
            step("qm", "OK", partial="Shr chg only", bb=bb.get("now"), y3=bb.get("y3"), y5=bb.get("y5"), y10=bb.get("y10"))
        else:
            _QM_LAST["missing"] = ["Shr chg"]
            step("qm", "FAIL", reason="partial: buyback not read", partial="Shr chg only")
        return
    try:
        qm = as_qm_data.fetch_as_qm(sb, abbrev_as, step, _as_fin_open_page, prof_html=_QM_PROF.get("html"),
                                    buyback=(_AS_RATIOS.get("buyback") if isinstance(_AS_RATIOS, dict) else None),
                                    moat=(_AS_QUALITY.get("moat") or _QM_SRC.get("moat")),
                                    now_block=(_AS_QUALITY.get("now") or _QM_SRC.get("now")),
                                    wall=(dict(_QM_WALL) if _QM_WALL.get("visited") else None),
                                    roic_series=((((_AS_QUALITY.get("details") or {}).get("roic") or {}).get("raw")) or None),
                                    margin_series=(((_AS_QUALITY.get("details") or {}).get("margins")) or None))
        if qm and only and not (only & QM_STATEMENT_LABELS):
            # v66: partial run for analyst-estimate inputs: keep only what this run really read (prof / ttm / moat / fin of the stored JSON stay)
            qm = {k: qm[k] for k in ("v", "fetched", "flags", "est", "warnings") if k in qm}
            qm["partial"] = True
        if qm:
            if not qm.get("partial"):
                qm["fin"] = bool(((_AS_QUALITY.get("v4") or {}).get("profile")) == "FIN")   # v53: financials are not scored / excluded on ND/EBITDA
            try:
                _QM_LAST["missing"] = as_qm_data.qm_missing(qm)   # v54: drives the completion pass
                if only:   # v66: a partial run is judged only on the inputs it was asked for
                    _QM_LAST["missing"] = [m for m in _QM_LAST["missing"] if m in only or (m == "OpInc est" and "Earn est" in only)]
            except Exception:
                _QM_LAST["missing"] = []
            _AS_QM.update(qm)
            step("qm", "OK", prof=len(qm.get("prof") or {}), est=bool(qm.get("est")), moat=qm.get("moat"), bb=(qm.get("bb") or {}).get("cur"))
        else:
            step("qm", "FAIL", reason="nothing read")
    except Exception as qm_error:
        step("qm", "FAIL", reason=type(qm_error).__name__ + ": " + str(qm_error)[:60])


def qm_completion_passes(webhook_url, row_number, abbrev_as, sheet_name, info, headless):
    """v54: when the Quality Model payload of the main pass lacks inputs (blocked pages), run the missing parts again in a FRESH browser (a new
    browser often passes Cloudflare where the old one stays blocked) and post the result again; the sheet keeps what it already has.
    Env AS_QM_FILL_PASSES (default 2, 0 = off). Never raises."""
    try:
        passes = int(os.environ.get("AS_QM_FILL_PASSES", "2"))
    except ValueError:
        passes = 2
    if os.environ.get("AS_FIN", "1") == "0" or passes <= 0:
        return
    statement_inputs = {"ROIC", "Op mgn", "FCF mgn", "Gross Margin", "Rev g", "ND/EBITDA", "Moat"}
    # v64: the main pass did not produce any Quality Model payload (ORCL 2026-10-23: summary page blocked, quality + qm steps never ran,
    # the Row JSON stayed without QM data and "missing" was empty, so no completion pass started) -> everything counts as missing.
    if not _QM_LAST.get("missing") and not info.get("qm") and not _AS_QM:
        _QM_LAST["missing"] = sorted(qm_only_labels() or (statement_inputs | {"Shr chg"}))
        print("🧩 v64: no Quality Model data came from the main pass -- completion pass will read it in a fresh browser")
    for n in range(1, passes + 1):
        missing = list(_QM_LAST.get("missing") or [])
        if not missing:
            return
        if time.monotonic() - _RUN_START > int(os.environ.get("AS_QM_FILL_MAX_ELAPSED", "1020")):
            print("⏹️ QM completion pass skipped: run already took {:.0f}s".format(time.monotonic() - _RUN_START))
            return
        pause = random.uniform(20, 40)
        print("🔁 QM completion pass {}/{}: still missing {} -- fresh browser after {:.0f}s".format(n, passes, ",".join(missing), pause))
        time.sleep(pause)
        _QM_LAST["missing"] = []
        try:
            step_begin("ASDCF", 90 + n, "headless" if headless else "headed")
            _STEP_CTX["blocked"] = 0
            with SB(uc=True, headless=headless) as sb2:
                if statement_inputs & set(missing):
                    fetch_as_quality(sb2, abbrev_as)
                if "Shr chg" in missing and not (isinstance(_AS_RATIOS, dict) and _AS_RATIOS.get("buyback")):
                    fetch_as_buyback(sb2, abbrev_as)
                _QM_WALL.clear()
                fetch_as_qm(sb2, abbrev_as)
                post_as_qm_if_any(webhook_url, row_number, abbrev_as, sheet_name, info)
            step("qm_fill", "OK", pass_=n, missing_after=",".join(_QM_LAST.get("missing") or []) or "-")
        except BaseException as fill_error:
            print("⚠️ QM completion pass {} failed: {}".format(n, str(fill_error)[:100]))
            if isinstance(fill_error, KeyboardInterrupt):
                raise

def post_as_qm_if_any(webhook_url, row_number, abbrev, sheet_name, info):
    """v48: posts the Quality Model data once (target ASQM, fn_91_12); never touches the DCF result."""
    if not _AS_QM:
        return
    qm = dict(_AS_QM)
    _AS_QM.clear()
    saved_post = dict(_LAST_POST)
    try:
        posted = post_provider_json(webhook_url, "ASQM", row_number, abbrev, sheet_name, {"qm": qm})
        info["qm"] = {"posted": bool(posted), "reason": None if posted else _LAST_POST.get("reason")}
    except Exception as qm_post_error:
        print("❌ Quality Model post failed: {}".format(qm_post_error))
        info["qm"] = {"posted": False, "reason": str(qm_post_error)[:80]}
    finally:
        _LAST_POST.clear()
        _LAST_POST.update(saved_post)


def post_as_quality_if_any(webhook_url, row_number, abbrev, sheet_name, info):
    """Posts the computed quality metrics once (target ASQ); never touches the DCF result."""
    if not _AS_QUALITY:
        return
    quality = dict(_AS_QUALITY)
    _AS_QUALITY.clear()
    if os.environ.get("AS_POST_QUALITY_V4", "0") != "1":   # v59
        info["quality"] = {"posted": False, "struct": quality.get("partial_structural"), "cov": quality.get("coverage_pct"), "reason": "not sent (Quality v4 columns removed)"}
        return
    saved_post = dict(_LAST_POST)
    try:
        posted = post_provider_json(webhook_url, "ASQ", row_number, abbrev, sheet_name, {"quality": quality})
        info["quality"] = {"posted": bool(posted), "struct": quality.get("partial_structural"), "cov": quality.get("coverage_pct"),
                           "reason": None if posted else _LAST_POST.get("reason")}
    except Exception as quality_error:
        print("❌ AS quality post failed: {}".format(quality_error))
        info["quality"] = {"posted": False, "reason": str(quality_error)[:80]}
    finally:
        _LAST_POST.clear()
        _LAST_POST.update(saved_post)


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

    dcf_failed = False
    dcf_cf = False
    _FAST_BLOCK["on"] = False
    try:
        step("run_extractor", "INFO", abbrev=abbrev_as)
        data = as_dcf_extractor.scrape_as_dcf_data(sb, abbrev_as)
        step("extract_table", "OK", periods=len(data.get("periods") or []),
             sections=len(data.get("sections") or []))

    except Exception as error:
        if isinstance(error, getattr(as_dcf_extractor, "AsDcfCloudflare", ())):
            # v62: Cloudflare page on the DCF page itself -> end this attempt now; run_bot relaunches with a fresh browser
            dcf_cf = True
            step("as_dcf_cloudflare", "FAIL", reason="CLOUDFLARE_PAGE")
            _FAST_BLOCK["on"] = False
            raise CloudflareBlocked("AlphaSpread DCF page is still the Cloudflare page: {}".format(str(error)[:120]))
        dcf_failed = True
        _FAST_BLOCK["on"] = True   # v60
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

    finally:
        # v19: the DCF goes FIRST (AlphaSpread showed a login wall on the DCF
        # modal when 7 other pages had been opened before it). Ratios and
        # quality run afterwards, also when the DCF failed, so they are kept.
        # v46: when the DCF failed AND two following pages show the Cloudflare page, stop at once and let run_bot retry with a fresh browser
        # (the old run kept opening pages for 3-4 minutes, all blocked, and was never retried: Amazon, MercadoLibre 2026-10-19).
        def _stop_if_blocked():
            if dcf_failed and _STEP_CTX.get("blocked", 0) >= 1:   # v60: was 2
                raise CloudflareBlocked("AlphaSpread shows the Cloudflare page on {} steps after the DCF failed".format(_STEP_CTX.get("blocked", 0)))
        if os.environ.get("AS_RATIOS", "1") != "0" and not dcf_cf:
            fetch_as_ratios(sb, abbrev_as)
            _stop_if_blocked()
            fetch_as_buyback(sb, abbrev_as)
            _stop_if_blocked()
            if os.environ.get("AS_HIST", "1") != "0":
                fetch_as_hist(sb, abbrev_as)  # v30
                _stop_if_blocked()
                fetch_as_score_details(sb, abbrev_as)  # v39
        print("🧭 v64: stages after the DCF | ratios={} quality={} qm={} | blocked steps={} dcf_failed={} dcf_cf={}".format(
            os.environ.get("AS_RATIOS", "1") != "0", os.environ.get("AS_QUALITY", "1") != "0", os.environ.get("AS_FIN", "1") != "0",
            _STEP_CTX.get("blocked", 0), dcf_failed, dcf_cf))
        if os.environ.get("AS_QUALITY", "1") != "0" and not dcf_cf and qm_need(QM_STATEMENT_LABELS):   # v66: skipped when the partial list has no statement input
            _stop_if_blocked()
            fetch_as_quality(sb, abbrev_as)
        if os.environ.get("AS_FIN", "1") != "0" and not dcf_cf:   # v48: Quality Model raw data (QM JSON)
            _stop_if_blocked()
            fetch_as_qm(sb, abbrev_as)

    _FAST_BLOCK["on"] = False
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
POST_UNREADABLE_RETRIES = int(os.environ.get("POST_UNREADABLE_RETRIES", "5"))
POST_RETRY_PAUSE_SECONDS = 6
POST_LOCK_RETRY_PAUSE_SECONDS = 20  # v12: base pause after LOCK_TIMEOUT (plus jitter)


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
        # v12: a LOCK_TIMEOUT refusal (another row held the document lock for 60 s
        # while several rows ran at once) wrote nothing, so re-posting is safe.
        retryable = (reason == "reply_unreadable" or reason.startswith("post_failed")
                     or reason == "refused:LOCK_TIMEOUT")
        if posted or not retryable:
            if posted and post_try > 1:
                print("   (v10) confirmed on post try {}".format(post_try))
            return posted
        if post_try <= POST_UNREADABLE_RETRIES:
            print("🔁 Row {} {}: reply unreadable/POST failed ({}) -- re-posting the same payload in {} s (try {} of {})".format(
                row_number, target, reason, POST_RETRY_PAUSE_SECONDS, post_try + 1, POST_UNREADABLE_RETRIES + 1))
            if reason == "refused:LOCK_TIMEOUT":
                time.sleep(POST_LOCK_RETRY_PAUSE_SECONDS + random.uniform(0, 25))
            else:
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
    if _POST_FLAGS.get("skipRecalc") and target.upper() in ("MS", "SW", "SWP", "ASRP"):
        payload["skipRecalc"] = True
    elif target.upper() in (_POST_FLAGS.get("skipTargets") or ()):
        payload["skipRecalc"] = True  # v29: SW-only follow-up run -- the SW webhook recalculates once, the SWP page data only writes its cells
    if _POST_FLAGS.get("recalcOnly") and target.upper() == "ASRP":
        payload["recalcOnly"] = True

    label = "Row {} ({}) {}".format(row_number, abbrev, target)

    try:
        # v24: providers run in parallel processes, but their webhooks go one at a time (each handler holds the sheet's
        # document lock; overlapping posts caused LOCK_TIMEOUT refusals). The file lock is released when the reply is back.
        with open(POST_LOCK_PATH, "a") as post_lock_file:
            fcntl.flock(post_lock_file, fcntl.LOCK_EX)
            try:
                response = requests.post(
                    webhook_url, json=payload, timeout=WEBHOOK_TIMEOUT_SECONDS
                )
            finally:
                fcntl.flock(post_lock_file, fcntl.LOCK_UN)
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
            "v": "v47",
            "versions": module_versions(),
            "sheet": sheet_name,
            "row": row_number,
            "runId": os.environ.get("GITHUB_RUN_ID", ""),
            "startedUtc": run_started_utc,
            "secondsTotal": round(time.monotonic() - run_started),
            "providers": providers_out,
        }
        print("📋 RUN_SUMMARY " + json.dumps(summary, ensure_ascii=False, separators=(",", ":")))
        # v27: tell the workflow that SW was blocked on every attempt, so it can start a SW-only follow-up
        # run on a fresh runner (blocks come in clusters per runner address).
        sw_info = providers_out.get("SW")
        if sw_info is not None and sw_info.get("status") != "ok":
            with open("sw_retry.flag", "w") as flag_file:
                flag_file.write("blocked")
            print("🔁 SW did not succeed -> sw_retry.flag written (the workflow may start a SW-only follow-up run)")
    except Exception as summary_error:
        print("⚠️ could not build RUN_SUMMARY: {}".format(summary_error))


# ----------------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------------
def post_sw_skin_if_any(webhook_url, row_number, abbrev, sheet_name, info):
    """v43: posts the Skin score + note (target SKIN) for this row once."""
    if not _SW_SKIN:
        return
    result = dict(_SW_SKIN)
    _SW_SKIN.clear()
    saved_post = dict(_LAST_POST)
    try:
        data = {"score": result["score"], "note": result["note"], "parts": result["parts"], "inputs": result["inputs"]}
        posted = post_provider_json(webhook_url, "SKIN", row_number, abbrev, sheet_name, data)
        info["skin"] = {"posted": bool(posted), "score": result["score"], "reason": None if posted else _LAST_POST.get("reason")}
        step("post_skin", "OK" if posted else "FAIL", score=result["score"], reason=None if posted else _LAST_POST.get("reason"))
    except Exception as skin_error:
        print("❌ SW skin post failed: {}".format(skin_error))
        info["skin"] = {"posted": False, "reason": str(skin_error)[:80]}
    finally:
        _LAST_POST.clear()
        _LAST_POST.update(saved_post)


def post_sw_pages_if_any(webhook_url, row_number, abbrev, sheet_name, info):
    """v13: posts the collected SW pages (target SWP) once; never touches the SW JSON result."""
    post_sw_skin_if_any(webhook_url, row_number, abbrev, sheet_name, info)  # v43
    if not _SW_PAGES:
        return
    pages = dict(_SW_PAGES)
    _SW_PAGES.clear()
    saved_post = dict(_LAST_POST)
    try:
        posted = post_provider_json(webhook_url, "SWP", row_number, abbrev, sheet_name, {"pages": pages})
        info["pages"] = {"posted": bool(posted), "got": sorted(pages.keys()),
                         "reason": None if posted else _LAST_POST.get("reason"),
                         "column": _LAST_POST.get("column")}
    except Exception as pages_error:
        print("❌ SW pages post failed: {}".format(pages_error))
        info["pages"] = {"posted": False, "got": sorted(pages.keys()), "reason": str(pages_error)[:80]}
    finally:
        _LAST_POST.clear()
        _LAST_POST.update(saved_post)


def run_providers_in_parallel(providers, trace, webhook_url, row_number, sheet_name, run_started, run_started_utc):
    """
    v24: one child process per provider (same script, env ONLY_TARGET), each with its own browser, started a few
    seconds apart. Tabs in one browser would not help: a WebDriver runs one command at a time and background tabs are
    throttled, so the real gain is separate browsers. Webhook posts are serialised by POST_LOCK_PATH. Child output is
    streamed with a [TARGET] prefix; their traces are merged into one RUN_SUMMARY.
    """
    children = []
    ordered = [p for p in providers if p[1]]
    # slowest first: Simply Wall St, then AlphaSpread, then MarketScreener
    rank = {"SW": 0, "ASDCF": 1, "MS": 2, "GFP": 3}
    ordered.sort(key=lambda p: rank.get(p[0], 9))
    for target, abbrev, _ in providers:
        if not abbrev:
            print("⏩ Row {}: no abbreviation for {} -- skipping.".format(row_number, target))
            trace[target] = {"abbrev": "", "status": "skipped", "attempts": []}
    print("🧵 v24: running {} providers in parallel ({})".format(len(ordered), ", ".join(p[0] for p in ordered)))

    def pump(target, process):
        for line in process.stdout:
            print("[{}] {}".format(target, line.rstrip("\n")), flush=True)

    as_abbrev = next((p[1] for p in providers if p[0] == "ASDCF" and p[1]), "")
    single_recalc = SINGLE_RECALC and bool(as_abbrev)
    if single_recalc:
        print("🧮 v26: MS / SW handlers skip their own recalculation; one final recalculation follows the last provider.")

    for index, (target, abbrev, _) in enumerate(ordered):
        trace_path = os.path.join(tempfile.gettempdir(), "trace_{}_{}.json".format(target, os.getpid()))
        if os.path.exists(trace_path):
            os.remove(trace_path)
        child_env = dict(os.environ, ONLY_TARGET=target, TRACE_OUT=trace_path, PYTHONUNBUFFERED="1", GH_LOG_UPLOAD="0")  # the parent uploads the combined log once
        if single_recalc:
            child_env["SKIP_RECALC"] = "1"
        process = subprocess.Popen([sys.executable, os.path.abspath(__file__)], env=child_env,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        reader = threading.Thread(target=pump, args=(target, process), daemon=True)
        reader.start()
        children.append((target, abbrev, process, reader, trace_path))
        if index < len(ordered) - 1:
            time.sleep(PARALLEL_START_GAP_SECONDS)

    for target, abbrev, process, reader, trace_path in children:
        process.wait()
        reader.join(timeout=5)
        try:
            with open(trace_path) as trace_file:
                trace.update(json.load(trace_file))
        except Exception as trace_error:
            print("⚠️ {}: child ended without a trace ({}); exit code {}".format(target, trace_error, process.returncode))
            trace[target] = {"abbrev": abbrev, "status": "error", "attempts": [], "reason": "child_no_trace_rc{}".format(process.returncode)}

    if single_recalc and any((trace.get(t) or {}).get("status") in ("ok", "not_written") for t in ("MS", "SW", "ASDCF")):
        try:
            _POST_FLAGS["recalcOnly"] = True
            final_started = time.monotonic()
            with_lock_posted = post_provider_json(webhook_url, "ASRP", row_number, as_abbrev, sheet_name, {})
            trace["RECALC"] = {"abbrev": as_abbrev, "status": "ok" if with_lock_posted else "error", "attempts": [],
                               "seconds": round(time.monotonic() - final_started), "reason": None if with_lock_posted else _LAST_POST.get("reason")}
            print("🧮 v26: final single recalculation {} ({} s)".format("done" if with_lock_posted else "FAILED: {}".format(_LAST_POST.get("reason")),
                                                                      round(time.monotonic() - final_started)))
        except Exception as recalc_error:
            print("❌ v26: final recalculation failed: {}".format(recalc_error))
        finally:
            _POST_FLAGS.pop("recalcOnly", None)

    print_run_summary(trace, sheet_name, row_number, run_started, run_started_utc)
    print("🧹 Task complete!")


SCRIPT_VERSION = "provider_json_scraper v73"   # bump on every change to this file


def as_path(abbrev_as):
    """v72: AlphaSpread URL path of an abbreviation: a space becomes %20, exactly as AlphaSpread writes it (sto/lifco b -> sto/lifco%20b, sto/lagr b -> sto/lagr%20b);
    the v61 hyphen form (lifco-b, atco-a) gives a 404. The original abbreviation stays unchanged for posting. An abbreviation already written with %20 passes unchanged."""
    return re.sub(r"\s+", "%20", str(abbrev_as or "").strip().strip("/"))


def module_versions():
    """Version index of this script and the helper modules (each module has a VERSION constant); '?' when a module is missing."""
    out = [SCRIPT_VERSION]
    for name in ("as_dcf_extractor", "as_qm_data", "as_quality_metrics", "as_moat", "as_ttm_metrics"):
        try:
            mod = __import__(name)
            out.append(str(getattr(mod, "VERSION", name + " ?")))
        except Exception:
            out.append(name + " MISSING")
    return out


def run_bot():
    print("🤖 Booting up the provider-JSON scraper v26 (single-row mode)...")
    print("📦 VERSIONS | " + " | ".join(module_versions()))

    webhook_url = os.environ["GAS_WEBHOOK_URL"]
    row_number = int(os.environ["ROW_NUMBER"])
    sheet_name = os.environ["SHEET_NAME"]

    if os.environ.get("SKIP_RECALC") == "1":
        _POST_FLAGS["skipRecalc"] = True   # v26 (child process of a parallel run)
    elif os.environ.get("ONLY_TARGET", "").strip().upper() == "SW":
        _POST_FLAGS["skipTargets"] = ("SWP",)   # v29: SW-only follow-up run: one full recalculation (after SW), not two

    run_started = time.monotonic()
    run_started_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    trace = {}  # v7: per provider facts for the RUN_SUMMARY line

    # Every provider's abbreviation is OPTIONAL (default ''), exactly like
    # insider_score_scraper.py's abbrev_is / abbrev_as: a row may have any
    # subset of them, and an empty one just skips that provider.
    abbrev_sw = os.environ.get("ABBREV_SW", "").strip()
    abbrev_as = os.environ.get("ABBREV_AS", "").strip()  # v5
    abbrev_ms = os.environ.get("ABBREV_MS", "").strip()  # v11
    abbrev_gf = os.environ.get("ABBREV_GF", "").strip()  # v14

    print(
        "🎯 Sheet={} | Row={} | SW={} | AS={} | MS={} | GF={}".format(
            sheet_name, row_number, abbrev_sw or "(none)", abbrev_as or "(none)", abbrev_ms or "(none)", abbrev_gf or "(none)"
        )
    )

    # (target key, abbreviation, scrape function). Add GF here later.
    providers = [
        ("SW", abbrev_sw, scrape_sw_data),
        ("ASDCF", abbrev_as, scrape_as_dcf),
        ("MS", abbrev_ms, scrape_ms_data),
    ]
    if GF_ENABLED:
        providers.append(("GFP", abbrev_gf, scrape_gf_data))  # v14: trace/summary key GFP, webhook target GFP (v24: only when GF_ENABLED=1)
    elif abbrev_gf:
        print("⏩ GuruFocus is switched off (GF_ENABLED=0) -- ABBREV_GF ignored.")

    only_target = os.environ.get("ONLY_TARGET", "").strip()
    child_mode = bool(only_target)
    if child_mode:
        providers = [p for p in providers if p[0] == only_target]

    if not any(abbrev for _, abbrev, _ in providers):
        print(
            "⏩ Row {}: no provider abbreviation was provided --"
            " nothing to scrape this run.".format(row_number)
        )
        print_run_summary(trace, sheet_name, row_number, run_started, run_started_utc)
        return

    active = [p for p in providers if p[1]]
    if PARALLEL_PROVIDERS and not child_mode and len(active) > 1:
        run_providers_in_parallel(providers, trace, webhook_url, row_number, sheet_name, run_started, run_started_utc)
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
        if target == "SW":
            _SW_PAGES.clear()
        if target == "ASDCF":
            _AS_RATIOS.clear()
            _AS_QUALITY.clear()
            _AS_QM.clear()
        provider_clock = time.monotonic()

        # Each provider in its OWN try/except: one failing can never
        # block another from still being attempted and posted.
        try:
            attempts = max(1, int(os.environ.get("CF_RETRY_ATTEMPTS", DEFAULT_CF_RETRY_ATTEMPTS)))
        except ValueError:
            attempts = DEFAULT_CF_RETRY_ATTEMPTS
        if target == "SW":
            attempts = min(attempts, int(os.environ.get("SW_MAX_ATTEMPTS", "3")))  # v25: blocks come in clusters per runner address
        if target == "GFP":
            attempts = min(attempts, GF_MAX_ATTEMPTS)  # v15: GuruFocus blocks are rarely cleared by retrying

        provider_started = time.monotonic()

        for attempt in range(1, attempts + 1):
            if attempt > 1:
                pause = random.uniform(CF_RETRY_WAIT_MIN_SECONDS, CF_RETRY_WAIT_MAX_SECONDS)
                if target == "ASDCF":
                    pause = random.uniform(15, 30)   # v62: was 30-60 (v46); a fresh browser launch is what helps, not a long pause
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
                    use_cdp = (target == "SW" and SW_ENGINE == "cdp")  # v42
                    swallowed_error = []  # v44: the SB context manager can swallow an exception raised inside "with" (then "posted" was never set)
                    posted = None
                    with (SB(uc=True, test=True, locale="en") if use_cdp else SB(uc=True, headless=headless)) as sb:
                        try:
                            browser_ready = True
                            data = scrape(CdpSB(sb) if use_cdp else sb, abbrev, row_number, headless)
                            posted = post_provider_json(
                                webhook_url, target, row_number, abbrev, sheet_name, data
                            )
                            step("post_to_sheet", "OK" if posted else "FAIL",
                                 chars=_LAST_POST.get("chars"), column=_LAST_POST.get("column"),
                                 reason=_LAST_POST.get("reason"))
                            if target == "SW":
                                post_sw_pages_if_any(webhook_url, row_number, abbrev, sheet_name, info)
                            elif target == "ASDCF":
                                post_as_ratios_if_any(webhook_url, row_number, abbrev, sheet_name, info)
                                post_as_quality_if_any(webhook_url, row_number, abbrev, sheet_name, info)
                                post_as_qm_if_any(webhook_url, row_number, abbrev, sheet_name, info)
                        except BaseException as inner_error:
                            swallowed_error.append(inner_error)
                            raise
                    if swallowed_error and posted is None:
                        raise swallowed_error[0]
                    if target == "ASDCF":
                        qm_completion_passes(webhook_url, row_number, abbrev, sheet_name, info, headless)   # v54
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
                    if target == "SW":
                        post_sw_pages_if_any(webhook_url, row_number, abbrev, sheet_name, info)
                    elif target == "ASDCF":
                        post_as_ratios_if_any(webhook_url, row_number, abbrev, sheet_name, info)
                        post_as_quality_if_any(webhook_url, row_number, abbrev, sheet_name, info)
                        post_as_qm_if_any(webhook_url, row_number, abbrev, sheet_name, info)
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
                    if target == "SW":
                        post_sw_pages_if_any(webhook_url, row_number, abbrev, sheet_name, info)
                    elif target == "ASDCF":
                        post_as_ratios_if_any(webhook_url, row_number, abbrev, sheet_name, info)
                        post_as_quality_if_any(webhook_url, row_number, abbrev, sheet_name, info)
                        post_as_qm_if_any(webhook_url, row_number, abbrev, sheet_name, info)
                    if not browser_ready:
                        # The browser itself could not start (e.g. no display
                        # for headed mode) -- try the next mode.
                        continue
                    finished = True
                    break

            if finished:
                break

            if time.monotonic() - provider_started >= (CF_RETRY_BUDGET_SECONDS * 2 if target == "ASDCF" else CF_RETRY_BUDGET_SECONDS):
                print("⏹️ {}: retry time budget ({}s) used up -- giving up on this provider.".format(
                    target, CF_RETRY_BUDGET_SECONDS))
                break

        info["seconds"] = round(time.monotonic() - provider_clock)

    if child_mode and os.environ.get("TRACE_OUT"):
        with open(os.environ["TRACE_OUT"], "w") as trace_file:
            json.dump(trace, trace_file)
        return
    print_run_summary(trace, sheet_name, row_number, run_started, run_started_utc)
    print("🧹 Task complete!")


if __name__ == "__main__":
    run_bot()
