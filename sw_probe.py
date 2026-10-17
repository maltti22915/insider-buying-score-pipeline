"""
sw_probe.py v2 -- READ-ONLY experiment: which GitHub-runner strategy gets the Simply Wall St valuation page past Cloudflare
most often? Posts NOTHING to the sheet. Variants run round-robin (A F G ... A F G ...), so every strategy sees the same runner
address and the same time of day. One line per attempt, a summary table, and a JSON line with the UTC hour (for time-of-day).

Variants (browser = real Chrome on the runner; http = no browser)
  A uc_baseline    SeleniumBase uc, headed (xvfb), reconnect 6 s, click the checkbox every 12 s   (= provider_json_scraper today)
  F cdp_solve      SeleniumBase CDP mode (pure CDP, no webdriver), sb.cdp.solve_captcha() every 8 s
  G cdp_gui        SeleniumBase CDP mode, sb.cdp.gui_click_captcha() every 8 s
  H uc_headless    SeleniumBase uc, headless, reconnect 6 s, click every 12 s
  I http_chrome    curl_cffi, Chrome TLS impersonation, plain GET of the page (no browser)
  J http_warm      curl_cffi, home page first (cookies kept), then the page
  K cdp_long       CDP mode with a 45 s window (does a long wait ever pay?)
  S scrape_do      Scrape.do API (needs env SCRAPEDO_TOKEN; render + super/residential). Checks only that the page arrives, not the dialog.

A pass = the valuation page HTML arrives (more than 50 000 characters, no "Just a moment" challenge). It does not click the "Data"
button, so it measures the Cloudflare gate only.

Env: ABBREV_SW, ATTEMPTS_PER_VARIANT (default 6), WAIT_SECONDS (default 25), VARIANTS (default "A,F,G,H,I,J,K"; add S with a token),
     SCRAPEDO_TOKEN (optional).
"""
import json, os, random, sys, time, datetime

ABBREV = os.environ.get("ABBREV_SW", "").strip().strip("/")
PER_VARIANT = int(os.environ.get("ATTEMPTS_PER_VARIANT", "6"))
WAIT = int(os.environ.get("WAIT_SECONDS", "25"))
VARIANTS = [v.strip().upper() for v in os.environ.get("VARIANTS", "A,F,G,H,I,J,K").split(",") if v.strip()]
SCRAPEDO_TOKEN = os.environ.get("SCRAPEDO_TOKEN", "").strip()
MIN_HTML = 50000
OUT = "diagnostics"
NAMES = {"A": "uc_baseline", "F": "cdp_solve", "G": "cdp_gui", "H": "uc_headless", "I": "http_chrome",
         "J": "http_warm", "K": "cdp_long", "S": "scrape_do"}
HTTP_VARIANTS = ("I", "J", "S")


def page_url():
    return "https://simplywall.st/stocks/{}/valuation".format(ABBREV)


def text_is_challenge(title, url, body):
    t, u, b = (title or "").lower(), (url or "").lower(), (body or "").lower()
    return ("just a moment" in t or "/challenge" in u or "verify you are human" in b
            or "checking your browser" in b or "just a moment" in b or "attention required" in t)


# ---------------------------------------------------------------- browser (webdriver) variants
def wd_is_challenge(sb):
    try:
        title = sb.get_title() or ""
        url = sb.get_current_url() or ""
        body = sb.execute_script("return String(document.body ? document.body.innerText : '').slice(0, 600);") or ""
    except Exception:
        return True
    return text_is_challenge(title, url, body)


def wd_wait_clear(sb, click_every, window):
    t0 = time.monotonic()
    clicks, last = 0, None
    if not wd_is_challenge(sb):
        return True, 0.0, 0
    while time.monotonic() - t0 < window:
        time.sleep(2)
        if not wd_is_challenge(sb):
            return True, round(time.monotonic() - t0, 1), clicks
        now = time.monotonic()
        if last is None or now - last >= click_every:
            last = now
            try:
                sb.uc_gui_click_captcha()
                clicks += 1
            except Exception:
                pass
    return (not wd_is_challenge(sb)), round(time.monotonic() - t0, 1), clicks


def run_uc(headless):
    from seleniumbase import SB
    with SB(uc=True, headless=headless) as sb:
        sb.uc_open_with_reconnect(page_url(), reconnect_time=6)
        time.sleep(2)
        cleared, sec, clicks = wd_wait_clear(sb, 12, WAIT)
        html_len, status = 0, ""
        if cleared:
            time.sleep(2)
            html = sb.get_page_source() or ""
            html_len = len(html)
            cleared = html_len > MIN_HTML and not wd_is_challenge(sb)
            status = (sb.get_title() or "")[:50]
        return cleared, sec, clicks, html_len, status


# ---------------------------------------------------------------- CDP mode variants
def cdp_is_challenge(sb):
    try:
        title = sb.cdp.get_title() or ""
        url = sb.cdp.get_current_url() or ""
        body = sb.cdp.evaluate("String(document.body ? document.body.innerText : '').slice(0, 600)") or ""
    except Exception:
        return True
    return text_is_challenge(title, url, body)


