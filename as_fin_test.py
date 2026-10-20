# as_fin_test.py v2 (millions check on the table only) -- finds the most RELIABLE way to read AlphaSpread annual statements (+ solvency, moat, 3Y ROIC) for Quality v2.
#
# Default stocks: nasdaq/adsk nyse/orcl nyse/uber (ADSK and ORCL are the two test cases of the Quality v2 spec).
# Env: AS_PATHS (space/comma separated), STRATEGIES (filter, e.g. "F2 F3"), REPEATS (default 2 = every strategy is run twice per page to see
# whether the result is repeatable), DISCOVERY ("1" default = also save the markup facts listed below).
#
# PART 1  DISCOVERY (once per stock; writes fin_pages/<stock>_discovery.json + the page HTML before and after the unit switch)
#   - outerHTML of every element that looks like the unit selector ("Auto" / "Millions" / <select>)
#   - outerHTML of the first 3 data rows of the statement table and ALL link targets of the row labels (checks the "slug at the end of the row link" assumption)
#   - every fetch()/XHR the page makes while the unit is switched (URL + first 300 chars of the answer) -> shows whether the numbers also come as JSON
# PART 2  STRATEGIES for the three statement pages (income / balance / cash flow), each run REPEATS times:
#   F1_auto         read the annual view as it is (unit "Auto": values are rounded, e.g. 1.3B)
#   F2_select       set the unit with the <select> element (JS value + input/change events), wait for the table to change
#   F3_click_js     open the "Auto" dropdown and click "Millions" with JS
#   F4_click_real   same with real Selenium clicks
#   F5_reload_f2    F2, and if the table did not change: reload the page once and repeat
#   R1_requests     plain HTTP GET with the browser's cookies (no click, no rendering): does the server already send the table?
# PART 3  EXTRAS (solvency / moat / profitability pages), each REPEATS times.
#
# A run counts as OK only when: not a Cloudflare page, >= 8 fiscal years, every wanted row slug found, unit really Millions (no B/T suffixes left),
# and the consistency checks pass (FCF = operating cash flow - |capex| within 2 % in >= 80 % of the years; revenue and shares positive).
# Repeat check: the second run of a strategy must give the same numbers as the first (max relative difference < 0.5 %).
# Output: results_fin.json, a ranking table in the log and in $GITHUB_STEP_SUMMARY, fin_pages/ (HTML of every failure and of the discovery pages).
import json, os, re, sys, time
from seleniumbase import SB
import as_fin_data as F

try:
    import requests
except Exception:
    requests = None

DEFAULT = "nasdaq/adsk nyse/orcl nyse/uber"
PATHS = [p.strip().strip("/") for p in re.split(r"[\s,]+", os.environ.get("AS_PATHS", "").strip() or DEFAULT) if p.strip()]
ONLY = [s.strip() for s in re.split(r"[\s,]+", os.environ.get("STRATEGIES", "").strip()) if s.strip()]
REPEATS = max(1, int(os.environ.get("REPEATS", "2") or 2))
DISCOVERY = os.environ.get("DISCOVERY", "1") != "0"
OUT = "fin_pages"
os.makedirs(OUT, exist_ok=True)
FY_RE = r"FY\s*20\d\d"
results, discoveries = [], {}

UNIT_FACTS_JS = r"""
var out = {selects: [], autoEls: [], millionsEls: []};
document.querySelectorAll('select').forEach(function (s) { out.selects.push(s.outerHTML.slice(0, 600)); });
document.querySelectorAll('button, a, label, li, span, div, option').forEach(function (e) {
  var t = (e.textContent || '').trim();
  if (e.children.length === 0 && t === 'Auto') { out.autoEls.push((e.parentElement ? e.parentElement.outerHTML : e.outerHTML).slice(0, 700)); }
  if (e.children.length === 0 && t === 'Millions') { out.millionsEls.push((e.parentElement ? e.parentElement.outerHTML : e.outerHTML).slice(0, 700)); }
});
out.autoEls = out.autoEls.slice(0, 3); out.millionsEls = out.millionsEls.slice(0, 3);
return JSON.stringify(out);
"""
ROW_FACTS_JS = r"""
var best = null, bestN = 0;
document.querySelectorAll('table').forEach(function (t) {
  var n = (t.innerText.match(/FY\s*20\d\d/g) || []).length; if (n > bestN) { best = t; bestN = n; } });
if (!best) { return JSON.stringify({error: 'no table'}); }
var rows = Array.prototype.slice.call(best.querySelectorAll('tr'));
var sample = rows.slice(1, 4).map(function (r) { return r.outerHTML.slice(0, 900); });
var links = [];
rows.forEach(function (r) { var a = r.querySelector('td a, th a'); links.push(a ? a.getAttribute('href') : null); });
return JSON.stringify({rowCount: rows.length, sampleRows: sample, labelLinks: links.slice(0, 40)});
"""
HOOK_JS = r"""
if (!window.__cap) {
  window.__cap = [];
  var of = window.fetch;
  window.fetch = function () {
    var u = arguments[0] && arguments[0].url ? arguments[0].url : String(arguments[0]);
    var p = of.apply(this, arguments);
    p.then(function (r) { r.clone().text().then(function (t) { window.__cap.push({kind: 'fetch', url: u, status: r.status, head: t.slice(0, 300)}); }); });
    return p;
  };
  var oo = XMLHttpRequest.prototype.open, os_ = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function (m, u) { this.__u = u; return oo.apply(this, arguments); };
  XMLHttpRequest.prototype.send = function () {
    var x = this; x.addEventListener('load', function () { window.__cap.push({kind: 'xhr', url: x.__u, status: x.status, head: String(x.responseText || '').slice(0, 300)}); });
    return os_.apply(this, arguments);
  };
}
return true;
"""
CLICK_TEXT_JS = ("var want = arguments[0], best = null;"
                 "document.querySelectorAll('button, a, label, li, span, div, option').forEach(function (e) {"
                 "  if (e.children.length === 0 && (e.textContent || '').trim() === want) { best = best || e; } });"
                 "if (!best) { return 'none'; } best.scrollIntoView({block: 'center'}); best.click(); return 'clicked';")


