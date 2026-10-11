import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import as_quality_v3 as v3

YEARS = list(range(2017, 2027)); n = len(YEARS)

def fmt(v):
    if v is None: return "—"
    a = abs(v)
    for div, suf in ((1e12, "T"), (1e9, "B"), (1e6, "m")):
        if a >= div:
            s = "%g%s" % (round(a / div, 4), suf); break
    else:
        s = "%g" % round(a, 4)
    return "(%s)" % s if v < 0 else s

def table(rows):
    head = "<tr><th>Metric</th>" + "".join("<th>%sFY%d (Dec %d)</th>" % ("Earlier " if y == 2017 else "", y, y) for y in YEARS) + "</tr>"
    body = "".join("<tr><td>%s</td>%s</tr>" % (k, "".join("<td>%s</td>" % fmt(v) for v in vals)) for k, vals in rows.items())
    return "<html><body><table>%s%s</table></body></html>" % (head, body)

rev = [300e9 * 1.1 ** i for i in range(n)]
op = [0.2 * r for r in rev]
shares = [1000e6 * 0.99 ** i for i in range(n)]
ni = [0.8 * o for o in op]
eps = [a / s for a, s in zip(ni, shares)]
inc = table({"Revenue": rev, "Cost of Revenue": [-0.4 * r for r in rev], "Gross Profit": [0.6 * r for r in rev],
             "Operating Income": op, "Interest Expense": [5e9] * n, "Pre-Tax Income": op, "Tax Provision": [-0.2 * o for o in op],
             "Net Income": ni, "EPS Diluted": eps})
bal = table({"Cash & Cash Equivalents": [50e9] * n, "Short-Term Debt": [0] * n, "Current Portion of Long-Term Debt": [10e9] * n,
             "Long-Term Debt": [190e9] * n, "Total Equity": [350e9] * n, "Total Assets": [700e9] * n, "Goodwill": [100e9] * n,
             "Common Shares Outstanding": shares})
cfs = table({"Net Income": ni, "Depreciation & Amortization": [20e9] * n, "Cash from Operating Activities": [1.2 * x for x in ni],
             "Capital Expenditures": [-10e9] * n})
r = v3.compute_v3("", inc, bal, cfs)
assert r["profile"] == "NF" and r["coverage_pct"] == 100, r["warnings"]
m = r["metrics"]
nopat = lambda i: 0.8 * op[i]
roic = [nopat(i) / 550e9 * 100 for i in range(n)]
import statistics
assert abs(m["roic_med5"] - statistics.median(roic[-5:])) < 0.01
assert abs(m["roic_persist"] - 100.0 * sum(1 for x in roic[-8:] if x >= 10) / 8) < 0.01
assert abs(m["op_margin3"] - 20.0) < 0.01
assert abs(m["rev_cagr5"] - 10.0) < 0.01 and abs(m["rev_worst"] - 10.0) < 0.01
exp_eps = ((sum(eps[-3:]) / 3) / (sum(eps[2:5]) / 3)) ** (1 / 5) * 100 - 100   # 2019-2021 avg vs 2024-2026 avg
assert abs(m["eps_cagr5"] - exp_eps) < 0.01, (m["eps_cagr5"], exp_eps)
assert abs(m["shr_cagr"] + 1.0) < 0.05
assert r["scores"]["rev_cagr5"] == 33.3 or abs(r["scores"]["rev_cagr5"] - 100 * (10 - 2) / 12) < 0.1
assert r["scores"]["op_margin3"] == 75.0 and r["flags"] == [] and r["q_capped"] == r["q"]
assert r["v1"]["struct"] is not None
assert abs(sum(r["weights"].values()) - 100) < 1e-9

# financial: no gross profit / cost of revenue rows
finc = table({"Revenue": rev, "Pre-Tax Income": [0.3 * x for x in rev], "Net Income": [0.2 * x for x in rev], "EPS Diluted": eps})
fbal = table({"Total Equity": [20e9 * 1.08 ** i for i in range(n)], "Total Assets": [200e9 * 1.08 ** i for i in range(n)],
              "Common Shares Outstanding": shares})
rf = v3.compute_v3("", finc, fbal, cfs)
assert rf["profile"] == "FIN" and "pt_margin3" in rf["metrics"] and abs(rf["metrics"]["pt_margin3"] - 30) < 0.01
assert abs(rf["metrics"]["eq_assets"] - 10.0) < 0.01 and rf["metrics"]["roe3"] > 0
assert any("financial" in w for w in rf["warnings"]) and abs(sum(rf["weights"].values()) - 100) < 1e-9
assert v3.compute_v3("", finc, fbal, cfs, profile="NF")["profile"] == "NF"

# caps: two loss years and a revenue decline
ni_loss = list(ni); ni_loss[-1] = -1e9; ni_loss[-2] = -2e9
rev_down = [300e9 * 0.95 ** i for i in range(n)]
inc2 = table({"Revenue": rev_down, "Cost of Revenue": [-0.4 * x for x in rev_down], "Gross Profit": [0.6 * x for x in rev_down],
              "Operating Income": [0.2 * x for x in rev_down], "Pre-Tax Income": [0.2 * x for x in rev_down],
              "Tax Provision": [-0.04 * x for x in rev_down], "Net Income": ni_loss, "EPS Diluted": eps})
r2 = v3.compute_v3("", inc2, bal, cfs)
assert any(f.startswith("net loss") for f in r2["flags"]) and "revenue CAGR<0" in r2["flags"]
assert r2["q_capped"] <= 50

# negative EPS endpoint -> unavailable, never zero
eps_neg = list(eps); eps_neg[-3:] = [-0.5, -0.5, -0.5]
inc3 = table({"Revenue": rev, "Cost of Revenue": [-0.4 * x for x in rev], "Gross Profit": [0.6 * x for x in rev],
              "Operating Income": op, "Pre-Tax Income": op, "Tax Provision": [-0.2 * o for o in op], "Net Income": ni, "EPS Diluted": eps_neg})
r3 = v3.compute_v3("", inc3, bal, cfs)
assert r3["metrics"].get("eps_cagr5") is None and r3["scores"]["eps_cagr5"] is None and r3["coverage_pct"] == 86, r3["coverage_pct"]

# warnings: goodwill > 50% of assets; short history
bal4 = table({"Cash & Cash Equivalents": [50e9] * n, "Long-Term Debt": [200e9] * n, "Total Equity": [350e9] * n,
              "Total Assets": [700e9] * n, "Goodwill": [400e9] * n, "Common Shares Outstanding": shares})
assert any("goodwill" in w for w in v3.compute_v3("", inc, bal4, cfs)["warnings"])
YEARS_SAVE = YEARS
print("all v3 tests passed")