def run_cdp(mode, window):
    from seleniumbase import SB
    with SB(uc=True, test=True, locale="en") as sb:
        sb.activate_cdp_mode(page_url())
        time.sleep(3)
        t0 = time.monotonic()
        clicks, last = 0, None
        cleared = not cdp_is_challenge(sb)
        sec = 0.0
        while not cleared and time.monotonic() - t0 < window:
            time.sleep(2)
            if not cdp_is_challenge(sb):
                cleared = True
                break
            now = time.monotonic()
            if last is None or now - last >= 8:
                last = now
                try:
                    if mode == "solve":
                        sb.cdp.solve_captcha()
                    else:
                        sb.cdp.gui_click_captcha()
                    clicks += 1
                except Exception:
                    pass
        sec = round(time.monotonic() - t0, 1) if clicks or not cleared else 0.0
        html_len, status = 0, ""
        if cleared:
            time.sleep(2)
            html = sb.cdp.get_page_source() or ""
            html_len = len(html)
            cleared = html_len > MIN_HTML and not cdp_is_challenge(sb)
            status = (sb.cdp.get_title() or "")[:50]
        return cleared, sec, clicks, html_len, status


# ---------------------------------------------------------------- http variants
def http_ok(resp_text, status):
    low = (resp_text or "")[:3000].lower()
    return status == 200 and len(resp_text or "") > MIN_HTML and "just a moment" not in low and "attention required" not in low


def run_http(warm):
    from curl_cffi import requests as cr
    session = cr.Session(impersonate="chrome")
    if warm:
        session.get("https://simplywall.st/", timeout=30)
        time.sleep(random.uniform(2, 5))
    r = session.get(page_url(), timeout=45)
    return http_ok(r.text, r.status_code), 0.0, 0, len(r.text or ""), "HTTP {}".format(r.status_code)


def run_scrapedo():
    import urllib.parse, urllib.request
    if not SCRAPEDO_TOKEN:
        raise RuntimeError("SCRAPEDO_TOKEN not set")
    api = "https://api.scrape.do/?token={}&url={}&super=true&render=true&geoCode=us".format(
        urllib.parse.quote(SCRAPEDO_TOKEN), urllib.parse.quote(page_url(), safe=""))
    try:
        with urllib.request.urlopen(api, timeout=120) as resp:
            body = resp.read().decode("utf-8", "ignore")
            status = resp.status
    except Exception as e:
        code = getattr(e, "code", "")
        raise RuntimeError("scrape.do {} {}".format(code, str(e)[:80]))
    return http_ok(body, status), 0.0, 0, len(body), "HTTP {}".format(status)


def run_attempt(v):
    if v == "A":
        return run_uc(False)
    if v == "H":
        return run_uc(True)
    if v == "F":
        return run_cdp("solve", WAIT)
    if v == "G":
        return run_cdp("gui", WAIT)
    if v == "K":
        return run_cdp("solve", 45)
    if v == "I":
        return run_http(False)
    if v == "J":
        return run_http(True)
    if v == "S":
        return run_scrapedo()
    raise RuntimeError("unknown variant " + v)


def main():
    if not ABBREV:
        print("ABBREV_SW is empty"); sys.exit(1)
    os.makedirs(OUT, exist_ok=True)
    started = datetime.datetime.utcnow()
    stats = {v: {"n": 0, "ok": 0, "errors": 0, "clear_secs": []} for v in VARIANTS}
    for rnd in range(1, PER_VARIANT + 1):
        for v in VARIANTS:
            t0 = time.monotonic()
            err = ""
            try:
                ok, sec, clicks, html_len, info = run_attempt(v)
            except Exception as e:
                ok, sec, clicks, html_len, info = False, 0, 0, 0, ""
                err = "{}: {}".format(type(e).__name__, str(e)[:140])
            st = stats[v]
            st["n"] += 1
            st["ok"] += 1 if ok else 0
            st["errors"] += 1 if err else 0
            if ok and sec:
                st["clear_secs"].append(sec)
            print("SW_PROBE round={} variant={} ({}) | pass={} | clear={}s | clicks={} | html={} | {!r} | total={}s {}".format(
                rnd, v, NAMES.get(v, v), ok, sec, clicks, html_len, info, round(time.monotonic() - t0), err), flush=True)
            time.sleep(random.uniform(3, 8))
    lines = ["| variant | name | passed | rate | typical clear time | errors |", "|---|---|---|---|---|---|"]
    for v in VARIANTS:
        st = stats[v]
        secs = sorted(st["clear_secs"])
        med = secs[len(secs) // 2] if secs else None
        lines.append("| {} | {} | {}/{} | {}% | {} | {} |".format(
            v, NAMES.get(v, v), st["ok"], st["n"], round(100 * st["ok"] / max(1, st["n"])),
            "{} s".format(med) if med else "-", st["errors"]))
    table = "\n".join(lines)
    stamp = "{} UTC (hour {:02d})".format(started.strftime("%Y-%m-%d %H:%M"), started.hour)
    print("SW_PROBE_SUMMARY {}\n{}".format(stamp, table))
    print("SW_PROBE_JSON " + json.dumps({"startedUtc": started.isoformat() + "Z", "hourUtc": started.hour, "abbrev": ABBREV, "stats": stats}))
    summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_file:
        with open(summary_file, "a", encoding="utf-8") as fh:
            fh.write("## SW probe v2: {} -- started {}\n\n{}\n".format(ABBREV, stamp, table))


if __name__ == "__main__":
    main()
