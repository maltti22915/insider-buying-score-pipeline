"""
as_quality_v3.py v1.1 (EPS label "EPS (Diluted)", profile detection by balance-sheet cash share, revenue base-effect warning) -- "Q v3": seven (non-financial) or eight (financial) past-quality metrics from the same four AlphaSpread pages.
Pure functions, no browser. Reuses the parsers and the ROIC rule of as_quality_metrics.py (v1 "Struct" is computed alongside for comparison).

Non-financial profile (weights sum to 100; score = linear lo -> 0 pts, hi -> 100 pts):
  roic_med5     ROIC, median of the last 5 FY (own yearly series, NOT scaled in v5)                 8% -> 25%     w25
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

v4 changes vs v3 (second-opinion review, Oct 2026): rev_cagr9 added (base effects), roic_persist weight 8->5, revenue CAGR<0 is a warning (no cap),
financial profile: ni_resil (net-income volatility, 15) added and Q capped at 60 (FIN_CAP), net-interest-income share of pre-tax income as diagnostic,
diagnostics for every profile: ROIC with SBC added back, SBC / revenue, ROIC net of cash (roic_mode="cash" scores that variant instead of GAAP).

v5 changes vs v4 (review of Oct 12 2026): (1) ROIC series is no longer multiplied by page 3Y ROIC / computed 3Y ROIC (the factor was 0.7-2.2 and went in
different directions per company); the page value stays as a comparison in details.roic.page3y and page_ratio. (2) rev_cagr9 needs nine elapsed years
(FY first -> FY last >= 9), otherwise it is missing and the weights are rescaled. (3) Capital = equity + minority interest + debt + lease rows ONLY if the
balance sheet has a lease line; AlphaSpread's balance sheets for the 15 test companies have none, so leases are NOT included and ROIC is somewhat overstated
for lease-heavy companies.
"""
import statistics
import as_quality_metrics as q1

SPEC_NF = [("roic_med5", 25, 8.0, 25.0), ("roic_persist", 5, 25.0, 100.0), ("op_margin3", 12, 5.0, 25.0),
           ("rev_cagr5", 16, 2.0, 14.0), ("rev_cagr9", 6, 0.0, 10.0), ("rev_worst", 10, -8.0, 4.0), ("eps_cagr5", 14, 3.0, 15.0), ("shr_cagr", 12, 3.0, -2.0)]
SPEC_FIN = [("roe3", 20, 8.0, 20.0), ("roe_persist", 5, 25.0, 100.0), ("pt_margin3", 10, 15.0, 40.0), ("rev_cagr5", 12, 2.0, 14.0),
            ("rev_worst", 8, -8.0, 4.0), ("eps_cagr5", 12, 3.0, 15.0), ("shr_cagr", 10, 3.0, -2.0), ("eq_assets", 8, 3.0, 15.0),
            ("ni_resil", 15, 1.0, 0.1)]
FIN_CAP = 60.0
PERSIST_HURDLE = 10.0
FIN_NAME_HINTS = ("loan", "deposit")


def _years_ok(table, label, years):
    return [y for y in years if (table.get(label) or {}).get(y) is not None]


def detect_profile(inc, bal=None, year=None):
    """FIN when the statements look like a bank / broker / insurer, else NF.
    - no Gross Profit / Cost of Revenue values AND no Operating Income values  (banks, pure insurers)
    - cash + short-term investments >= 50% of total assets                      (brokers such as flatexDEGIRO: client cash)
    - a row name containing loan / deposit
    Managed-care style statements (insurance rows but an Operating Income line, e.g. UnitedHealth) stay NF; pass profile= to override."""
    def has(table, label):
        return any(v is not None for v in (table.get(label) or {}).values())
    has_gross = has(inc, "Gross Profit") and has(inc, "Cost of Revenue")
    has_op = has(inc, "Operating Income")
    hint = next((l for l in inc if any(h in l.lower() for h in FIN_NAME_HINTS)), None)
    if hint:
        return "FIN", "row '{}'".format(hint)
    if not has_gross and not has_op:
        return "FIN", "no Gross Profit and no Operating Income values"
    if bal is not None and year is not None:
        ta = (bal.get("Total Assets") or {}).get(year)
        cash = ((bal.get("Cash & Cash Equivalents") or {}).get(year) or 0.0) + ((bal.get("Short-Term Investments") or {}).get(year) or 0.0)
        if ta and cash / ta >= 0.5:
            return "FIN", "cash and short-term investments {:.0f}% of total assets".format(100.0 * cash / ta)
    return "NF", "operating statements"


def _roic_series(inc, bal, years, add_sbc=None, net_cash=False):
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
        if net_cash:
            capital -= (q1._first(bal, ["Cash & Cash Equivalents", "Cash Equivalents"], y) or 0.0) + (q1._g(bal, "Short-Term Investments", y) or 0.0)
        if add_sbc:
            op = op + abs(add_sbc.get(y) or 0.0)
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


