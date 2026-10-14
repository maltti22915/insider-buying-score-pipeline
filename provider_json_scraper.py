# ============================================================================
# provider_json_scraper.yml
# ============================================================================
# Runs provider_json_scraper.py for exactly ONE sheet row at a time,
# triggered on demand via GitHub's own workflow_dispatch API -- called from
# Apps Script's fn_24_73_TriggerProviderJsonRefresh_StockData_60, which
# fn_24_05 fires AFTER a row's own main refresh has written its data.
#
# Deliberately a SEPARATE workflow from insider_score_scraper.yml
# (Insider Buying Score + AlphaSpread), so this new functionality can be
# tested on its own and can never affect that already-working chain.
#
# VERSION 9: SW_MAX_ATTEMPTS = 2 in the normal run, 3 in the SW-only follow-up run (a fresh runner is a better second chance than a third try on the same blocked address).
#
# VERSION 8: inputs only_target / retry_left and a last step: when SW was blocked on every attempt (sw_retry.flag from provider_json_scraper.py v27)
# a SW-only follow-up run is started after 90 s on a fresh runner (up to retry_left times, default 2). Needs permissions actions: write.
#
# VERSION 7: new optional input as_quality ("1" = read the AlphaSpread statement pages, "0" = skip them); env AS_QUALITY for provider_json_scraper.py v18. Sent by fn_24_73 v5.
#
# VERSION 6: env SCRAPE_DO_TOKEN from the repository secret SCRAPE_DO_TOKEN (GuruFocus pages are fetched through Scrape.do, provider_json_scraper.py v16).
#
# VERSION 5: new optional input abbrev_gf (GuruFocus) and env ABBREV_GF for provider_json_scraper.py v14/v15.
#
# VERSION 4: new optional input abbrev_ms (MarketScreener) and env ABBREV_MS for
# provider_json_scraper.py v11. Nothing else changed.
#
# VERSION 3: job timeout raised from 10 to 20 minutes, because provider_json_scraper.py
# v6 retries a Cloudflare-blocked provider (up to 3 attempts, about 330 s budget each).
# Nothing else changed.
#
# VERSION 2: second provider, AlphaSpread DCF. New optional input abbrev_as
# (e.g. "nasdaq/adsk") and one env line ABBREV_AS. as_dcf_extractor.py must be
# at the repository root next to provider_json_scraper.py. No new secret and
# no new dependency (the extractor uses only the Python standard library).
#
# VERSION 1 (NEW WORK): first version. Providers are optional inputs, one
# per provider -- today only abbrev_sw (Simply Wall St). A future abbrev_gf
# (GuruFocus) is added here as one more optional input, plus one env line.
#
# Save this file as .github/workflows/provider_json_scraper.yml in the
# SAME repository as insider_score_scraper.yml, and provider_json_scraper.py
# at the repository root next to insider_score_scraper.py. The existing
# requirements.txt (seleniumbase, requests) is reused as-is.
#
# REQUIRED REPOSITORY SECRETS (Settings -> Secrets and variables -> Actions):
#   GAS_WEBHOOK_URL  -- the SAME, already-existing Web App URL the Insider
#                       Buying Score / AlphaSpread scraper uses. An Apps
#                       Script project has exactly one doPost, so this
#                       provider JSON path shares that URL and is routed to
#                       fn_91_01 by the payload's own "target" field
#                       (SW / GF). No new secret is needed.
#
# Diagnostics: the dialog's own HTML and a screenshot are written to
# ./diagnostics on every run (see SAVE_DIAGNOSTICS_ALWAYS in the script) and
# uploaded below as a run artifact, retained 3 days.
# ============================================================================

name: Provider JSON Scraper

permissions:
  contents: read
  actions: write

