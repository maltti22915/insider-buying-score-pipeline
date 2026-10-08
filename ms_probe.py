"""
ms_probe.py v1 -- READ-ONLY feasibility probe: can a GitHub Actions browser load
MarketScreener (MS) pages that ScrapeDO fetches today? Posts NOTHING to the sheet.
For each abbreviation in ABBREV_MS (comma separated, e.g. "TELE2-AB-13247047") it opens
https://www.marketscreener.com/quote/stock/<abbrev>/ in a real headed browser,
waits up to WAIT_SECONDS for any challenge to clear, prints a one-line verdict
(title, html size, challenge markers, price/consensus markers) and saves the HTML
and a screenshot to ./diagnostics for the workflow artifact.
"""
import os, re, sys, time
from seleniumbase import SB

WAIT_SECONDS = int(os.environ.get("WAIT_SECONDS", "25"))
ATTEMPTS = int(os.environ.get("ATTEMPTS", "2"))
OUT = "diagnostics"
CHALLENGE = ("just a moment", "attention required", "access denied", "verify you are human", "captcha", "datadome")
MARKERS = ("Last Close", "Consensus", "Target price", "Mean consensus", "Number of analysts", "Capitalization", "P/E ratio")


def probe(sb, abbrev, attempt):
    url = "https://www.marketscreener.com/quote/stock/{}/".format(abbrev)
    t0 = time.monotonic()
    sb.uc_open_with_reconnect(url, reconnect_time=6)
    title, html = "", ""
    cleared = False
    while time.monotonic() - t0 < WAIT_SECONDS:
        title = (sb.get_title() or "")
        html = sb.get_page_source() or ""
        low = (title + " " + html[:3000]).lower()
        if not any(c in low for c in CHALLENGE) and len(html) > 30000:
            cleared = True
            break
        time.sleep(1)
    sec = round(time.monotonic() - t0, 1)
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))
    found = [m for m in MARKERS if m.lower() in text.lower()]
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", abbrev)
    os.makedirs(OUT, exist_ok=True)
    open("{}/ms_{}_a{}.html".format(OUT, safe, attempt), "w", encoding="utf-8").write(html)
    try:
        sb.save_screenshot("ms_{}_a{}.png".format(safe, attempt), folder=OUT)
    except Exception:
        pass
    print("MS_PROBE {} a{} | cleared={} | {}s | title={!r} | html={} chars | text={} chars | markers={}".format(
        abbrev, attempt, cleared, sec, title[:80], len(html), len(text), found))
    return cleared


def main():
    abbrevs = [a.strip() for a in os.environ.get("ABBREV_MS", "").split(",") if a.strip()]
    if not abbrevs:
        print("ABBREV_MS is empty"); sys.exit(1)
    passed = 0
    for abbrev in abbrevs:
        ok = False
        for attempt in range(1, ATTEMPTS + 1):
            try:
                with SB(uc=True, headless=False) as sb:
                    ok = probe(sb, abbrev, attempt)
            except Exception as e:
                print("MS_PROBE {} a{} | ERROR {}: {}".format(abbrev, attempt, type(e).__name__, str(e)[:200]))
            if ok:
                break
            time.sleep(8)
        passed += 1 if ok else 0
    print("MS_PROBE_SUMMARY {}/{} loaded".format(passed, len(abbrevs)))


if __name__ == "__main__":
    main()