def compute_v4(profitability_html, income_html, balance_html, cashflow_html, profile=None, roic_mode="gaap"):
    inc, iy, iinfo = q1.parse_financial_table(income_html)
    bal, by, binfo = q1.parse_financial_table(balance_html)
    cfs, cy, cinfo = q1.parse_financial_table(cashflow_html)
    years = sorted(set(iy) & set(by))
    out = {"v": "v5.0", "profile": None, "metrics": {}, "scores": {}, "q": None, "coverage_pct": 0, "flags": [], "warnings": [],
           "display": "n/a", "details": {}}
    if len(years) < 5:
        out["warnings"].append("history too short: {} common FY".format(len(years)))
        return out
    detected, reason = detect_profile(inc, bal, years[-1])
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

    long_years = [y for y in years if rev.get(y)]
    if m.get("rev_cagr5") is not None and len(long_years) >= 8:
        long_cagr = _cagr(rev[long_years[0]], rev[long_years[-1]], long_years[-1] - long_years[0])
        det["rev_cagr_long"] = {"first_year": long_years[0], "last_year": long_years[-1], "cagr": long_cagr}
        if long_cagr is not None and abs(m["rev_cagr5"] - long_cagr) > 10:
            out["warnings"].append("revenue base effect: 5y {:.0f}% vs {}y {:.0f}%".format(m["rev_cagr5"], long_years[-1] - long_years[0], long_cagr))

    if len(long_years) >= 9 and long_years[-1] - long_years[0] >= 9:   # v5: nine ELAPSED years (10 fiscal years), else n/a
        m["rev_cagr9"] = _cagr(rev[long_years[0]], rev[long_years[-1]], long_years[-1] - long_years[0])
        det["rev_cagr9"] = {"first_year": long_years[0], "last_year": long_years[-1]}

    # --- EPS CAGR (3Y-averaged endpoints, else single years), both endpoints must be positive
    eps = {y: q1._first(inc, ["EPS (Diluted)", "EPS Diluted"], y) for y in years}
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
        raw, inputs = _roic_series(inc, bal, last8, net_cash=(roic_mode == "cash"))
        page3, _ = q1.roic3y_from_page(profitability_html)
        last3_vals = [raw[y] for y in last3 if y in raw]
        comp3 = _avg(last3_vals) if len(last3_vals) == 3 else None
        # v5: the series is NOT scaled to the page's 3Y ROIC any more (the factor differed in size and direction per company and
        # could not be explained). The page value is kept as a comparison only: details.roic.page3y / computed3y / page_ratio.
        scale = None
        page_ratio = (page3 / comp3) if (page3 is not None and comp3 is not None and page3 > 0 and comp3 > 0) else None
        sc = 1.0
        series = {y: v * sc for y, v in raw.items()}
        vals5 = [series[y] for y in last5 if y in series]
        if len(vals5) >= 4:
            m["roic_med5"] = statistics.median(vals5)
        vals8 = [series[y] for y in last8 if y in series]
        if len(vals8) >= 5:
            m["roic_persist"] = 100.0 * sum(1 for v in vals8 if v >= PERSIST_HURDLE) / len(vals8)
        det["roic"] = {"series": {str(y): round(v, 1) for y, v in series.items()}, "scale": None, "page_ratio": (round(page_ratio, 2) if page_ratio else None), "page3y": page3, "computed3y": comp3,
                       "years_med": [y for y in last5 if y in series], "years_persist": [y for y in last8 if y in series]}
        sbc = {y: q1._g(cfs, "Stock-Based Compensation", y) for y in years}
        if any(v is not None for v in sbc.values()):
            rs, _ = _roic_series(inc, bal, last5, add_sbc=sbc)
            rg, _ = _roic_series(inc, bal, last5)
            if len(rs) >= 4:
                det["diag_roic_sbc_med5"] = round(statistics.median(rs.values()), 1)
                det["diag_roic_gaap_unscaled_med5"] = round(statistics.median(rg.values()), 1) if rg else None
            if sbc.get(last) is not None and rev.get(last):
                det["diag_sbc_pct_rev"] = round(100.0 * abs(sbc[last]) / rev[last], 1)
        rc, _ = _roic_series(inc, bal, last5, net_cash=True)
        if len(rc) >= 4:
            det["diag_roic_netcash_med5"] = round(statistics.median(rc.values()), 1)
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
        nis = [ni[y] for y in last8 if ni.get(y) is not None]
        if len(nis) >= 5:
            mean_abs = _avg([abs(v) for v in nis])
            if mean_abs > 0:
                m["ni_resil"] = statistics.pstdev(nis) / mean_abs
        nii_hits = []
        for y in last5:
            n_, p_ = q1._g(inc, "Net Interest Income (Expense)", y), q1._g(inc, "Pre-Tax Income", y)
            if n_ is not None and p_ and p_ > 0:
                nii_hits.append(abs(n_) / p_)
        if nii_hits:
            det["diag_nii_share_pretax"] = {"avg": round(_avg(nii_hits), 2), "years_over_50pct": sum(1 for v in nii_hits if v > 0.5), "n": len(nii_hits)}
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
        out["warnings"].append("revenue CAGR<0")
    mg = m.get("op_margin3") if prof == "NF" else m.get("pt_margin3")
    if mg is not None and mg < 0:
        flags.append("margin<0")

    # --- warnings (never change the score)
    warns = list(out["warnings"])   # keep the base-effect warning added earlier
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
    if det.get("diag_sbc_pct_rev") is not None and det["diag_sbc_pct_rev"] >= 8:
        warns.append("SBC {:.0f}% of revenue".format(det["diag_sbc_pct_rev"]))
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
    if shown is not None and prof == "FIN" and shown > FIN_CAP:
        flags.append("financial cap {:.0f}".format(FIN_CAP))
        shown = FIN_CAP
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


compute_v3 = compute_v4  # alias for callers
