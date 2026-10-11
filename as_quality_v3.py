"""
as_quality_v3.py v1 -- "Q v3": seven (non-financial) or eight (financial) past-quality metrics from the same four AlphaSpread pages.
Pure functions, no browser. Reuses the parsers and the ROIC rule of as_quality_metrics.py (v1 "Struct" is computed alongside for comparison).

Non-financial profile (weights sum to 100; score = linear lo -> 0 pts, hi -> 100 pts):
  roic_med5     ROIC, median of the last 5 FY (own yearly series scaled to the page's 3Y average)   8% -> 25%     w26
  roic_persist  share of the last 8 FY (>= 5 valid) with ROIC >= 10%                                 25% -> 100%   w8
  op_margin3    operating income / revenue, 3Y average                                               5% -> 25%     w12
  rev_cagr5     revenue CAGR over the last 5 FY                                                      2% -> 14%     w18
  rev_worst     worst year-over-year revenue change of the last 5 FY                                 -8% -> +4%    w10
  eps_cagr5     diluted EPS CAGR, 3Y-averaged endpoints (single years if history is short); both endpoints must be > 0
                                                                                                     3% -> 15%     w14
  shr_cagr      share-count CAGR (see as_quality_metrics; a >30% jump is reported as a warning)      +3% -> -2%    w12
Financial profile (no gross profit / cost of revenue rows, or bank/insurer row names):
  roe3 (24, 8% -> 20%), roe_persist (8), pt_margin3 (10, 15% -> 40%), rev_cagr5 (16), rev_worst (10), eps_cagr5 (14), shr_cagr (10),
  eq_assets (8, 3% -> 15%)
Caps (Q <= 50): net loss in >= 2 of the last 5 FY, dilution > 5%/yr, revenue CAGR < 0, margin (operating / pre-tax) < 0.
Warnings (never change the score): ND/EBITDA > 4, interest cover < 2x (non-financials), CFO/NI < 0.6 or > 3, goodwill > 50% of assets,
share-count discontinuity, financial company (rate-sensitive earnings, no regulatory capital data).
Missing metrics are dropped and the weights rescaled; Q shows n/a when coverage < 70% or the return metric is missing.
"""
import statistics
import as_quality_metrics as q1

SPEC_NF = [("roic_med5", 26, 8.0, 25.0), ("roic_persist", 8, 25.0, 100.0), ("op_margin3", 12, 5.0, 25.0),
           ("rev_cagr5", 18, 2.0, 14.0), ("rev_worst", 10, -8.0, 4.0), ("eps_cagr5", 14, 3.0, 15.0), ("shr_cagr", 12, 3.0, -2.0)]
SPEC_FIN = [("roe3", 24, 8.0, 20.0), ("roe_persist", 8, 25.0, 100.0), ("pt_margin3", 10, 15.0, 40.0), ("rev_cagr5", 16, 2.0, 14.0),
            ("rev_worst", 10, -8.0, 4.0), ("eps_cagr5", 14, 3.0, 15.0), ("shr_cagr", 10, 3.0, -2.0), ("eq_assets", 8, 3.0, 15.0)]
PERSIST_HURDLE = 10.0
FIN_NAME_HINTS = ("loan", "deposit", "premium", "insurance", "claims")


def _years_ok(table, label, years):
    return [y for y in years if (table.get(label) or {}).get(y) is not None]


def detect_profile(inc):
    gross = inc.get("Gross Profit") or {}
    cost = inc.get("Cost of Revenue") or {}
    has_gross = any(v is not None for v in gross.values()) and any(v is not None for v in cost.values())
    hint = next((l for l in inc if any(h in l.lower() for h in FIN_NAME_HINTS)), None)
    if not has_gross:
        return "FIN", "no Gross Profit / Cost of Revenue values"
    if hint:
        return "FIN", "row '{}'".format(hint)
    return "NF", "gross profit present"


def _roic_series(inc, bal, years):
    out, inputs = {}, {}
    for y in years:
        op, eq = q1._g(inc, "Operating Income", y), q1._g(bal, "Total Equity", y)
        if None in (op, eq):
            continue
        pre, tax = q1._g(inc, "Pre-Tax Income", y), q1._g(inc, "Tax Provision", y)
        rate = abs(tax) / pre if (tax is not None and pre and pre > 0) else q1.TAX_DEFAULT
        rate = max(q1.TAX_MIN, min(q1.TAX_MAX, rate))
        minority = q1._g(bal, "Minority Interest", y) or 0.0
        debt = sum(q1._g(bal, l, y) or 0.0 for l in ("Short-Term Debt", "Current Portion of Long-Term Debt", "Long-Term Debt"))
        capital = eq + minority + debt + q1._lease_total(bal, y)
        if capital > 0:
            out[y] = op * (1 - rate) / capital * 100.0
            inputs[y] = {"op": op, "tax_rate": round(rate, 4), "capital": capital}
    return out, inputs


