# as_validation_batch.py v1 -- runs the quality models on a list of AlphaSpread tickers in one GitHub job.
# Per ticker (own browser): profitability + income + balance + cash-flow pages (annual), TTM view of income and cash flow,
# Quarterly view of the balance sheet. Computes v1 "Struct", Q v3 and the Now block, prints one comparison table,
# the Spearman correlation against a reference ranking, and writes results.json (+ raw HTML under as_pages/).
import json, os, re, time
from seleniumbase import SB
import as_quality_metrics as q1
import as_quality_v3 as v3
import as_ttm_metrics as ttm

DEFAULT = ("tsx/csu nasdaq/adsk nyse/now xetra/evd nasdaq/app nyse/uber xetra/ftk xetra/sap nasdaq/meta nasdaq/amzn "
           "nasdaq/meli nyse/unh nyse/msci nyse/baba cse/chemm")
PATHS = [p.strip().strip("/") for p in re.split(r"[\s,]+", os.environ.get("AS_PATHS", "").strip() or DEFAULT) if p.strip()]
# reference ranking = Claude's blind judgment of 10-year business quality (opinion, not data); replace with your own via USER_TIERS
JUDGMENT = {"nyse/msci": 90, "tsx/csu": 88, "cse/chemm": 85, "nasdaq/adsk": 84, "nyse/now": 80, "xetra/sap": 80, "nasdaq/meta": 80,
            "xetra/evd": 78, "nasdaq/amzn": 76, "nasdaq/meli": 74, "nyse/unh": 68, "nasdaq/app": 62, "nyse/uber": 58, "nyse/baba": 52, "xetra/ftk": 50}
TIER_SCORE = {"A": 90, "B": 70, "C": 50, "D": 30}
for pair in re.split(r"[\s,]+", os.environ.get("USER_TIERS", "").strip()):
    if "=" in pair:
        k, v = pair.split("=", 1)
        if v.strip().upper() in TIER_SCORE:
            JUDGMENT[k.strip().strip("/")] = TIER_SCORE[v.strip().upper()]
OUT = "as_pages"
os.makedirs(OUT, exist_ok=True)
PAGES = [("profitability", "profitability"), ("income", "financials/income-statement"),
         ("balance", "financials/balance-sheet"), ("cashflow", "financials/cash-flow-statement")]
VIEWS = {"income": ("TTM", r"TTM\s+[A-Z][a-z]{2}\s+\d{4}"), "cashflow": ("TTM", r"TTM\s+[A-Z][a-z]{2}\s+\d{4}"),
         "balance": ("Quarterly", r"Q\d\s*FY\d{4}")}


def click_view(sb, toggle):
    label, pattern = toggle
    try:
        res = sb.execute_script(
            "var want = arguments[0], best = null;"
            "document.querySelectorAll('button, a, label, li, span, div').forEach(function (e) {"
            "  if (e.children.length === 0 && (e.textContent || '').trim() === want) { best = best || e; } });"
            "if (!best) { return 'none'; } best.scrollIntoView({block: 'center'}); best.click(); return 'clicked';", label)
        if res != "clicked":
            return "", "toggle not found"
        for _ in range(10):
            sb.sleep(1.0)
            src = sb.get_page_source()
            if re.search(pattern, src):
                return src, ""
        return "", "header did not change"
    except Exception as e:
        return "", type(e).__name__


def rank(values):
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2.0 + 1
        i = j + 1
    return ranks


def spearman(a, b):
    if len(a) < 4:
        return None
    ra, rb = rank(a), rank(b)
    ma, mb = sum(ra) / len(ra), sum(rb) / len(rb)
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    den = (sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb)) ** 0.5
    return num / den if den else None


