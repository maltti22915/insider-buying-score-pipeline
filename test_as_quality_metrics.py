import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import as_ttm_metrics as T

MON = ["Mar 2024","Jun 2024","Sep 2024","Dec 2024","Mar 2025","Jun 2025","Sep 2025","Dec 2025","Mar 2026","Jun 2026"]

def table(header_cells, rows):
    h = "<table><tr>" + "".join("<th>%s</th>" % c for c in header_cells) + "</tr>"
    for r in rows:
        h += "<tr>" + "".join("<td>%s</td>" % c for c in r) + "</tr>"
    return h + "</table>"

def ttm_header():
    return ["Metric", "Earlier"] + ["TTM %s" % m for m in MON]

# MELI values read from the AlphaSpread screenshots (TTM view)
INC = table(ttm_header(), [
    ["Revenue", ""] + ["16.3B","17.7B","19.1B","20.8B","22.4B","24.1B","26.2B","28.9B","31.8B","35.2B"],
    ["Gross Profit", ""] + ["8B","8.5B","8.9B","9.6B","10.3B","11.1B","11.8B","12.9B","13.9B","15B"],
    ["Operating Income", ""] + ["2.3B","2.4B","2.1B","2.6B","2.9B","3B","3.1B","3.2B","3B","2.9B"],
    ["Interest Expense", ""] + ["178m","168m","155m","165m","166m","163m","158m","160m","186m","212m"],
])
CFS = table(ttm_header(), [
    ["Depreciation & Amortization", ""] + ["552m","578m","600m","617m","635m","680m","732m","818m","892m","985m"],
    ["Stock-Based Compensation", ""] + ["188m","152m","235m","261m","193m","193m","193m","303m","399m","468m"],
    ["Cash from Operating Activities", ""] + ["5.8B","6.3B","6.9B","7.9B","7.4B","8.5B","9.8B","12.1B","13.2B","13.9B"],
    ["Capital Expenditures", ""] + ["(568m)","(638m)","(735m)","(860m)","(984m)","(1.1B)","(1.2B)","(1.3B)","(1.3B)","(1.5B)"],
])
QH = ["Metric", "Earlier"] + ["Q%d FY%d %s" % ((i % 4) + 1, 2024 + i // 4, m) for i, m in enumerate(MON)]
BAL = table(QH, [
    ["Cash & Cash Equivalents", ""] + ["2.6B","2.8B","2.2B","2.6B","3B","3B","2.6B","3.7B","3.7B","3.6B"],
    ["Short-Term Investments", ""] + ["3.7B","4.1B","4.5B","4.5B","5.1B","4.6B","3.7B","2.6B","2B","2.1B"],
    ["Long-Term Debt", ""] + ["1B"] * 10,
])

assert T.parse_value("(1.5B)") == -1.5e9 and T.parse_value("468m") == 468e6 and T.parse_value("—") is None
rows, periods, info = T.parse_period_table(INC, "ttm")
assert periods[-1] == (2026, 6) and len(periods) == 10 and rows["Revenue"][(2026, 6)] == 35.2e9
# annual / quarterly tables must not be mistaken for TTM
assert T.parse_period_table(BAL, "ttm")[1] == []
q_rows, q_periods, _ = T.parse_period_table(BAL, "q")
assert q_periods[-1] == (2026, 6) and q_rows["Cash & Cash Equivalents"][(2026, 6)] == 3.6e9

r = T.compute_now(INC, CFS, BAL)
s = r["signals"]
assert abs(s["rev_growth"] - 46.06) < 0.1, s          # 35.2 / 24.1
assert abs(s["gm_delta"] - (15 / 35.2 * 100 - 11.1 / 24.1 * 100)) < 1e-6   # about -3.4pp
assert abs(s["om_delta"] - (2.9 / 35.2 * 100 - 3.0 / 24.1 * 100)) < 1e-6   # about -4.2pp
# growth a year earlier: 24.1 / 16.3? no -> prev2 is Jun 2024 = 17.7: 24.1/17.7 = +36.2%
assert abs(s["rev_accel"] - (46.06 - 36.16)) < 0.2, s
assert r["details"]["rev_accel_vs"] == "growth one year earlier"
fcfm_now = (13.9 - 1.5 - 0.468) / 35.2 * 100
fcfm_prev = (8.5 - 1.1 - 0.193) / 24.1 * 100
assert abs(s["fcfm_delta"] - (fcfm_now - fcfm_prev)) < 0.05, s
assert r["scores"]["om_delta"] == 0.0 and 0 < r["scores"]["gm_delta"] < 60
assert 0 < r["now"] < 100
assert abs(r["levels"]["interest_cover_ttm"] - 2.9 / 0.212) < 0.01
# net cash: debt 1B - cash 3.6B - STI 2.1B < 0 -> ND/EBITDA reported as negative
assert r["levels"]["nd_ebitda_ttm"] < 0
# with a 5y CAGR given it is used as the base
r2 = T.compute_now(INC, CFS, BAL, rev_cagr5_pct=30.0)
assert abs(r2["signals"]["rev_accel"] - (46.06 - 30.0)) < 0.1 and r2["details"]["rev_accel_vs"] == "5y CAGR"
# missing pages degrade, never raise
r3 = T.compute_now("", CFS, BAL)
assert r3["now"] is None and r3["warnings"]
# scoring anchors
assert T.score_signal(-4, -4, 3) == 0 and T.score_signal(0, -4, 3) == 60 and T.score_signal(3, -4, 3) == 100
assert abs(T.score_signal(-2, -4, 3) - 30) < 1e-9
print("all ttm tests passed")

# v1.2: financial profile skips FCF / gross margin; implausible margin swings are ignored
rf = T.compute_now(INC, CFS, BAL, profile="FIN")
assert "fcfm_delta" not in rf["signals"] and "gm_delta" not in rf["signals"] and "om_delta" in rf["signals"]
CFS_BAD = CFS.replace("<td>13.9B</td>", "<td>-300B</td>")
rb = T.compute_now(INC, CFS_BAD, BAL)
assert "fcfm_delta" not in rb["signals"] and any("implausible" in w for w in rb["warnings"])
print("ttm v1.2 tests passed")
