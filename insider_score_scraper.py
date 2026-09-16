"""
============================================================================
insider_score_scraper.py
============================================================================

PURPOSE
----------------------------------------------------------------------------
Runs on a schedule (GitHub Actions), reads the StockData_60 spreadsheet's
own Column D metadata directly (via the Sheets API, read-only) to find
every row's own "abbrevIS" value, uses SeleniumBase's uc
("undetected-chromedriver") mode to fetch each row's own real
InsiderScreener company page, and POSTs the resulting raw HTML to a
Google Apps Script webhook (fn_90_01_InsiderScoreWebhook_StockData_60),
which scores it using that project's own already-built, already-verified
"Insider Buying Score" logic.

WHY THIS EXISTS
----------------------------------------------------------------------------
Every fetch approach reachable from Google Apps Script itself (Scrape.do's
own render+super, a targeted wait/networkidle2 variant, a direct no-proxy
request, and ZenRows' own dedicated antibot=true engine) consistently
failed InsiderScreener's own real Cloudflare challenge-platform
protection. Apps Script's own UrlFetchApp has no real browser capability
at all, and neither Scrape.do's nor ZenRows' own remote browser instances
passed this specific site's own fingerprint check either.

SeleniumBase's uc mode runs a genuinely patched Chromium instance built
specifically to defeat this exact class of detection (canvas, audio
context, font rendering, and related fingerprinting) -- confirmed
directly against the person's own already-working example project
scraping this same site's own /en/explore/{country} pages. This script
reuses that same, already-proven technique, pointed instead at the
specific company pages (/en/company/{slug}) the existing "Insider Buying
Score" scoring logic actually needs (individual transaction dates,
roles, and planned-vs-real status) -- a different page shape than the
broad daily "explore" feed the original example scraped, but the exact
same underlying bypass capability.

WHAT THIS SCRIPT DOES NOT DO
----------------------------------------------------------------------------
- Does not compute the score itself. The webhook it posts to reuses this
  project's own existing fn_22_30 parsing/scoring logic directly, so the
  role-weighting/planned-discount/recency-window design lives in exactly
  one place, not duplicated in two languages.
- Does not write anything to the spreadsheet directly. All writes happen
  through the webhook, which also re-verifies the row's own abbrevIS has
  not changed since this script read it, before writing anything.
- Does not use a Service Account to upload/store any file via the Drive
  API. This script only ever READS existing sheet values (Sheets API,
  spreadsheets.readonly scope) -- a completely different API and scope
  from the Drive API's own file-upload quota restriction that an earlier,
  unrelated example project in this same family of scripts ran into. That
  restriction does not apply here at all.

REQUIRED GITHUB ACTIONS SECRETS
----------------------------------------------------------------------------
GAS_WEBHOOK_URL       -- this project's own deployed
                         fn_90_01_InsiderScoreWebhook_StockData_60 Web App
                         URL (kept secret, same convention as any other
                         webhook URL in this family of scripts).
GOOGLE_SERVICE_ACCOUNT_JSON
                       -- the full JSON key of a Google Cloud Service
                         Account, with the target spreadsheet shared to
                         that service account's own email address as at
                         least "Viewer". Read-only access is all this
                         script ever needs.
SPREADSHEET_ID        -- the StockData_60 spreadsheet's own ID (the long
                         string in its own URL, between /d/ and /edit).

REQUIRED PYTHON PACKAGES (requirements.txt)
----------------------------------------------------------------------------
seleniumbase
requests
google-auth
google-api-python-client

CONFIGURATION CONSTANTS
----------------------------------------------------------------------------
See the top of run_bot() below for SHEET_NAME, HEADER_ROW, and
METADATA_COLUMN -- these match this project's own already-established,
real, confirmed layout conventions.

VERSION
----------------------------------------------------------------------------
v1 -- Requested directly, new work, IS (InsiderScreener) fetch
  reliability. First version -- reads every configured company's own
  abbrevIS from the sheet directly, scrapes each one's own real company
  page with SeleniumBase's uc mode, and posts the resulting HTML to the
  new webhook for scoring.
============================================================================
"""

import json
import os
import time

import requests
from google.oauth2 import service_account
from googleapiclient.discovery import build
from seleniumbase import SB


# ----------------------------------------------------------------------------
# CONFIGURATION
# ----------------------------------------------------------------------------
SHEET_NAME = "Salkku"
HEADER_ROW = 4
FIRST_DATA_ROW = HEADER_ROW + 1
METADATA_COLUMN_LETTER = "D"

# Polite delay between company page fetches, to avoid hammering
# InsiderScreener's own servers across many companies in one run.
DELAY_BETWEEN_REQUESTS_SECONDS = 3

