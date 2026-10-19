# as_strategy_test.py v2 (fix: Trend strategies crashed on unpacking) -- finds the most reliable way to read AlphaSpread "AS Profit", "AS Solv" and "Trend" inputs.
# For every AlphaSpread path (default: the first 3 Salkku stocks) it runs each STRATEGY below in a fresh page load and records
# success / seconds / attempts. Output: results_strategy.json, a ranking table in the log and in $GITHUB_STEP_SUMMARY,
# raw HTML of every failure under as_pages_strategy/ (so the failure can be studied).
#
# SCORES (Profitability + Solvency cards on <path>/summary)
#   S1_baseline    scroll in 600 px steps, up to 20 s            (the v44 behaviour)
#   S2_heading     S1 + scrollIntoView on the card heading       (v45 step 1)
#   S3_reload      S2, and if empty reload the page once         (v45)
#   S4_slowfull    slow full-page scroll down and up, 45 s
#   S5_events      scroll + mouse/scroll event dispatch + 10 s idle wait at the heading
#   S6_analysis    open the "View ... Analysis" pages and read the score there
# TREND (income statement TTM view -> as_ttm_metrics.compute_now)
#   T1_click1      one JS click, 10 x 1 s                        (v44)
#   T2_click3      up to 3 JS clicks, 12 s each                  (v45)
#   T3_real_click  Selenium click on the element after readyState + 3 s
#   T4_reload      reload, wait 4 s, then T2
#   T5_quarterly   Quarterly view of the income statement, TTM summed from 4 quarters (tested only for page access)
import json, os, re, sys, time
from seleniumbase import SB

try:
    import provider_json_scraper as P
    SCORES_JS, scores_clean = P._AS_SCORES_JS, P._as_scores_clean
except Exception as import_error:   # keep the test usable even if the scraper cannot be imported
    print("WARNING: provider_json_scraper not importable ({}); score strategies S1-S5 are skipped".format(type(import_error).__name__))
    SCORES_JS, scores_clean = None, None
import as_ttm_metrics as ttm

DEFAULT = "nyse/uber tsx/csu nyse/msci"
PATHS = [p.strip().strip("/") for p in re.split(r"[\s,]+", os.environ.get("AS_PATHS", "").strip() or DEFAULT) if p.strip()]
ONLY = [s.strip() for s in re.split(r"[\s,]+", os.environ.get("STRATEGIES", "").strip()) if s.strip()]
OUT = "as_pages_strategy"
os.makedirs(OUT, exist_ok=True)
TTM_RE = r"TTM\s+[A-Z][a-z]{2}\s+\d{4}"
CLICK_JS = ("var want = arguments[0], best = null;"
            "document.querySelectorAll('button, a, label, li, span, div').forEach(function (e) {"
            "  if (e.children.length === 0 && (e.textContent || '').trim() === want) { best = best || e; } });"
            "if (!best) { return 'none'; } best.scrollIntoView({block: 'center'}); best.click(); return 'clicked';")
HEADING_JS = ("var t = arguments[0], f = null;"
              "document.querySelectorAll('h1,h2,h3,h4,div,span').forEach(function (e) {"
              "  if (!f && e.children.length === 0 && (e.textContent || '').trim().slice(-t.length) === t) { f = e; } });"
              "if (f) { f.scrollIntoView({block: 'center'}); return true; } return false;")
results = []


def blocked(sb):
    return "just a moment" in (sb.get_title() or "").lower()


def open_page(sb, url):
    sb.uc_open_with_reconnect(url, 4)
    sb.sleep(2.0)
    return not blocked(sb)


def read_scores(sb):
    try:
        res = sb.execute_script(SCORES_JS) or {}
    except Exception:
        res = {}
    return scores_clean(res.get("profit")), scores_clean(res.get("solv")), res


def scroll_step(sb, state, step_px=600):
    try:
        height = int(sb.execute_script("return Math.round(document.body.scrollHeight || 0);") or 0)
        state["y"] = state.get("y", 0) + step_px
        if height and state["y"] > height:
            state["y"] = 0
        sb.execute_script("window.scrollTo(0, {});".format(state["y"]))
    except Exception:
        pass


def poll_scores(sb, seconds, heading_from=None, events=False, slow=False):
    """returns (profit, solv, rounds). heading_from = round number after which the card headings are scrolled into view."""
    deadline, rounds, state = time.time() + seconds, 0, {}
    profit = solv = None
    while time.time() < deadline:
        rounds += 1
        profit, solv, _ = read_scores(sb)
        if profit and solv:
            break
        if heading_from is not None and rounds >= heading_from:
            try:
                sb.execute_script(HEADING_JS, "Profitability Score" if rounds % 2 else "Solvency Score")
                sb.sleep(1.5)
            except Exception:
                pass
        if events:
            try:
                sb.execute_script("window.dispatchEvent(new Event('scroll')); window.dispatchEvent(new Event('resize'));"
                                  "document.dispatchEvent(new MouseEvent('mousemove', {clientX: 200, clientY: 300, bubbles: true}));")
            except Exception:
                pass
        scroll_step(sb, state, 300 if slow else 600)
        sb.sleep(2.0 if slow else 1.2)
    return profit, solv, rounds


