"""
yahoo_abbrev_probe.py v5 (plain HTTP attempt capped at 6 s: in the last run every query went to the browser anyway, and the plain attempt cost most of the 38 s per query)
yahoo_abbrev_probe.py v4 (speed: 3 queries per stock (SW, AS, MS), 4 s between queries, 20 s retry pause; COMBINED=1 and GF=1 switch the old extras back on)
yahoo_abbrev_probe.py v3 (also writes entries_<stock>_<provider>.json: position/title/snippet/link as the Task 20 scorer needs)
yahoo_abbrev_probe.py v2 (v1 result: the first browser query returned results, the next ones HTTP 500 = Yahoo throttling;
v2 waits longer between queries, retries a 500 after a pause with a fresh browser session, and also tests ONE combined query per stock) -- READ-ONLY feasibility test: can Yahoo Search, opened from a GitHub Actions
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
DELAY = float(os.environ.get("DELAY", "4"))          # seconds between queries
RETRY_PAUSE = float(os.environ.get("RETRY_PAUSE", "20"))  # pause before a retry after an HTTP 500 / empty page
RETRIES = int(os.environ.get("RETRIES", "2"))


def is_error_page(page):
    low = (page or "")[:200000].lower()
    return ("http error 500" in low) or ("isn\u2019t working" in low) or ("isn't working" in low) or ("algo-sr" not in low and "no results" not in low)


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


def parse_entries(page):
    """Organic results as the Task 20 scorer (fn_20_14) expects them: position, title, snippet, link."""
    entries = []
    for pos, m in enumerate(re.finditer(
            r'<div class="dd [^"]*algo algo-sr[^"]*".*?(?=<div class="dd [^"]*algo algo-sr|</ol>)', page, re.S), start=1):
        blk = m.group(0)
        href = re.search(r'<a [^>]*href="(https?://[^"]+)"', blk)
        title = re.search(r'<h3[^>]*>(.*?)</h3>', blk, re.S)
        snip = re.search(r'<div class="compText[^"]*">(.*?)</div>', blk, re.S)
        clean = lambda t: re.sub(r"\s+", " ", htmlmod.unescape(re.sub(r"<[^>]+>", " ", t or ""))).strip()
        if href:
            entries.append({"position": pos, "entryType": "organic", "link": htmlmod.unescape(href.group(1)),
                            "title": clean(title.group(1) if title else ""),
                            "snippet": clean(snip.group(1) if snip else "")})
    return entries


def blocked(page):
    low = page[:4000].lower()
    return any(k in low for k in ("consent.yahoo", "unusual traffic", "captcha", "are you a robot", "access denied"))


def fetch_plain(url):
    try:
        r = requests.get(url, headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"}, timeout=float(os.environ.get("PLAIN_TIMEOUT", "6")))
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

    def start_browser():
        nonlocal sb_ctx, sb
        stop_browser()
        try:
            from seleniumbase import SB
            sb_ctx = SB(uc=True, headed=True, xvfb=True)
            sb = sb_ctx.__enter__()
        except Exception as err:  # noqa: BLE001
            sb_ctx, sb = None, None
            print("YAHOO_PROBE browser unavailable: {}".format(err))

    def stop_browser():
        nonlocal sb_ctx, sb
        if sb_ctx is not None:
            try:
                sb_ctx.__exit__(None, None, None)
            except Exception:  # noqa: BLE001
                pass
        sb_ctx, sb = None, None

    start_browser()

    def search(query):
        """plain HTTP first, then the browser; a 500 / empty page is retried after a pause with a fresh browser."""
        url = "https://search.yahoo.com/search?" + urllib.parse.urlencode({"p": query, "ei": "UTF-8"})
        status, page = fetch_plain(url)
        mode = "plain"
        if status == 200 and not blocked(page) and decode_links(page) and not is_error_page(page):
            return mode, status, page, 0
        mode = "browser"
        for attempt in range(RETRIES + 1):
            if sb is None:
                start_browser()
            if sb is not None:
                try:
                    page = fetch_browser(sb, url)
                except Exception as err:  # noqa: BLE001
                    page = "ERR {}".format(err)
                if not is_error_page(page):
                    return mode, status, page, attempt
            if attempt < RETRIES:
                time.sleep(RETRY_PAUSE)
                start_browser()
        return mode, status, page, RETRIES

    try:
        for company, ticker, country in stocks:
            queries = []
            if os.environ.get("COMBINED", "0") == "1":
                queries.append(("ALL", "{} {} (simplywall.st OR alphaspread.com OR marketscreener.com)".format(company, ticker).strip()))
            for key, domain, pattern in PROVIDERS:
                if key == "GF" and os.environ.get("GF", "0") != "1":
                    continue  # GuruFocus is switched off in the project
                queries.append((key, "site:{} {} {}".format(domain, company, ticker).strip()))
            for key, query in queries:
                t0 = time.monotonic()
                mode, status, page, retries = search(query)
                links = decode_links(page)
                entries = parse_entries(page)
                import json as _json
                open("{}/entries_{}_{}.json".format(OUT, re.sub(r"[^A-Za-z0-9_-]", "_", company)[:40], key), "w", encoding="utf-8").write(
                    _json.dumps(entries, ensure_ascii=False, indent=1))
                sec = round(time.monotonic() - t0, 1)
                safe = re.sub(r"[^A-Za-z0-9_-]", "_", "{}_{}".format(company, key))[:60]
                open("{}/yahoo_{}_{}.html".format(OUT, safe, mode), "w", encoding="utf-8").write(page)
                found = {}
                for pkey, domain, pattern in PROVIDERS:
                    if key not in ("ALL", pkey):
                        continue
                    abbrevs = []
                    for u in links:
                        mm = pattern.search(u)
                        if mm and mm.group(1) not in abbrevs:
                            abbrevs.append(mm.group(1))
                    found[pkey] = abbrevs[:MAX_RESULTS]
                print("YAHOO_PROBE {} | {} | {} | mode={} http={} retries={} {}s | links={} | entries={} | error_page={} | abbrevs={}{}".format(
                    company, ticker or "-", key, mode, status, retries, sec, len(links), len(entries), is_error_page(page), found,
                    " | BLOCKED" if blocked(page) else ""), flush=True)
                time.sleep(DELAY)
    finally:
        stop_browser()
    return 0


if __name__ == "__main__":
    sys.exit(main())