def run_one(path):
    base = "https://www.alphaspread.com/security/{}/".format(path)
    folder = os.path.join(OUT, path.replace("/", "_"))
    os.makedirs(folder, exist_ok=True)
    pages, views, notes = {}, {}, []
    with SB(uc=True, headless=False, locale_code="en", test=True) as sb:
        for name, rel in PAGES:
            started = time.time()
            try:
                sb.uc_open_with_reconnect(base + rel, 5)
                source = ""
                for _ in range(20):
                    source = sb.get_page_source()
                    ready = ("3Y Average ROIC" in source) if name == "profitability" else bool(re.search(r"FY\s*20\d\d", source))
                    if ready:
                        break
                    sb.sleep(1.5)
                if "just a moment" in (sb.get_title() or "").lower():
                    notes.append(name + ": blocked")
                    continue
                pages[name] = source
                open(os.path.join(folder, name + ".html"), "w", encoding="utf-8").write(source)
                if name in VIEWS:
                    view, why = click_view(sb, VIEWS[name])
                    if view:
                        views[name] = view
                        open(os.path.join(folder, name + "_" + VIEWS[name][0].lower() + ".html"), "w", encoding="utf-8").write(view)
                    else:
                        notes.append("{} {} view: {}".format(name, VIEWS[name][0], why))
                print("  page {:<13} {:.0f}s".format(name, time.time() - started), flush=True)
            except Exception as e:
                notes.append("{}: {}".format(name, type(e).__name__))
    rec = {"path": path, "notes": notes}
    if all(k in pages for k in ("income", "balance", "cashflow")):
        res = v3.compute_v3(pages.get("profitability", ""), pages["income"], pages["balance"], pages["cashflow"])
        rec["v3"] = res
    else:
        rec["error"] = "annual pages missing: " + ",".join(sorted(pages))
    if all(views.get(k) for k in ("income", "cashflow")):
        rec["now"] = ttm.compute_now(views["income"], views["cashflow"], views.get("balance", ""))
    return rec


results = []
for p in PATHS:
    print("=== {}".format(p), flush=True)
    try:
        results.append(run_one(p))
    except Exception as e:
        results.append({"path": p, "error": type(e).__name__ + ": " + str(e)[:80], "notes": []})
        print("  FAILED", e, flush=True)
    time.sleep(3)

json.dump(results, open("results.json", "w"), default=str, indent=1)


def f(x, d=1):
    return "-" if x is None else ("{:.%df}" % d).format(x)


print("\n==== COMPARISON (v1 Struct vs Q v3; reference = judgment score) ====")
cols = ["path", "prof", "judg", "v1", "Q3", "Qcap", "cov", "roic/roe", "persist", "margin", "revCAGR", "worstRev", "epsCAGR", "shr", "now", "flags | warnings"]
print(" | ".join(cols))
x1, x3, xj = [], [], []
for r in results:
    v = r.get("v3")
    if not v:
        print("{} | ERROR {} {}".format(r["path"], r.get("error"), "; ".join(r.get("notes", []))))
        continue
    m = v["metrics"]
    ret = m.get("roic_med5") if v["profile"] == "NF" else m.get("roe3")
    per = m.get("roic_persist") if v["profile"] == "NF" else m.get("roe_persist")
    mar = m.get("op_margin3") if v["profile"] == "NF" else m.get("pt_margin3")
    now = (r.get("now") or {}).get("now")
    print(" | ".join([r["path"], v["profile"], str(JUDGMENT.get(r["path"], "-")), f(v["v1"]["struct"], 0), f(v["q"], 0), f(v["q_capped"], 0),
                      str(v["coverage_pct"]), f(ret), f(per, 0), f(mar), f(m.get("rev_cagr5")), f(m.get("rev_worst")), f(m.get("eps_cagr5")),
                      f(m.get("shr_cagr")), f(now, 0), ", ".join(v["flags"] + v["warnings"]) or "none"]))
    if v["q_capped"] is not None and v["v1"]["struct"] is not None and r["path"] in JUDGMENT:
        x1.append(v["v1"]["struct"]); x3.append(v["q_capped"]); xj.append(JUDGMENT[r["path"]])
print("\nSPEARMAN vs reference ranking (n={}): v1 Struct={}  Q v3={}".format(len(xj), f(spearman(x1, xj), 2), f(spearman(x3, xj), 2)))
print("NOTES:", {r["path"]: r["notes"] for r in results if r.get("notes")})
print("SUMMARY_JSON " + json.dumps([{"path": r["path"], "profile": (r.get("v3") or {}).get("profile"), "q": (r.get("v3") or {}).get("q_capped"),
      "v1": ((r.get("v3") or {}).get("v1") or {}).get("struct"), "metrics": (r.get("v3") or {}).get("metrics"),
      "now": (r.get("now") or {}).get("now"), "signals": (r.get("now") or {}).get("signals")} for r in results], default=str))