def s1(sb, url):
    profit, solv, rounds = poll_scores(sb, 20)
    return profit, solv, {"rounds": rounds}


def s2(sb, url):
    profit, solv, rounds = poll_scores(sb, 20, heading_from=3)
    return profit, solv, {"rounds": rounds}


def s3(sb, url):
    profit, solv, rounds = poll_scores(sb, 20, heading_from=3)
    if profit or solv:
        return profit, solv, {"rounds": rounds, "reloaded": False}
    open_page(sb, url)
    profit, solv, rounds2 = poll_scores(sb, 20, heading_from=3)
    return profit, solv, {"rounds": rounds + rounds2, "reloaded": True}


def s4(sb, url):
    profit, solv, rounds = poll_scores(sb, 45, slow=True)
    return profit, solv, {"rounds": rounds}


def s5(sb, url):
    profit, solv, rounds = poll_scores(sb, 30, heading_from=2, events=True)
    if not (profit and solv):
        sb.sleep(10.0)
        profit, solv, _ = read_scores(sb)
    return profit, solv, {"rounds": rounds}


def s6(sb, url):
    """reads the score from the analysis pages linked by the cards (links are collected from the summary page)."""
    links = sb.execute_script("var o = {}; document.querySelectorAll('a[href]').forEach(function (a) {"
                              "var t = (a.textContent || '').trim();"
                              "if (/^View Profitability Analysis/i.test(t)) { o.profit = a.href; }"
                              "if (/^View Solvency Analysis/i.test(t)) { o.solv = a.href; } }); return o;") or {}
    found, info = {}, {"links": sorted(links.keys())}
    for kind, word in (("profit", "Profitability"), ("solv", "Solvency")):
        href = links.get(kind)
        if not href:
            continue
        try:
            open_page(sb, href)
            for _ in range(10):
                text = sb.execute_script("return document.body ? document.body.innerText : '';") or ""
                m = re.search(word + r"\s+Score[\s\S]{0,80}?\b(\d{1,3})\s*(?:/\s*100)?\b", text, re.I)
                if m and 0 <= int(m.group(1)) <= 100:
                    found[kind] = int(m.group(1))
                    break
                sb.sleep(1.5)
        except Exception as e:
            info[kind + "_err"] = type(e).__name__
    return ({"score": found["profit"]} if "profit" in found else None, {"score": found["solv"]} if "solv" in found else None, info)


SCORE_STRATEGIES = [("S1_baseline", s1), ("S2_heading", s2), ("S3_reload", s3), ("S4_slowfull", s4), ("S5_events", s5), ("S6_analysis", s6)]


def click_ttm(sb, attempts, wait_s, real=False):
    used = 0
    for used in range(1, attempts + 1):
        try:
            if real:
                sb.wait_for_ready_state_complete()
                sb.sleep(3.0)
                sb.click("//*[normalize-space(text())='TTM']", by="xpath", timeout=6)
            elif sb.execute_script(CLICK_JS, "TTM") != "clicked":
                sb.sleep(2.0)
                continue
        except Exception:
            sb.sleep(2.0)
            continue
        for _ in range(wait_s):
            sb.sleep(1.0)
            src = sb.get_page_source()
            if re.search(TTM_RE, re.sub(r"<[^>]+>", " ", src)):
                return src, used
    return "", used


def trend_from(income_html):
    now = ttm.compute_now(income_html, "", "")   # income TTM only: the v45 behaviour
    return now.get("now"), now


def t_run(sb, url, attempts, wait_s, real=False, reload_first=False):
    if reload_first:
        open_page(sb, url)
        sb.sleep(4.0)
    src, used = click_ttm(sb, attempts, wait_s, real)
    if not src:
        return None, {"attempts": used, "error": "header did not change"}
    value, now = trend_from(src)
    return value, {"attempts": used, "signals": sorted((now.get("signals") or {}).keys()), "warnings": (now.get("warnings") or [])[:2]}


def t1(sb, url): return t_run(sb, url, 1, 10)
def t2(sb, url): return t_run(sb, url, 3, 12)
def t3(sb, url): return t_run(sb, url, 2, 12, real=True)
def t4(sb, url): return t_run(sb, url, 3, 12, reload_first=True)


