"""
sw_probe.py v1 -- READ-ONLY experiment: which browser behaviour gets past the Simply Wall St
Cloudflare challenge most often? Posts NOTHING to the sheet.

Runs ATTEMPTS_PER_VARIANT fresh headed browsers for each variant, in round-robin order (A B C D E A B ...) so that
every variant sees the same runner address and the same time of day. Prints one line per attempt and a summary table.

Variants
  A baseline        open with reconnect 6 s, click the challenge checkbox every 12 s   (what provider_json_scraper does)
  B early_click     open with reconnect 6 s, click at once and every 5 s
  C long_reconnect  open with reconnect 12 s, click every 12 s
  D warmup_home     open https://simplywall.st/ first, wait, then the stock page; click every 12 s
  E no_click        open with reconnect 6 s, never click, just wait

Env: ABBREV_SW (e.g. us/software/nasdaq-adsk/autodesk), ATTEMPTS_PER_VARIANT (default 8), WAIT_SECONDS (default 20),
     VARIANTS (default "A,B,C,D,E").
"""
import json, os, random, sys, time
from seleniumbase import SB

ABBREV = os.environ.get("ABBREV_SW", "").strip().strip("/")
PER_VARIANT = int(os.environ.get("ATTEMPTS_PER_VARIANT", "8"))
WAIT = int(os.environ.get("WAIT_SECONDS", "20"))
VARIANTS = [v.strip().upper() for v in os.environ.get("VARIANTS", "A,B,C,D,E").split(",") if v.strip()]
OUT = "diagnostics"

NAMES = {"A": "baseline", "B": "early_click", "C": "long_reconnect", "D": "warmup_home", "E": "no_click"}


def is_challenge(sb):
    try:
        title = (sb.get_title() or "").lower()
        url = (sb.get_current_url() or "").lower()
        body = (sb.execute_script("return String(document.body ? document.body.innerText : '').slice(0, 600);") or "").lower()
    except Exception:
        return True
    return ("just a moment" in title or "/challenge" in url or "verify you are human" in body
            or "checking your browser" in body or "just a moment" in body)


def wait_clear(sb, click_first, click_every, do_click):
    """Returns (cleared, seconds, clicks)."""
    t0 = time.monotonic()
    clicks, last = 0, None
    if not is_challenge(sb):
        return True, 0.0, 0
    while time.monotonic() - t0 < WAIT:
        time.sleep(1 if click_first else 2)
        if not is_challenge(sb):
            return True, round(time.monotonic() - t0, 1), clicks
        if do_click:
            now = time.monotonic()
            if last is None or now - last >= click_every:
                last = now
                try:
                    sb.uc_gui_click_captcha()
                    clicks += 1
                except Exception:
                    pass
    return (not is_challenge(sb)), round(time.monotonic() - t0, 1), clicks


def run_attempt(variant):
    url = "https://simplywall.st/stocks/{}/valuation".format(ABBREV)
    with SB(uc=True, headless=False) as sb:
        if variant == "D":
            sb.uc_open_with_reconnect("https://simplywall.st/", reconnect_time=6)
            wait_clear(sb, False, 12, True)
            time.sleep(random.uniform(3, 6))
        reconnect = 12 if variant == "C" else 6
        sb.uc_open_with_reconnect(url, reconnect_time=reconnect)
        time.sleep(2)
        click_first = variant == "B"
        click_every = 5 if variant == "B" else 12
        do_click = variant != "E"
        if click_first and is_challenge(sb) and do_click:
            pass  # wait_clear clicks straight away on its first loop (last is None)
        cleared, sec, clicks = wait_clear(sb, click_first, click_every, do_click)
        html_len = 0
        title = ""
        if cleared:
            time.sleep(2)
            html_len = len(sb.get_page_source() or "")
            title = (sb.get_title() or "")[:60]
            cleared = html_len > 50000 and not is_challenge(sb)
        return cleared, sec, clicks, html_len, title


def main():
    if not ABBREV:
        print("ABBREV_SW is empty"); sys.exit(1)
    os.makedirs(OUT, exist_ok=True)
    stats = {v: {"n": 0, "ok": 0, "clear_secs": []} for v in VARIANTS}
    for rnd in range(1, PER_VARIANT + 1):
        for v in VARIANTS:
            t0 = time.monotonic()
            try:
                ok, sec, clicks, html_len, title = run_attempt(v)
                err = ""
            except Exception as e:
                ok, sec, clicks, html_len, title, err = False, 0, 0, 0, "", "{}: {}".format(type(e).__name__, str(e)[:120])
            st = stats[v]
            st["n"] += 1
            st["ok"] += 1 if ok else 0
            if ok and sec:
                st["clear_secs"].append(sec)
            print("SW_PROBE round={} variant={} ({}) | pass={} | clear={}s | clicks={} | html={} | title={!r} | total={}s {}".format(
                rnd, v, NAMES[v], ok, sec, clicks, html_len, title, round(time.monotonic() - t0), err))
            time.sleep(random.uniform(4, 10))
    lines = ["| variant | name | passed | rate | typical clear time |", "|---|---|---|---|---|"]
    for v in VARIANTS:
        st = stats[v]
        secs = sorted(st["clear_secs"])
        med = secs[len(secs) // 2] if secs else None
        lines.append("| {} | {} | {}/{} | {}% | {} |".format(
            v, NAMES[v], st["ok"], st["n"], round(100 * st["ok"] / max(1, st["n"])), "{} s".format(med) if med else "-"))
    table = "\n".join(lines)
    print("SW_PROBE_SUMMARY\n" + table)
    print("SW_PROBE_JSON " + json.dumps(stats))
    summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_file:
        with open(summary_file, "a", encoding="utf-8") as fh:
            fh.write("## SW Cloudflare probe: {}\n\n{}\n".format(ABBREV, table))


if __name__ == "__main__":
    main()