def _cagr(first, last, n):
    if first is None or last is None or first <= 0 or last <= 0 or n <= 0:
        return None
    return ((last / first) ** (1.0 / n) - 1.0) * 100.0


def _avg(values):
    return sum(values) / len(values) if values else None


def compute_v3(profitability_html, income_html, balance_html, cashflow_html, profile=None):
    inc, iy, iinfo = q1.parse_financial_table(income_html)
    bal, by, binfo = q1.parse_financial_table(balance_html)
    cfs, cy, cinfo = q1.parse_financial_table(cashflow_html)
    years = sorted(set(iy) & set(by))
    out = {"v": "v3.1", "profile": None, "metrics": {}, "scores": {}, "q": None, "coverage_pct": 0, "flags": [], "warnings": [],
           "display": "n/a", "details": {}}
    if len(years) < 5:
        out["warnings"].append("history too short: {} common FY".format(len(years)))
        return out
    detected, reason = detect_profile(inc)
    prof = profile or detected
    out["profile"], out["details"]["profile_reason"] = prof, reason
    last = years[-1]
    last8, last5, last3 = years[-8:], years[-5:], years[-3:]
    m, det = {}, {}

    rev = {y: q1._g(inc, "Revenue", y) for y in years}
    # --- revenue CAGR and worst year
    span_years = [y for y in years[-6:] if rev.get(y)]
    if len(span_years) >= 5:
        m["rev_cagr5"] = _cagr(rev[span_years[0]], rev[span_years[-1]], span_years[-1] - span_years[0])
        det["rev_cagr5"] = {"first_year": span_years[0], "last_year": span_years[-1], "first": rev[span_years[0]], "last": rev[span_years[-1]]}
        yoy = {span_years[i]: 100.0 * (rev[span_years[i]] / rev[span_years[i - 1]] - 1.0) for i in range(1, len(span_years)) if span_years[i] - span_years[i - 1] == 1}
        if len(yoy) >= 4:
            worst_year = min(yoy, key=yoy.get)
            m["rev_worst"] = yoy[worst_year]
            det["rev_worst"] = {"yoy": {str(k): round(v, 1) for k, v in yoy.items()}, "year": worst_year}

    # --- EPS CAGR (3Y-averaged endpoints, else single years), both endpoints must be positive
    eps = {y: q1._g(inc, "EPS Diluted", y) for y in years}
    e_end = [eps[y] for y in years[-3:] if eps.get(y) is not None]
    start_years = [last - 7, last - 6, last - 5]
    e_start = [eps[y] for y in start_years if eps.get(y) is not None]
    if len(e_end) == 3 and len(e_start) == 3:
        m["eps_cagr5"] = _cagr(_avg(e_start), _avg(e_end), 5)
        det["eps_cagr5"] = {"basis": "3Y averages", "start_years": start_years, "start": _avg(e_start), "end": _avg(e_end)}
    elif eps.get(last) is not None and eps.get(last - 5) is not None:
        m["eps_cagr5"] = _cagr(eps[last - 5], eps[last], 5)
        det["eps_cagr5"] = {"basis": "single years", "start_years": [last - 5], "start": eps[last - 5], "end": eps[last]}
    if m.get("eps_cagr5") is None and "eps_cagr5" in det:
        det["eps_cagr5"]["unavailable"] = "non-positive endpoint"

    # --- returns
    ni = {y: q1._g(inc, "Net Income", y) for y in years}
    if prof == "NF":
        raw, inputs = _roic_series(inc, bal, last8)
        page3, _ = q1.roic3y_from_page(profitability_html)
        last3_vals = [raw[y] for y in last3 if y in raw]
        comp3 = _avg(last3_vals) if len(last3_vals) == 3 else None
        scale = None
        if page3 is not None and comp3 is not None and page3 > 0 and comp3 > 0:
            scale = min(3.0, max(0.3, page3 / comp3))
        sc = scale if scale is not None else 1.0
        series = {y: v * sc for y, v in raw.items()}
        vals5 = [series[y] for y in last5 if y in series]
        if len(vals5) >= 4:
            m["roic_med5"] = statistics.median(vals5)
        vals8 = [series[y] for y in last8 if y in series]
        if len(vals8) >= 5:
            m["roic_persist"] = 100.0 * sum(1 for v in vals8 if v >= PERSIST_HURDLE) / len(vals8)
        det["roic"] = {"series": {str(y): round(v, 1) for y, v in series.items()}, "scale": scale, "page3y": page3, "computed3y": comp3,
                       "years_med": [y for y in last5 if y in series], "years_persist": [y for y in last8 if y in series]}
        om = [100.0 * q1._g(inc, "Operating Income", y) / rev[y] for y in last3 if q1._g(inc, "Operating Income", y) is not None and rev.get(y)]
        if len(om) == 3:
            m["op_margin3"] = _avg(om)
    else:
        roe = {}
        for y in last8:
            e0, e1, n = q1._g(bal, "Total Equity", y - 1), q1._g(bal, "Total Equity", y), ni.get(y)
            if None not in (e0, e1, n) and (e0 + e1) > 0:
                roe[y] = 100.0 * n / ((e0 + e1) / 2.0)
        vals3 = [roe[y] for y in last3 if y in roe]
        if len(vals3) == 3:
            m["roe3"] = _avg(vals3)
        if len(roe) >= 5:
            m["roe_persist"] = 100.0 * sum(1 for v in roe.values() if v >= PERSIST_HURDLE) / len(roe)
        det["roe"] = {"series": {str(y): round(v, 1) for y, v in roe.items()}}
        pm = [100.0 * q1._g(inc, "Pre-Tax Income", y) / rev[y] for y in last3 if q1._g(inc, "Pre-Tax Income", y) is not None and rev.get(y)]
        if len(pm) == 3:
            m["pt_margin3"] = _avg(pm)
        eq, ta = q1._g(bal, "Total Equity", last), q1._g(bal, "Total Assets", last)
        if eq is not None and ta:
            m["eq_assets"] = 100.0 * eq / ta
            det["eq_assets"] = {"year": last, "equity": eq, "assets": ta}

    # --- v1 numbers reused: share-count CAGR, leverage and cash-conversion warnings, the old Struct for comparison
    v1 = q1.compute_metrics(profitability_html, income_html, balance_html, cashflow_html)
    m["shr_cagr"] = v1["metrics"].get("shr_cagr")
    det["shr_cagr"] = (v1.get("details") or {}).get("shr_cagr")
    out["v1"] = {"struct": v1["partial_structural"], "coverage_pct": v1["coverage_pct"], "flags": v1["flags"], "metrics": v1["metrics"]}

    spec = SPEC_NF if prof == "NF" else SPEC_FIN
    scores = {k: q1.lin(m.get(k), lo, hi) for k, w, lo, hi in spec}
    total_w = sum(w for _, w, _, _ in spec)
    avail_w = sum(w for k, w, _, _ in spec if scores[k] is not None)
    q = (sum(w * scores[k] for k, w, _, _ in spec if scores[k] is not None) / avail_w) if avail_w else None
    coverage = avail_w / total_w
    ret_key = "roic_med5" if prof == "NF" else "roe3"

    # --- caps
    flags = []
    losses = [y for y in last5 if ni.get(y) is not None and ni[y] <= 0]
    if len(losses) >= 2:
        flags.append("net loss {} of 5y".format(len(losses)))
    if m.get("shr_cagr") is not None and m["shr_cagr"] > 5:
        flags.append("dilution>5%/yr")
    if m.get("rev_cagr5") is not None and m["rev_cagr5"] < 0:
        flags.append("revenue CAGR<0")
    mg = m.get("op_margin3") if prof == "NF" else m.get("pt_margin3")
    if mg is not None and mg < 0:
        flags.append("margin<0")

    # --- warnings (never change the score)
    warns = []
    v1m = v1["metrics"]
    if prof == "NF":
        if v1m.get("nd_ebitda") is not None and v1m["nd_ebitda"] > 4:
            warns.append("ND/EBITDA>4")
        if "EBITDA<=0" in v1["flags"]:
            warns.append("EBITDA<=0")
        op, intr = q1._g(inc, "Operating Income", last), q1._g(inc, "Interest Expense", last)
        if op is not None and intr:
            cover = op / abs(intr)
            det["interest_cover"] = round(cover, 2)
            if cover < 2:
                warns.append("interest cover<2x")
    else:
        warns.append("financial: rate-sensitive earnings, no regulatory capital data")
    cn = v1m.get("cfo_ni")
    if cn is not None and (cn < 0.6 or cn > 3):
        warns.append("CFO/NI {:.1f}".format(cn))
    gw, ta = q1._g(bal, "Goodwill", last), q1._g(bal, "Total Assets", last)
    if gw is not None and ta:
        det["goodwill_pct"] = round(100.0 * gw / ta, 1)
        if gw / ta > 0.5:
            warns.append("goodwill>50% of assets")
    if (det.get("shr_cagr") or {}).get("restarted"):
        warns.append("share-count jump>30% (split or issuance?)")

    shown = None if q is None else (min(q, 50.0) if flags else q)
    out.update({
        "metrics": {k: (None if v is None else round(v, 2)) for k, v in m.items()},
        "scores": {k: (None if v is None else round(v, 1)) for k, v in scores.items()},
        "q": None if q is None else round(q, 1), "q_capped": None if shown is None else round(shown, 1),
        "coverage_pct": round(coverage * 100), "flags": flags, "warnings": warns,
        "weights": {k: w for k, w, _, _ in spec}, "details": det,
        "display": "n/a (cov %d%%)" % round(coverage * 100) if (coverage < 0.7 or scores.get(ret_key) is None or shown is None)
                   else "%d | cov %d%%" % (round(shown), round(coverage * 100)),
    })
    return out