# Real Cloudflare-protected challenges can take a genuine few seconds to
# resolve even inside a real, patched browser -- confirmed necessary
# directly, since this project's own earlier Apps Script-side experiments
# (a Scrape.do-based customWait=8000/waitUntil=networkidle2 variant)
# already established that this specific challenge needs real time to
# settle, not just a real browser.
PAGE_LOAD_SETTLE_SECONDS = 6


def get_configured_companies(spreadsheet_id, sheet_name):
    """
    Reads every data row's own Column D metadata cell directly via the
    Sheets API (read-only), parses each one's own JSON, and returns a
    list of {row_number, abbrev_is} for every row where abbrevIS is a
    real, non-null value.

    A blank spacer row (this project's own real, established layout
    interleaves blank rows between data rows) simply has no parseable
    JSON in Column D, so it is silently skipped here -- not treated as
    an error, matching this whole project's own established "skip
    isolated gaps, do not stop at them" convention.
    """
    credentials_json = os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]
    credentials_info = json.loads(credentials_json)

    credentials = service_account.Credentials.from_service_account_info(
        credentials_info,
        scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"],
    )

    sheets_service = build("sheets", "v4", credentials=credentials)

    range_notation = "{}!{}{}:{}".format(
        sheet_name,
        METADATA_COLUMN_LETTER,
        FIRST_DATA_ROW,
        METADATA_COLUMN_LETTER,
    )

    result = (
        sheets_service.spreadsheets()
        .values()
        .get(spreadsheetId=spreadsheet_id, range=range_notation)
        .execute()
    )

    raw_rows = result.get("values", [])

    companies = []

    for offset, row in enumerate(raw_rows):
        row_number = FIRST_DATA_ROW + offset

        if not row or not row[0]:
            # Blank spacer row, or a row with no Column D content at all.
            continue

        raw_metadata_text = row[0]

        try:
            metadata = json.loads(raw_metadata_text)
        except (ValueError, TypeError):
            print(
                "⚠️  Row {}: Column D did not parse as JSON, skipping.".format(
                    row_number
                )
            )
            continue

        abbrev_is = metadata.get("abbrevIS")

        if not abbrev_is:
            continue

        companies.append(
            {
                "row_number": row_number,
                "abbrev_is": abbrev_is,
            }
        )

    return companies


def scrape_company_html(sb, abbrev_is):
    """
    Fetches the real, complete HTML of one company's own InsiderScreener
    page, using SeleniumBase's own already-open uc-mode browser session
    (reusing one browser across every company in this run, rather than
    launching a fresh one per company, for speed).
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


def post_to_webhook(webhook_url, row_number, abbrev_is, html):
    """
    Posts one company's own scraped HTML to the Apps Script webhook,
    which re-verifies the row still matches and writes the computed
    score, using this project's own existing fn_22_30 scoring logic.
    """
    payload = {
        "sheetName": SHEET_NAME,
        "rowNumber": row_number,
        "abbrevIS": abbrev_is,
        "html": html,
    }

    try:
        response = requests.post(webhook_url, json=payload, timeout=30)
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
    elif response_body.get("ok"):
        print(
            "⏩ Row {} ({}): webhook accepted but did not write ({})".format(
                row_number, abbrev_is, response_body.get("reason")
            )
        )
    else:
        print(
            "❌ Row {} ({}): webhook refused/failed ({})".format(
                row_number, abbrev_is, response_body.get("reason")
            )
        )


def run_bot():
    print("🤖 Booting up the Insider Buying Score scraper...")

    webhook_url = os.environ["GAS_WEBHOOK_URL"]
    spreadsheet_id = os.environ["SPREADSHEET_ID"]

    print("📖 Reading configured companies from the spreadsheet...")
    companies = get_configured_companies(spreadsheet_id, SHEET_NAME)

    print(
        "📊 Found {} row(s) with a real abbrevIS configured.".format(
            len(companies)
        )
    )

    if not companies:
        print("🤷 Nothing to scrape. Task complete!")
        return

    with SB(uc=True, headless=True) as sb:
        for index, company in enumerate(companies):
            row_number = company["row_number"]
            abbrev_is = company["abbrev_is"]

            print(
                "\n[{}/{}] Row {}: {}".format(
                    index + 1, len(companies), row_number, abbrev_is
                )
            )

            try:
                html = scrape_company_html(sb, abbrev_is)

            except Exception as scrape_error:
                print(
                    "❌ Row {} ({}): scrape itself failed: {}".format(
                        row_number, abbrev_is, scrape_error
                    )
                )
                continue

            post_to_webhook(webhook_url, row_number, abbrev_is, html)

            if index < len(companies) - 1:
                time.sleep(DELAY_BETWEEN_REQUESTS_SECONDS)

    print("\n🧹 Task complete!")


if __name__ == "__main__":
    run_bot()
