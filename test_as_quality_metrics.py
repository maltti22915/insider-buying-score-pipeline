import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import as_quality_metrics as q

YEARS = list(range(2017, 2027))

def fmt(v):
    if v is None: return "—"
    a = abs(v)
    for div, suf in ((1e12, "T"), (1e9, "B"), (1e6, "m")):
        if a >= div:
            s = "%g%s" % (round(a / div, 3), suf); break
    else:
        s = "%g" % a
    return "(%s)" % s if v < 0 else s

def table(rows):
    head = "<tr><th>Metric</th>" + "".join("<th>%sFY%d (Mar %d)</th>" % ("Earlier " if y == 2017 else "", y, y) for y in YEARS) + "</tr>"
    body = "".join("<tr><td>%s</td>%s</tr>" % (k, "".join("<td>%s</td>" % fmt(v) for v in vals)) for k, vals in rows.items())
    return "<html><body><table>%s%s</table></body></html>" % (head, body)

# company: ROIC ~ 20%, net debt 1x EBITDA, shares shrinking 1%/yr, FCF positive every year
n = len(YEARS)
op = [100e9] * n
inc = table({"Operating Income": op, "Pre-Tax Income": [100e9] * n, "Tax Provision": [-20e9] * n})
bal = table({
    "Cash & Cash Equivalents": [50e9] * n, "Short-Term Investments": [0] * n,
    "Short-Term Debt": [0] * n, "Current Portion of Long-Term Debt": [10e9] * n, "Long-Term Debt": [190e9] * n,
    "Minority Interest": [0] * n, "Total Equity": [350e9] * n,
    "Common Shares Outstanding": [1000e6 * (0.99 ** i) for i in range(n)],
})
cfo = [120e9] * n
cfs = table({"Net Income": [80e9] * n, "Depreciation & Amortization": [50e9] * n,
             "Cash from Operating Activities": cfo, "Capital Expenditures": [-30e9] * n})
prof = "<div>8% Low 3Y Average ROIC</div><div>Low ROIC 3%</div>"
r = q.compute_metrics(prof, inc, bal, cfs)
m = r["metrics"]
# tax 20%; NOPAT 80B; IC (cash not netted) = 350 + 200 = 550 -> 14.5%; net of cash = 500 -> 16%
assert abs(r["diagnostics"]["roic_by_year"][2026] - 14.5) < 0.1, r["diagnostics"]
assert abs(r["diagnostics"]["roic_by_year_net_of_cash"][2026] - 16.0) < 0.1
assert abs(m["roic_min5"] - 14.5) < 0.1
assert m["roic3y"] == 8.0 and r["diagnostics"]["roic3y_source"] == "page", r["diagnostics"]["roic3y_page_note"]
assert abs(m["cfo_ni"] - 1.5) < 1e-6
assert abs(m["nd_ebitda"] - (150 / 150)) < 1e-6          # net debt 150B, EBITDA 150B
assert m["fcf_years"] == 5
assert abs(m["shr_cagr"] - (-1.0)) < 0.05, m["shr_cagr"]
assert r["coverage_pct"] == 100 and r["flags"] == []
print("display:", r["display"], "| scores:", r["scores"])

# share-count unit break (8:1 in FY2022) -> segment restarts, still computed from >=3 points
bal2 = table({**{k: [None] * n for k in ()}, "Cash & Cash Equivalents": [50e9]*n, "Short-Term Debt": [0]*n,
              "Current Portion of Long-Term Debt": [10e9]*n, "Long-Term Debt": [190e9]*n, "Total Equity": [350e9]*n,
              "Common Shares Outstanding": [2.6e9]*5 + [20e9, 19.8e9, 19.6e9, 19.4e9, 19.2e9]})
r2 = q.compute_metrics(prof, inc, bal2, cfs)
assert r2["diagnostics"]["notes"], "jump should be noted"
assert r2["metrics"]["shr_cagr"] is not None and r2["metrics"]["shr_cagr"] < 0
# negative FCF years + net cash
cfs3 = table({"Net Income": [80e9]*n, "Depreciation & Amortization": [50e9]*n,
              "Cash from Operating Activities": [20e9]*n, "Capital Expenditures": [-30e9]*n})
bal3 = table({"Cash & Cash Equivalents": [400e9]*n, "Short-Term Debt": [0]*n, "Current Portion of Long-Term Debt": [0]*n,
              "Long-Term Debt": [100e9]*n, "Total Equity": [350e9]*n, "Common Shares Outstanding": [1e9]*n})
r3 = q.compute_metrics("", inc, bal3, cfs3)
assert r3["metrics"]["fcf_years"] == 0 and r3["scores"]["nd_ebitda"] == 100.0 and "CFO/NI<0.6" in r3["flags"]
assert r3["diagnostics"]["roic3y_source"] == "computed"
# missing page / empty inputs never crash
r4 = q.compute_metrics("", "", "", "")
assert r4["display"].startswith("n/a") and r4["coverage_pct"] == 0
assert q.parse_value("(86B)") == -86e9 and q.parse_value("1m") == 1e6 and q.parse_value("—") is None and q.parse_value("1.1T") == 1.1e12
print("all tests passed")
