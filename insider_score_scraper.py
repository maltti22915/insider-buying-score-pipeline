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
row_number  -- the specific row on the "Salkku" sheet this run is for.
abbrev_is   -- that row's own current InsiderScreener company slug.

REQUIRED PYTHON PACKAGES (requirements.txt)
----------------------------------------------------------------------------
seleniumbase
requests

VERSION
----------------------------------------------------------------------------
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

import os

import requests
from seleniumbase import SB


# ----------------------------------------------------------------------------
# CONFIGURATION
# ----------------------------------------------------------------------------
SHEET_NAME = "Salkku"

# Real Cloudflare-protected challenges can take a genuine few seconds to
# resolve even inside a real, patched browser -- confirmed necessary
# directly, since this project's own earlier Apps Script-side experiments
# (a Scrape.do-based customWait=8000/waitUntil=networkidle2 variant)
# already established that this specific challenge needs real time to
# settle, not just a real browser.
PAGE_LOAD_SETTLE_SECONDS = 6


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


def post_to_webhook(webhook_url, row_number, abbrev_is, html):
    """
    Posts this company's own scraped HTML to the Apps Script webhook,
    which re-verifies the row still matches and writes the computed
    score, using this project's own existing fn_22_30 scoring logic.

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
        "sheetName": SHEET_NAME,
        "rowNumber": row_number,
        "abbrevIS": abbrev_is,
        "html": html,
    }

    try:
        response = requests.post(webhook_url, json=payload, timeout=120)
        response_body = response.json()

    except Exception as post_error:
        print(
            "❌ Row {} ({}): webhook POST itself failed: {}".format(
                row_number, abbrev_is, post_error
            )
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


def run_bot():
    print("🤖 Booting up the Insider Buying Score scraper (single-row mode)...")

    webhook_url = os.environ["GAS_WEBHOOK_URL"]
    row_number = int(os.environ["ROW_NUMBER"])
    abbrev_is = os.environ["ABBREV_IS"]

    print("🎯 Row {}: {}".format(row_number, abbrev_is))

    with SB(uc=True, headless=True) as sb:
        try:
            html = scrape_company_html(sb, abbrev_is)

        except Exception as scrape_error:
            print(
                "❌ Row {} ({}): scrape itself failed: {}".format(
                    row_number, abbrev_is, scrape_error
                )
            )
            return

        post_to_webhook(webhook_url, row_number, abbrev_is, html)

    print("🧹 Task complete!")


if __name__ == "__main__":
    run_bot()
