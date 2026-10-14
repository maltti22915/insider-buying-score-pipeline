"""
yahoo_abbrev_probe.py v1 -- READ-ONLY feasibility test: can Yahoo Search, opened from a GitHub Actions
runner, replace the Google/Scrape.do search that finds the stock abbreviations (Task 20)?
Posts NOTHING to the sheet.

INPUT (env QUERIES): one stock per line, "Company name | Ticker | country" (ticker/country optional), e.g.
    Meta Platforms Inc | META | us
    flatexDEGIRO AG | FTK | de
For every stock and every provider below it opens
    https://search.yahoo.com/search?p=site:<domain> <company> <ticker>
(first with plain HTTP, then -- if that is blocked or has no results -- in a real browser), reads the result
links (Yahoo's r.search.yahoo.com redirect links are decoded) and prints, per provider, the first results and
the abbreviation each URL would give:
    SW  simplywall.st/stocks/<cc>/<industry>/<exchange-ticker>/<name>  -> "us/media/nasdaq-meta/meta-platforms"
    AS  alphaspread.com/security/<exchange>/<ticker>                  -> "nasdaq/meta"
    MS  marketscreener.com/quote/stock/<NAME-ID>/                      -> "META-PLATFORMS-INC-10547141"
    GF  gurufocus.com/stock/<TICKER>/summary                           -> "META" (exchange prefix is not in the URL)
One summary line per stock/provider starts with  YAHOO_PROBE  (grep it). HTML and screenshots go to ./diagnostics.
"""
import html as htmlmod
import os
import re
import sys
import time
import urllib.parse

import requests

OUT = "diagnostics"
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0.0.0 Safari/537.36")
PROVIDERS = [
    ("SW", "simplywall.st",
     re.compile(r"https?://(?:www\.)?simplywall\.st/stocks/([a-z]{2}/[a-z0-9-]+/[a-z0-9.-]+/[a-z0-9.-]+)", re.I)),
    ("AS", "alphaspread.com",
     re.compile(r"https?://(?:www\.)?alphaspread\.com/security/([a-z0-9.-]+/[a-z0-9.-]+)", re.I)),
    ("MS", "marketscreener.com",
     re.compile(r"https?://(?:www\.)?marketscreener\.com/quote/stock/([A-Z0-9-]+-\d+)", re.I)),
    ("GF", "gurufocus.com",
     re.compile(r"https?://(?:www\.)?gurufocus\.com/stock/([A-Za-z0-9.:-]+)", re.I)),
]
MAX_RESULTS = 5


def decode_links(page):
    """All result URLs of a Yahoo result page, redirect links decoded, order kept, no duplicates."""
    urls = []
    text = htmlmod.unescape(page)
    for m in re.finditer(r"/RU=(https?%3a[^/\"'&\s]+)", text, re.I):
        urls.append(urllib.parse.unquote(m.group(1)))
    for m in re.finditer(r"href=\"(https?://[^\"]+)\"", text, re.I):
        u = m.group(1)
        if "yahoo.com" not in u:
            urls.append(u)
    seen, out = set(), []
    for u in urls:
        key = u.split("?")[0].rstrip("/")
        if key not in seen:
            seen.add(key)
            out.append(u)
    return out


def blocked(page):
    low = page[:4000].lower()
    return any(k in low for k in ("consent.yahoo", "unusual traffic", "captcha", "are you a robot", "access denied"))


def fetch_plain(url):
    try:
        r = requests.get(url, headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"}, timeout=25)
        return r.status_code, r.text
    except Exception as err:  # noqa: BLE001
        return 0, "ERR {}".format(err)


def fetch_browser(sb, url):
    sb.uc_open_with_reconnect(url, reconnect_time=4)
    if "consent.yahoo" in (sb.get_current_url() or ""):
        for sel in ("button[name='agree']", "button.accept-all", "button[value='agree']"):
            try:
                sb.click(sel, timeout=5)
                time.sleep(3)
                break
            except Exception:  # noqa: BLE001
                continue
    time.sleep(2)
    return sb.get_page_source() or ""


def main():
    stocks = []
    for line in os.environ.get("QUERIES", "").splitlines():
        parts = [p.strip() for p in line.split("|")]
        if parts and parts[0]:
            stocks.append((parts[0], parts[1] if len(parts) > 1 else "", parts[2] if len(parts) > 2 else ""))
    if not stocks:
        print("YAHOO_PROBE no QUERIES given")
        return 1
    os.makedirs(OUT, exist_ok=True)

    sb_ctx = None
    sb = None
    try:
        from seleniumbase import SB
        sb_ctx = SB(uc=True, headed=True, xvfb=True)
        sb = sb_ctx.__enter__()
    except Exception as err:  # noqa: BLE001
        print("YAHOO_PROBE browser unavailable: {}".format(err))

    try:
        for company, ticker, country in stocks:
            for key, domain, pattern in PROVIDERS:
                query = "site:{} {} {}".format(domain, company, ticker).strip()
                url = "https://search.yahoo.com/search?" + urllib.parse.urlencode({"p": query, "ei": "UTF-8"})
                t0 = time.monotonic()
                mode, status, page = "plain", 0, ""
                status, page = fetch_plain(url)
                links = decode_links(page) if status == 200 and not blocked(page) else []
                hits = [u for u in links if pattern.search(u)]
                if not hits and sb is not None:
                    mode = "browser"
                    try:
                        page = fetch_browser(sb, url)
                        links = decode_links(page)
                        hits = [u for u in links if pattern.search(u)]
                    except Exception as err:  # noqa: BLE001
                        page = "ERR {}".format(err)
                sec = round(time.monotonic() - t0, 1)
                safe = re.sub(r"[^A-Za-z0-9_-]", "_", "{}_{}".format(company, key))[:60]
                open("{}/yahoo_{}_{}.html".format(OUT, safe, mode), "w", encoding="utf-8").write(page)
                abbrevs = []
                for u in hits:
                    a = pattern.search(u).group(1)
                    if a not in abbrevs:
                        abbrevs.append(a)
                print("YAHOO_PROBE {} | {} | {} | mode={} http={} {}s | results={} | provider hits={} | abbrevs={}{}".format(
                    company, ticker or "-", key, mode, status, sec, len(links), len(hits), abbrevs[:MAX_RESULTS],
                    " | BLOCKED" if blocked(page) else ""))
                time.sleep(2)
    finally:
        if sb_ctx is not None:
            try:
                sb_ctx.__exit__(None, None, None)
            except Exception:  # noqa: BLE001
                pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