def t5(sb, url):
    """quarterly view of the income statement: counts how many quarter columns the page offers (4 needed for a self-made TTM)."""
    if sb.execute_script(CLICK_JS, "Quarterly") != "clicked":
        return None, {"error": "toggle not found"}
    for _ in range(12):
        sb.sleep(1.0)
        text = re.sub(r"<[^>]+>", " ", sb.get_page_source())
        quarters = set(re.findall(r"Q\d\s*FY\d{4}", text))
        if len(quarters) >= 4:
            return len(quarters), {"quarters": len(quarters)}
    return None, {"error": "no quarter header"}


TREND_STRATEGIES = [("T1_click1", t1), ("T2_click3", t2), ("T3_real_click", t3), ("T4_reload", t4), ("T5_quarterly", t5)]


def run(sb, path, name, fn, url):
    started = time.time()
    entry = {"path": path, "strategy": name, "ok": False, "sec": 0, "info": {}}
    try:
        if not open_page(sb, url):
            entry["info"] = {"error": "blocked (Cloudflare)"}
        else:
            if name.startswith("S"):
                a, b, info = fn(sb, url)
                entry["ok"] = bool(a and b)
                entry["partial"] = bool(a or b) and not entry["ok"]
                entry["profit"], entry["solv"] = (a or {}).get("score"), (b or {}).get("score")
            else:
                a, info = fn(sb, url)   # v2: trend strategies return (value, info) -- v1 unpacked 3 values and every T-run failed
                entry["ok"] = a is not None
                entry["value"] = a
            entry["info"] = info
    except Exception as e:
        entry["info"] = {"error": type(e).__name__ + ": " + str(e)[:80]}
    entry["sec"] = round(time.time() - started, 1)
    if not entry["ok"]:
        try:
            with open(os.path.join(OUT, "{}__{}.html".format(path.replace("/", "_"), name)), "w", encoding="utf-8") as h:
                h.write(sb.get_page_source()[:300000])
        except Exception:
            pass
    print("RESULT {:<14} {:<14} {} {:>5.1f}s {}".format(path, name, "OK  " if entry["ok"] else ("PART" if entry.get("partial") else "FAIL"),
                                                       entry["sec"], json.dumps(entry["info"], default=str)[:160]), flush=True)
    results.append(entry)


def wanted(name):
    if not ONLY:
        return name not in ("S4_slowfull", "S5_events")   # v2: both failed on every stock in the first run; ask for them by name to repeat
    return name in ONLY or name[0] in ONLY or name[:2] in ONLY


for path in PATHS:
    base = "https://www.alphaspread.com/security/{}/".format(path)
    try:
        with SB(uc=True, headless=False, locale_code="en", test=True) as sb:
            for name, fn in SCORE_STRATEGIES:
                if wanted(name) and (SCORES_JS or name == "S6_analysis"):
                    run(sb, path, name, fn, base + "summary")
            for name, fn in TREND_STRATEGIES:
                if wanted(name):
                    run(sb, path, name, fn, base + "financials/income-statement")
    except Exception as e:
        print("BROWSER ERROR", path, type(e).__name__, str(e)[:100], flush=True)
    json.dump(results, open("results_strategy.json", "w"), indent=1, default=str)

# ---- summary
names = [n for n, _ in SCORE_STRATEGIES + TREND_STRATEGIES if any(r["strategy"] == n for r in results)]
lines = ["| strategy | OK | of | rate | median s |", "|---|---|---|---|---|"]
for n in names:
    rs = [r for r in results if r["strategy"] == n]
    ok = sum(1 for r in rs if r["ok"])
    secs = sorted(r["sec"] for r in rs)
    lines.append("| {} | {} | {} | {:.0f}% | {} |".format(n, ok, len(rs), 100.0 * ok / len(rs), secs[len(secs) // 2]))
grid = ["", "| stock | " + " | ".join(n.split("_")[0] for n in names) + " |", "|---|" + "---|" * len(names)]
for path in PATHS:
    cells = []
    for n in names:
        r = next((x for x in results if x["path"] == path and x["strategy"] == n), None)
        cells.append("-" if r is None else ("ok" if r["ok"] else ("part" if r.get("partial") else "FAIL")))
    grid.append("| {} | {} |".format(path, " | ".join(cells)))
# stocks that no strategy could read are the interesting ones
for group, label in ((("S",), "AS Profit+Solv"), (("T",), "Trend")):
    dead = [p for p in PATHS if results and not any(r["ok"] for r in results if r["path"] == p and r["strategy"][0] in group)
            and any(r["path"] == p and r["strategy"][0] in group for r in results)]
    grid.append("\nNo strategy worked for {}: {}".format(label, ", ".join(dead) or "none"))
report = "\n".join(lines + grid)
print("\n===== STRATEGY RANKING =====\n" + report, flush=True)
summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
if summary_file:
    open(summary_file, "a").write("## AS strategy test\n" + report + "\n")