def blocked(sb):
    return "just a moment" in (sb.get_title() or "").lower()


def open_page(sb, url, ready=FY_RE):
    """opens url; waits for `ready` in the page text; Cloudflare is retried (12 s, 25 s). Returns (source, cloudflare_hits)."""
    hits = 0
    for wait in (0, 12, 25):
        if wait:
            sb.sleep(wait)
        sb.uc_open_with_reconnect(url, 4)
        sb.sleep(2.0)
        if blocked(sb):
            hits += 1
            continue
        for _ in range(14):
            src = sb.get_page_source()
            if re.search(ready, re.sub(r"<[^>]+>", " ", src)):
                return src, hits
            sb.sleep(1.5)
        return sb.get_page_source(), hits
    return "", hits


def table_signature(src):
    return len(src), hash(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", src))[:60000])


def wait_changed(sb, before, seconds=12):
    for _ in range(seconds):
        sb.sleep(1.0)
        now = sb.get_page_source()
        if table_signature(now) != before:
            return now
    return None


def js(sb, code, *args):
    try:
        return sb.execute_script(code, *args)
    except Exception as e:
        return "ERR " + type(e).__name__


# ----------------------------------------------------------------------------- unit strategies: each returns (source, how) or (None, why)
def f1(sb, url, src):
    return src, "auto"


def f2(sb, url, src):
    before = table_signature(src)
    how = js(sb, F._SET_MILLIONS_JS)
    new = wait_changed(sb, before) if how in ("select", "clicked") else None
    return (new, how) if new else (None, "no change after " + str(how))


def f3(sb, url, src):
    before = table_signature(src)
    a = js(sb, CLICK_TEXT_JS, "Auto")
    sb.sleep(1.0)
    b = js(sb, CLICK_TEXT_JS, "Millions")
    new = wait_changed(sb, before)
    return (new, "{}/{}".format(a, b)) if new else (None, "no change after {}/{}".format(a, b))


def f4(sb, url, src):
    before = table_signature(src)
    try:
        sb.click('//*[normalize-space(text())="Auto"]', by="xpath", timeout=6)
        sb.sleep(1.0)
        sb.click('//*[normalize-space(text())="Millions"]', by="xpath", timeout=6)
    except Exception as e:
        return None, "real click failed: " + type(e).__name__
    new = wait_changed(sb, before)
    return (new, "real") if new else (None, "no change after real clicks")


def f5(sb, url, src):
    new, how = f2(sb, url, src)
    if new:
        return new, how
    src2, _ = open_page(sb, url)
    if not src2:
        return None, "reload blocked"
    return f2(sb, url, src2)


def r1(sb, url, src):
    if requests is None:
        return None, "requests missing"
    try:
        cookies = {c["name"]: c["value"] for c in sb.driver.get_cookies()}
        ua = sb.execute_script("return navigator.userAgent")
        r = requests.get(url, cookies=cookies, headers={"User-Agent": ua, "Accept-Language": "en"}, timeout=40)
        if r.status_code != 200 or not re.search(FY_RE, re.sub(r"<[^>]+>", " ", r.text)):
            return None, "HTTP {} no FY table in the answer ({} chars)".format(r.status_code, len(r.text))
        return r.text, "requests"
    except Exception as e:
        return None, "requests " + type(e).__name__


STRATS = [("F1_auto", f1), ("F2_select", f2), ("F3_click_js", f3), ("F4_click_real", f4), ("F5_reload_f2", f5), ("R1_requests", r1)]


def millions_active(src):
    """True when no table value carries a B/T suffix (Auto shows 1.3B / 2.7T); needs at least one number."""
    tables = re.findall(r"<table.*?</table>", src, re.S)   # statement table only: the page header carries "Market Cap $376B"
    tables.sort(key=lambda x: -len(re.findall(r"FY\s*20\d\d", x)))
    text = re.sub(r"<[^>]+>", " ", tables[0] if tables else src)
    numbers = re.findall(r"\(?-?\d[\d,]*\.?\d*\s?([BT])\b", text)
    return len(numbers) == 0


def checks(series, years):
    """consistency of one parsed cash-flow / income / balance set. series = {group: {slug: [..]}}"""
    notes, ok = [], True
    cf = series.get("cf", {})
    f, o, c = cf.get("free-cash-flow"), cf.get("cash-from-operating-activities"), cf.get("capital-expenditures")
    if f and o and c:
        good = tot = 0
        for a, b, d in zip(f, o, c):
            if a is None or b is None or d is None:
                continue
            tot += 1
            if abs(a - (b - abs(d))) <= 0.02 * (abs(b) + 1):
                good += 1
        if tot:
            notes.append("FCF=OCF-capex {}/{}".format(good, tot))
            ok = ok and good / tot >= 0.8
    rev = series.get("is", {}).get("revenue")
    if rev and any(v is not None and v <= 0 for v in rev):
        ok = False
        notes.append("revenue<=0")
    sh = series.get("bs", {}).get("common-shares-outstanding")
    if sh and any(v is not None and v <= 0 for v in sh):
        ok = False
        notes.append("shares<=0")
    return ok, "; ".join(notes)


def max_rel_diff(a, b):
    worst = 0.0
    for slug, va in a.items():
        vb = b.get(slug)
        if not vb:
            return 1.0
        for x, y in zip(va, vb):
            if x is None and y is None:
                continue
            if x is None or y is None:
                return 1.0
            worst = max(worst, abs(x - y) / (abs(x) + abs(y) + 1e-9) * 2)
    return worst


def save(name, text):
    try:
        with open(os.path.join(OUT, name), "w", encoding="utf-8") as h:
            h.write(text)
    except Exception:
        pass


def discovery(sb, path):
    base = F.BASE.format(path)
    url = base + F.PAGES["is"]
    d = {"url": url}
    src, hits = open_page(sb, url)
    d["cloudflare_hits"] = hits
    if not src:
        discoveries[path] = d
        return
    save(path.replace("/", "_") + "_is_before.html", src)
    d["unit_facts"] = js(sb, UNIT_FACTS_JS)
    d["row_facts"] = js(sb, ROW_FACTS_JS)
    js(sb, HOOK_JS)
    before = table_signature(src)
    d["switch"] = js(sb, F._SET_MILLIONS_JS)
    new = wait_changed(sb, before)
    d["table_changed"] = bool(new)
    d["captured_requests"] = js(sb, "return JSON.stringify(window.__cap || [])")
    if new:
        save(path.replace("/", "_") + "_is_after.html", new)
    discoveries[path] = d
    print("DISCOVERY {}: switch={} changed={} requests={}".format(path, d["switch"], d["table_changed"], str(d["captured_requests"])[:200]))


def run_statements(sb, path):
    base = F.BASE.format(path)
    wanted_total = {g: len(F.SLUGS[g]) for g in F.PAGES}
    for name, fn in STRATS:
        if ONLY and not any(name.startswith(o) for o in ONLY):
            continue
        prev = {}
        for rep in range(1, REPEATS + 1):
            series, per_group, t0 = {}, {}, time.time()
            fail = ""
            cf_hits = 0
            for group, page in F.PAGES.items():
                try:
                    src, hits = open_page(sb, base + page)
                    cf_hits += hits
                    if not src:
                        fail = "blocked:" + group
                        break
                    new, how = fn(sb, base + page, src)
                    if new is None:
                        fail = "unit:{}:{}".format(group, how)
                        save("{}_{}_{}_{}_fail.html".format(path.replace("/", "_"), name, group, rep), src)
                        break
                    millions = millions_active(new) if name != "F1_auto" else False
                    order, ser, info = F.parse_statement(new, group, unit_selected_millions=millions)
                    per_group[group] = {"years": len(order), "rows": info.get("rows"), "missing": info.get("missing"), "how": how, "millions": millions}
                    if len(order) < 8 or info.get("missing"):
                        fail = "parse:{}:years={} missing={}".format(group, len(order), ",".join(info.get("missing", [])))
                        save("{}_{}_{}_{}_parse.html".format(path.replace("/", "_"), name, group, rep), new)
                        break
                    if name != "F1_auto" and not millions:
                        fail = "unit:{}:still B/T suffixes".format(group)
                        break
                    series[group] = ser
                except Exception as e:
                    fail = "error:{}:{}".format(group, type(e).__name__)
                    break
            ok = not fail
            note = ""
            if ok:
                ok, note = checks(series, None)
                if not ok:
                    fail = "consistency: " + note
            repeat = None
            if ok and prev:
                diffs = [max_rel_diff(prev[g], series[g]) for g in series if g in prev]
                repeat = round(max(diffs), 5) if diffs else None
                if repeat is not None and repeat > 0.005:
                    ok, fail = False, "repeat differs by {:.2%}".format(repeat)
            if ok:
                prev = series
            results.append({"part": "statements", "stock": path, "strategy": name, "rep": rep, "ok": ok, "fail": fail, "seconds": round(time.time() - t0, 1),
                            "cloudflare_hits": cf_hits, "groups": per_group, "checks": note, "repeat_diff": repeat})
            print("[{}] {} rep{}: {} {} ({:.0f}s)".format(path, name, rep, "OK" if ok else "FAIL", fail or note, time.time() - t0))
            sb.sleep(4.0)


def run_extras(sb, path):
    base = F.BASE.format(path)
    items = [("solvency", "solvency", r"Net\s+Debt"), ("moat", "qualitative/block/economic-moat", r"What is Economic Moat\?"), ("profitability", "profitability", r"3Y Average ROIC")]
    for rep in range(1, REPEATS + 1):
        for name, page, ready in items:
            t0 = time.time()
            src, hits = open_page(sb, base + page, ready)
            ok, got = False, None
            if src:
                if name == "solvency":
                    got = F.parse_solvency(src)
                    ok = got["net_debt"] is not None and got["int_cov"] is not None
                elif name == "moat":
                    try:
                        import as_moat
                        got = F.parse_moat_rating(as_moat.parse_moat(src).get("rating"))
                    except Exception as e:
                        got = "ERR " + type(e).__name__
                    ok = got in ("Wide", "Narrow", "None")
                else:
                    got = F.parse_roic3y(src)
                    ok = got is not None
                if not ok:
                    save("{}_{}_{}_fail.html".format(path.replace("/", "_"), name, rep), src)
            results.append({"part": "extras", "stock": path, "strategy": name, "rep": rep, "ok": ok, "fail": "" if ok else ("blocked" if not src else "not parsed"),
                            "seconds": round(time.time() - t0, 1), "cloudflare_hits": hits, "value": got})
            print("[{}] extras {} rep{}: {} {}".format(path, name, rep, "OK" if ok else "FAIL", got))
            sb.sleep(3.0)


def summary():
    lines = ["| part | strategy | ok / runs | avg s | Cloudflare hits | failures |", "|---|---|---|---|---|---|"]
    keys = []
    for r in results:
        k = (r["part"], r["strategy"])
        if k not in keys:
            keys.append(k)
    ranking = []
    for part, strat in keys:
        rs = [r for r in results if r["part"] == part and r["strategy"] == strat]
        ok = sum(1 for r in rs if r["ok"])
        fails = sorted({r["fail"].split(":")[0] + ":" + (r["fail"].split(":")[1] if ":" in r["fail"] else "") for r in rs if r["fail"]})
        ranking.append((part, strat, ok, len(rs), sum(r["seconds"] for r in rs) / max(1, len(rs)), sum(r.get("cloudflare_hits", 0) for r in rs), fails))
    ranking.sort(key=lambda x: (x[0], -x[2] / max(1, x[3]), x[4]))
    for part, strat, ok, n, avg, hits, fails in ranking:
        lines.append("| {} | {} | {}/{} | {:.0f} | {} | {} |".format(part, strat, ok, n, avg, hits, "; ".join(fails)[:120]))
    text = "\n".join(lines)
    print("\n" + text)
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as h:
            h.write("## AS Fin test\n" + text + "\n")


def main():
    print("as_fin_test v1 | stocks: {} | repeats: {} | strategies: {}".format(PATHS, REPEATS, ONLY or "all"))
    with SB(uc=True, headless=False, locale_code="en") as sb:
        for path in PATHS:
            try:
                if DISCOVERY:
                    discovery(sb, path)
                run_statements(sb, path)
                run_extras(sb, path)
            except Exception as e:
                print("stock {} aborted: {}".format(path, type(e).__name__))
    with open("results_fin.json", "w", encoding="utf-8") as h:
        json.dump({"results": results, "discovery": discoveries}, h, ensure_ascii=False, indent=1)
    summary()


if __name__ == "__main__":
    main()