"on":
  workflow_dispatch:
    inputs:
      row_number:
        description: 'The specific row on the target sheet this run is for'
        required: true
        type: string
      sheet_name:
        description: 'The real sheet this row lives on (e.g. "Salkku", "Watch")'
        required: true
        type: string
      abbrev_sw:
        description: "OPTIONAL: that row's own current Simply Wall St abbreviation (e.g. \"de/consumer-durables/etr-ads/adidas-shares\"). Leave blank to skip the SW scrape entirely."
        required: false
        type: string
        default: ''
      abbrev_as:
        description: "OPTIONAL: that row's own current AlphaSpread abbreviation (e.g. \"nasdaq/adsk\"). Leave empty to skip the AlphaSpread DCF."
        required: false
        type: string
        default: ''
      abbrev_ms:
        description: "OPTIONAL: that row's own current MarketScreener abbreviation (e.g. \"CONSTELLATION-SOFTWARE-IN-1409607\"). Leave empty to skip MarketScreener."
        required: false
        type: string
        default: ''
      abbrev_gf:
        description: "OPTIONAL: that row's own current GuruFocus abbreviation (e.g. \"NAS:ADSK\" or \"XAMS:PRX\"). Leave empty to skip GuruFocus."
        required: false
        type: string
        default: ''
      as_quality:
        description: "1 = read the AlphaSpread statement pages for the quality metrics, 0 = skip them"
        required: false
        default: "1"
        type: string
      parallel:
        description: "1 = providers run side by side (fast), 0 = one after the other (old behaviour; use it to test whether a block is caused by the parallel run)"
        required: false
        default: "1"
        type: string

      only_target:
        description: "OPTIONAL: run only this provider (SW). Used by the automatic SW follow-up run."
        required: false
        default: ''
        type: string
      retry_left:
        description: "How many SW-only follow-up runs may still be started if SW is blocked"
        required: false
        default: "2"
        type: string

jobs:
  scrape-provider-json:
    runs-on: ubuntu-latest
    timeout-minutes: 20

    steps:
      - name: Check out repository
        uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'
          cache: 'pip'
          cache-dependency-path: requirements.txt

      - name: Install dependencies
        run: |
          pip install -r requirements.txt

      - name: Run the scraper
        env:
          GAS_WEBHOOK_URL: ${{ secrets.GAS_WEBHOOK_URL }}
          ROW_NUMBER: ${{ inputs.row_number }}
          SHEET_NAME: ${{ inputs.sheet_name }}
          ABBREV_SW: ${{ inputs.abbrev_sw }}
          ABBREV_AS: ${{ inputs.abbrev_as }}
          ABBREV_MS: ${{ inputs.abbrev_ms }}
          ABBREV_GF: ${{ inputs.abbrev_gf }}
          AS_QUALITY: ${{ inputs.as_quality }}
          PARALLEL: ${{ inputs.parallel || '1' }}
          ONLY_TARGET: ${{ inputs.only_target }}
          SW_MAX_ATTEMPTS: ${{ inputs.only_target == 'SW' && '3' || '2' }}
          SCRAPE_DO_TOKEN: ${{ secrets.SCRAPE_DO_TOKEN }}
        run: python provider_json_scraper.py

      - name: Upload diagnostics
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: provider-json-diagnostics-row${{ inputs.row_number }}-${{ github.run_id }}
          path: diagnostics/
          if-no-files-found: ignore
          retention-days: 3

      - name: Start a SW-only follow-up run when SW was blocked
        if: always() && hashFiles('sw_retry.flag') != '' && inputs.retry_left != '0' && inputs.abbrev_sw != ''
        env:
          GH_TOKEN: ${{ github.token }}
          RETRY_LEFT: ${{ inputs.retry_left || '2' }}
        run: |
          sleep 90
          NEXT=$((RETRY_LEFT - 1))
          gh workflow run provider_json_scraper.yml \
            -f row_number="${{ inputs.row_number }}" \
            -f sheet_name="${{ inputs.sheet_name }}" \
            -f abbrev_sw="${{ inputs.abbrev_sw }}" \
            -f only_target=SW \
            -f as_quality=0 \
            -f retry_left="$NEXT"
