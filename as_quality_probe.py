# as_quality_probe.py v1 -- opens the 4 AlphaSpread pages of ONE ticker in one browser, saves the raw HTML
# (uploaded as a workflow artifact so the parser can be corrected against the real markup) and prints the
# six structural metrics from as_quality_metrics.py.
import json, os, re, time
from seleniumbase import SB
import as_quality_metrics as q

AS_PATH = os.environ.get("AS_PATH", "nyse/baba").strip("/")
BASE = "https://www.alphaspread.com/security/{}/".format(AS_PATH)
PAGES = [("profitability", "profitability"),
         ("income", "financials/income-statement"),
         ("balance", "financials/balance-sheet"),
         ("cashflow", "financials/cash-flow-statement")]
OUT = "as_pages"
os.makedirs(OUT, exist_ok=True)
html = {}

with SB(uc=True, headless=False, locale_code="en", test=True) as sb:
    for name, path in PAGES:
        started = time.time()
        sb.uc_open_with_reconnect(BASE + path, 5)
        # wait until the page has what we need (a table with FY headers, or the ROIC text)
        for _ in range(20):
            source = sb.get_page_source()
            ready = ("3Y Average ROIC" in source) if name == "profitability" else bool(re.search(r"FY\s*20\d\d", source))
            if ready:
                break
            sb.sleep(1.5)
        html[name] = source
        open(os.path.join(OUT, name + ".html"), "w", encoding="utf-8").write(source)
        print("PAGE {:<14} title={!r} len={} ready={} {:.0f}s".format(name, sb.get_title(), len(source), ready, time.time() - started))

result = q.compute_metrics(html["profitability"], html["income"], html["balance"], html["cashflow"])
print("METRICS", json.dumps(result["metrics"]))
print("SCORES ", json.dumps(result["scores"]))
print("PARTIAL_STRUCTURAL", result["partial_structural"], "| coverage", result["coverage_pct"], "| display:", result["display"])
print("DIAGNOSTICS", json.dumps(result["diagnostics"], default=str))
print("QUALITY_SUMMARY " + json.dumps({"as_path": AS_PATH, **result}, default=str))
