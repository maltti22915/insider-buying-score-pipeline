"""
abbrev_search.py v1 -- Yahoo Search for Task 20 (stock abbreviation finder), run from GitHub Actions.
Replaces the Scrape.do/Google search. Started by Apps Script (fn_20_21) through workflow abbrev_search.yml.

INPUT (env)
  REQUEST_ID      id made by fn_20_21; the answer is stored by the webhook under ABBRS_<id>
  QUERIES         JSON list: [{"id": "...", "query": "site:simplywall.st Meta Platforms Inc META", "site": "..."}]
  GAS_WEBHOOK_URL the Apps Script Web App URL (secret, same one the other scrapers use)
  DELAY (4 s between queries), RETRY_PAUSE (20), RETRIES (2), PLAIN_TIMEOUT (6)

For every query: plain HTTP first (fast), else a real browser (SeleniumBase uc); a Yahoo HTTP 500 / empty page is
retried after a pause with a fresh browser. Queries run strictly one after another (Yahoo throttles bursts).
OUTPUT: ONE POST {target:'ABBRS', requestId, runSeconds, results:[{id, query, mode, seconds, retried, error,
entries:[{position,title,snippet,link}]}]} -> fn_91_09 (script cache) -> fn_20_21 builds the packets.
LOG: gh_log_uploader (imported first) sends every printed line to the main Drive log; lines start with ABBREV_SEARCH.
"""
import gh_log_uploader  # noqa: F401  (must stay first: copies stdout/stderr to the main log file)

import html as htmlmod
import json
import os
import re
import sys
import time
import urllib.parse

import requests

OUT = "diagnostics"
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0.0.0 Safari/537.36")
DELAY = float(os.environ.get("DELAY", "4"))
RETRY_PAUSE = float(os.environ.get("RETRY_PAUSE", "20"))
RETRIES = int(os.environ.get("RETRIES", "2"))
MAX_ENTRIES = 8


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
            link = htmlmod.unescape(href.group(1))
            ru = re.search(r"/RU=(https?%3a[^/]+)", link, re.I)  # plain-HTTP pages wrap links in a Yahoo redirect
            if ru:
                link = urllib.parse.unquote(ru.group(1))
            entries.append({"position": pos, "entryType": "organic", "link": link,
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


def post_answer(payload):
    url = os.environ.get("GAS_WEBHOOK_URL", "")
    if not url:
        print("ABBREV_SEARCH 🚨 GAS_WEBHOOK_URL missing -- cannot deliver the answer", flush=True)
        return False
    for attempt in range(1, 4):
        try:
            r = requests.post(url, json=payload, timeout=60)
            print("ABBREV_SEARCH 📤 answer posted | attempt={} http={} reply={}".format(attempt, r.status_code, r.text[:200].replace("\n", " ")), flush=True)
            if r.status_code == 200 and '"ok":true' in r.text.replace(" ", ""):
                return True
        except Exception as err:  # noqa: BLE001
            print("ABBREV_SEARCH ⚠️ post attempt {} failed: {}".format(attempt, err), flush=True)
        time.sleep(3)
    return False


def main():
    t_start = time.monotonic()
    request_id = os.environ.get("REQUEST_ID", "").strip()
    try:
        jobs = json.loads(os.environ.get("QUERIES", "[]"))
    except Exception as err:  # noqa: BLE001
        print("ABBREV_SEARCH 🚨 QUERIES is not valid JSON: {}".format(err), flush=True)
        return 1
    if not request_id or not jobs:
        print("ABBREV_SEARCH 🚨 REQUEST_ID or QUERIES missing", flush=True)
        return 1
    os.makedirs(OUT, exist_ok=True)
    print("ABBREV_SEARCH 🚀 START | request={} | queries={} | delay={}s".format(request_id, len(jobs), DELAY), flush=True)

    sb_ctx = None
    sb = None

    def stop_browser():
        nonlocal sb_ctx, sb
        if sb_ctx is not None:
            try:
                sb_ctx.__exit__(None, None, None)
            except Exception:  # noqa: BLE001
                pass
        sb_ctx, sb = None, None

    def start_browser():
        nonlocal sb_ctx, sb
        stop_browser()
        try:
            from seleniumbase import SB
            sb_ctx = SB(uc=True, headed=True, xvfb=True)
            sb = sb_ctx.__enter__()
        except Exception as err:  # noqa: BLE001
            sb_ctx, sb = None, None
            print("ABBREV_SEARCH ⚠️ browser unavailable: {}".format(err), flush=True)

    def search(query):
        url = "https://search.yahoo.com/search?" + urllib.parse.urlencode({"p": query, "ei": "UTF-8"})
        status, page = fetch_plain(url)
        if status == 200 and not blocked(page) and decode_links(page) and not is_error_page(page):
            return "plain", page, 0
        for attempt in range(RETRIES + 1):
            if sb is None:
                start_browser()
            if sb is not None:
                try:
                    page = fetch_browser(sb, url)
                except Exception as err:  # noqa: BLE001
                    page = "ERR {}".format(err)
                if not is_error_page(page):
                    return "browser", page, attempt
            if attempt < RETRIES:
                print("ABBREV_SEARCH ↻ retry {} after Yahoo error page | pause {}s".format(attempt + 1, RETRY_PAUSE), flush=True)
                time.sleep(RETRY_PAUSE)
                start_browser()
        return "browser", page, RETRIES

    results = []
    try:
        for i, job in enumerate(jobs):
            qid, query = str(job.get("id")), str(job.get("query", ""))
            t0 = time.monotonic()
            res = {"id": qid, "query": query, "mode": "", "seconds": 0, "retried": False, "error": "", "entries": []}
            try:
                mode, page, retries = search(query)
                entries = parse_entries(page)
                res.update(mode=mode, retried=retries > 0, entries=entries[:MAX_ENTRIES])
                if not entries:
                    res["error"] = "YAHOO_ERROR_PAGE" if is_error_page(page) else ""
                safe = re.sub(r"[^A-Za-z0-9_-]", "_", qid)[:40]
                open("{}/yahoo_{}_{}.html".format(OUT, safe, mode), "w", encoding="utf-8").write(page)
            except Exception as err:  # noqa: BLE001
                res["error"] = "EXC {}".format(str(err)[:150])
            res["seconds"] = round(time.monotonic() - t0, 1)
            results.append(res)
            top = res["entries"][0]["link"] if res["entries"] else "-"
            print("ABBREV_SEARCH 🔎 {}/{} | id={} | mode={} | {}s | entries={} | retried={} | error={} | top={} | query={}".format(
                i + 1, len(jobs), qid, res["mode"], res["seconds"], len(res["entries"]), res["retried"], res["error"] or "NONE", top, query), flush=True)
            if i < len(jobs) - 1:
                time.sleep(DELAY)
    finally:
        stop_browser()

    run_seconds = round(time.monotonic() - t_start, 1)
    ok = post_answer({"target": "ABBRS", "requestId": request_id, "runSeconds": run_seconds, "results": results})
    print("ABBREV_SEARCH {} DONE | request={} | seconds={} | queries={} | with_results={} | delivered={}".format(
        "✅" if ok else "🚨", request_id, run_seconds, len(results), sum(1 for r in results if r["entries"]), ok), flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
