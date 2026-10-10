"""
as_quality_metrics.py v5 -- six STRUCTURAL quality metrics from AlphaSpread pages (STD profile).

  Q1 ROIC 3Y average      profitability page text ("3Y Average ROIC"); falls back to the computed value
  Q2 Worst-year ROIC      second-lowest yearly ROIC of the last 5 FY (ROIC_MIN_RANK = 2; 1 = the very worst), computed from the statements
                          and scaled so the last-3-year average equals the page value (v4, ROIC_CALIBRATE_TO_PAGE)
  Q6 Cash conversion      sum(cash from operations) / sum(net income), last 5 FY (both from the cash-flow page)
  Q8 Net debt / EBITDA    latest FY; EBITDA = operating income + D&A (cash-flow page)
  Q10 FCF-positive years  of the last 5 FY (FCF = cash from operations - |capex|)
  Q11 Share-count CAGR    Common Shares Outstanding, last 5 intervals; restarts after a >30% yearly jump

Pure functions, no browser. Input = the HTML of 5 pages (profitability, income-statement, balance-sheet,
cash-flow-statement). Output = a dict with raw metrics, 0-100 scores, coverage, flags and diagnostics.
ROIC rule (ONE rule, change the constants below to change it everywhere):
  NOPAT = operating income * (1 - tax rate), tax rate = |tax provision| / pre-tax income clamped to 15-30%
  invested capital (year end) = total equity + minority interest + debt + leases (cash is NOT subtracted)
  v2: cash is no longer netted (ROIC_SUBTRACT_CASH = False). AlphaSpread's own ROIC appears to be built that way
  (Alibaba page ROIC 3% vs ~3% from equity+debt; Nike page 12% vs ~14%), and Q1 uses the page value, so Q2 must
  use the same basis. The net-of-cash series is still reported in diagnostics ('roic_by_year_net_of_cash').
  goodwill is KEPT, long-term investments are NOT stripped (STRIP_LONG_TERM_INVESTMENTS = False).
"""
import re
from html.parser import HTMLParser

STRIP_LONG_TERM_INVESTMENTS = False
ROIC_SUBTRACT_CASH = False   # v2: same basis as AlphaSpread's own ROIC (see docstring)
ROIC_CALIBRATE_TO_PAGE = True  # v4: scale the computed ROIC series so its last-3-year average equals the page value
ROIC_MIN_RANK = 2            # v3: 1 = worst year of the last 5, 2 = second-worst (robust to one shock year such as COVID); chosen by the user
TAX_MIN, TAX_MAX, TAX_DEFAULT = 0.15, 0.30, 0.21
SHARE_JUMP_LIMIT = 0.30

# STD profile anchors (lo -> 0 points, hi -> 100 points) and weights, from the brief
SCORE_SPEC = {
    "roic3y":       {"lo": 8.0,  "hi": 25.0, "w": 20},
    "roic_min5":    {"lo": 5.0,  "hi": 18.0, "w": 10},
    "cfo_ni":       {"lo": 0.7,  "hi": 1.2,  "w": 8},
    "nd_ebitda":    {"lo": 3.5,  "hi": 0.0,  "w": 10},
    "fcf_years":    {"lo": 0.0,  "hi": 5.0,  "w": 5},
    "shr_cagr":     {"lo": 3.0,  "hi": -2.0, "w": 10},
}


# ----------------------------------------------------------------------------- parsing
class _Tables(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables, self._t, self._r, self._c = [], None, None, None

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self._t = []
        elif tag == "tr" and self._t is not None:
            self._r = []
        elif tag in ("td", "th") and self._r is not None:
            self._c = []

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._c is not None and self._r is not None:
            self._r.append(re.sub(r"\s+", " ", "".join(self._c)).strip())
            self._c = None
        elif tag == "tr" and self._r is not None and self._t is not None:
            if self._r:
                self._t.append(self._r)
            self._r = None
        elif tag == "table" and self._t is not None:
            self.tables.append(self._t)
            self._t = None

    def handle_data(self, data):
        if self._c is not None:
            self._c.append(data)


def parse_value(text):
    """'(86B)' -> -86e9, '131.5B' -> 131.5e9, '1m' -> 1e6, '1.1T', '-', '—' -> None, '12%' -> 12.0"""
    s = (text or "").strip().replace(",", "").replace("$", "").replace("¥", "")
    if s in ("", "-", "—", "–", "N/A", "n/a", "NaN"):
        return None
    neg = (s.startswith("(") and s.endswith(")")) or s.startswith("-") or s.startswith("−")
    m = re.search(r"(\d+(?:\.\d+)?)\s*([TBMKmk]?)", s)
    if not m:
        return None
    value = float(m.group(1)) * {"T": 1e12, "B": 1e9, "M": 1e6, "m": 1e6, "K": 1e3, "k": 1e3, "": 1}[m.group(2)]
    return -value if neg else value


def parse_financial_table(html):
    """Returns ({label: {year:int -> value}}, years_sorted, info). Picks the table with the most FYxxxx headers."""
    parser = _Tables()
    parser.feed(html or "")
    best = None
    for table in parser.tables:
        for row in table[:3]:
            years = [re.search(r"FY\s*(\d{4})", c) for c in row]
            count = sum(1 for y in years if y)
            if count >= 4 and (best is None or count > best[0]):
                best = (count, table, row)
                break
    if best is None:
        return {}, [], {"error": "no table with FY headers"}
    _, table, header = best
    col_year = {}
    for index, cell in enumerate(header):
        m = re.search(r"FY\s*(\d{4})", cell)
        if m:
            col_year[index] = int(m.group(1))
    rows = {}
    for row in table:
        if not row or row is header:
            continue
        label = row[0]
        if not label or label in rows:
            continue
        rows[label] = {col_year[i]: parse_value(row[i]) for i in col_year if i < len(row)}
    years = sorted(set(col_year.values()))
    info = {"columns": len(header), "years": years, "rows": len(rows)}
    if len(header) > 14:
        info["warning"] = "more than 14 columns: probably a quarterly/TTM layout, not handled"
    return rows, years, info


def strip_text(html):
    html = re.sub(r"(?is)<(script|style|noscript).*?</\1>", " ", html or "")
    html = re.sub(r"(?s)<[^>]+>", " ", html)
    import html as _h
    return re.sub(r"\s+", " ", _h.unescape(html)).strip()


def roic3y_from_page(profitability_html):
    """The page shows 'Low 3Y Average ROIC' with a percentage; layout (number before or after the label)
    is not known, so the NEAREST percentage to the label wins and the snippet is returned for checking."""
    text = strip_text(profitability_html)
    label = "3Y Average ROIC"
    i = text.find(label)
    if i < 0:
        return None, "label '3Y Average ROIC' not found"
    after = text[i + len(label): i + len(label) + 40]
    before = text[max(0, i - 24): i]
    candidates = []
    m = re.search(r"(-?\d+(?:\.\d+)?)\s*%", after)
    if m:
        candidates.append((m.start(), float(m.group(1)), "after"))
    m = re.search(r"(-?\d+(?:\.\d+)?)\s*%((?:\s*[A-Za-z]+){0,2}\s*)$", before)
    if m:
        candidates.append((len(m.group(2)), float(m.group(1)), "before"))
    snippet = text[max(0, i - 24): i + len(label) + 40]
    if not candidates:
        return None, "no % near label: " + snippet
    gap, value, side = sorted(candidates, key=lambda c: c[0])[0]
    return value, "%s: %s" % (side, snippet)


# ----------------------------------------------------------------------------- computation
def _g(rows, label, year):
    series = rows.get(label)
    return None if series is None else series.get(year)


def _first(rows, labels, year):
    for label in labels:
        v = _g(rows, label, year)
        if v is not None:
            return v
    return None


def _lease_total(rows, year):
    total, found = 0.0, False
    for label, series in rows.items():
        low = label.lower()
        if "lease" in low and "receivable" not in low and series.get(year) is not None:
            total += series[year]
            found = True
    return total if found else 0.0


def lin(x, lo, hi):
    if x is None:
        return None
    t = (x - lo) / (hi - lo)
    return 100.0 * max(0.0, min(1.0, t))


def compute_metrics(profitability_html, income_html, balance_html, cashflow_html):
    inc, inc_years, inc_info = parse_financial_table(income_html)
    bal, bal_years, bal_info = parse_financial_table(balance_html)
    cfs, cfs_years, cfs_info = parse_financial_table(cashflow_html)
    diag = {"income": inc_info, "balance": bal_info, "cashflow": cfs_info, "notes": []}
    common = sorted(set(inc_years) & set(bal_years) & set(cfs_years))
    last5 = common[-5:]
    latest = common[-1] if common else None
    diag["last5"] = last5
    details = {}   # v5: the numbers behind every cell, for the cell notes

    # --- yearly ROIC (chosen basis in roic_by_year, the other one only for diagnostics)
    roic_by_year, roic_net_cash, roic_inputs = {}, {}, {}
    for y in last5 + ([common[-6]] if len(common) >= 6 else []):
        op = _g(inc, "Operating Income", y)
        pre = _g(inc, "Pre-Tax Income", y)
        tax = _g(inc, "Tax Provision", y)
        equity = _g(bal, "Total Equity", y)
        minority = _g(bal, "Minority Interest", y) or 0.0
        debt = sum(_g(bal, l, y) or 0.0 for l in ("Short-Term Debt", "Current Portion of Long-Term Debt", "Long-Term Debt"))
        cash = (_first(bal, ["Cash & Cash Equivalents", "Cash Equivalents"], y) or 0.0) + (_g(bal, "Short-Term Investments", y) or 0.0)
        if None in (op, equity):
            continue
        rate = abs(tax) / pre if (tax is not None and pre and pre > 0) else TAX_DEFAULT
        rate = max(TAX_MIN, min(TAX_MAX, rate))
        gross = equity + minority + debt + _lease_total(bal, y)
        if STRIP_LONG_TERM_INVESTMENTS:
            gross -= _g(bal, "Long-Term Investments", y) or 0.0
        nopat = op * (1 - rate)
        roic_inputs[y] = {"op": op, "tax_rate": round(rate, 4), "capital": gross}
        if gross > 0:
            roic_by_year[y] = nopat / gross * 100.0
        if gross - cash > 0:
            roic_net_cash[y] = nopat / (gross - cash) * 100.0
    if ROIC_SUBTRACT_CASH:
        roic_by_year = roic_net_cash
    diag["roic_by_year"] = {y: round(v, 1) for y, v in roic_by_year.items()}
    diag["roic_by_year_net_of_cash"] = {y: round(v, 1) for y, v in roic_net_cash.items()}
    window = [roic_by_year[y] for y in last5 if y in roic_by_year]
    last3 = [roic_by_year[y] for y in last5[-3:] if y in roic_by_year]
    roic3_computed = sum(last3) / len(last3) if len(last3) == 3 else None
    diag["roic3y_computed"] = None if roic3_computed is None else round(roic3_computed, 1)

    roic3_page, note = roic3y_from_page(profitability_html)
    diag["roic3y_page_note"] = note
    roic3y = roic3_page if roic3_page is not None else roic3_computed
    diag["roic3y_source"] = "page" if roic3_page is not None else ("computed" if roic3_computed is not None else None)

    # v4: calibrate the computed yearly series to the page's 3Y average, so that Q2 (worst year) sits on the same
    # basis as Q1. Without it Q2 could exceed Q1 (Autodesk: page 15.0, computed worst year 20.7). The factor is
    # skipped when either average is <= 0 (a ratio of such values is meaningless) and clamped to 0.3 - 3.
    roic_scale = None
    if ROIC_CALIBRATE_TO_PAGE and roic3_page is not None and roic3_computed is not None \
            and roic3_page > 0 and roic3_computed > 0:
        roic_scale = min(3.0, max(0.3, roic3_page / roic3_computed))
        window = [v * roic_scale for v in window]
    diag["roic_scale"] = None if roic_scale is None else round(roic_scale, 3)
    diag["roic_by_year_calibrated"] = None if roic_scale is None else {y: round(v * roic_scale, 1) for y, v in roic_by_year.items()}
    roic_min5 = sorted(window)[ROIC_MIN_RANK - 1] if len(window) >= max(3, ROIC_MIN_RANK + 1) else None
    _sc = roic_scale if roic_scale is not None else 1.0
    _years5 = [y for y in last5 if y in roic_by_year]
    details["roic"] = {
        "years": _years5,
        "inputs": {str(y): roic_inputs.get(y) for y in _years5},
        "raw": {str(y): round(roic_by_year[y], 2) for y in _years5},
        "scaled": {str(y): round(roic_by_year[y] * _sc, 2) for y in _years5},
        "scale": roic_scale, "page3y": roic3_page, "computed3y": roic3_computed,
        "rank": ROIC_MIN_RANK,
        "pick_year": None if roic_min5 is None else next((y for y in _years5 if abs(roic_by_year[y] * _sc - roic_min5) < 1e-9), None),
    }

    # --- cash conversion (cash-flow page only: same consolidated net income as CFO starts from)
    cfo = [_g(cfs, "Cash from Operating Activities", y) for y in last5]
    ni = [_g(cfs, "Net Income", y) for y in last5]
    cfo_ni = None
    if len(last5) == 5 and None not in cfo and None not in ni and sum(ni) > 0:
        cfo_ni = sum(cfo) / sum(ni)
        details["cfo_ni"] = {"years": list(last5), "cfo": list(cfo), "ni": list(ni), "cfo_sum": sum(cfo), "ni_sum": sum(ni)}

    # --- net debt / EBITDA, latest FY
    nd_ebitda, nd_note = None, None
    if latest is not None:
        debt = sum(_g(bal, l, latest) or 0.0 for l in ("Short-Term Debt", "Current Portion of Long-Term Debt", "Long-Term Debt")) + _lease_total(bal, latest)
        cash = (_first(bal, ["Cash & Cash Equivalents", "Cash Equivalents"], latest) or 0.0) + (_g(bal, "Short-Term Investments", latest) or 0.0)
        op = _g(inc, "Operating Income", latest)
        da = _g(cfs, "Depreciation & Amortization", latest)
        net_debt = debt - cash
        details["nd_ebitda"] = {"year": latest, "debt": debt, "leases": _lease_total(bal, latest), "cash": cash, "net_debt": net_debt, "op": op, "da": da}
        diag["net_debt"] = net_debt
        if op is not None and da is not None:
            ebitda = op + da
            details["nd_ebitda"]["ebitda"] = ebitda
            diag["ebitda"] = ebitda
            if net_debt <= 0:
                nd_ebitda, nd_note = net_debt / ebitda if ebitda > 0 else -1.0, "net cash"
            elif ebitda > 0:
                nd_ebitda = net_debt / ebitda
            else:
                nd_note = "EBITDA <= 0"

    # --- FCF-positive years
    positives, known = 0, 0
    fcf_rows = []
    for y in last5:
        c, cap = _g(cfs, "Cash from Operating Activities", y), _g(cfs, "Capital Expenditures", y)
        if c is None or cap is None:
            continue
        known += 1
        positives += 1 if c - abs(cap) > 0 else 0
        fcf_rows.append({"year": y, "cfo": c, "capex": abs(cap), "fcf": c - abs(cap)})
    fcf_years = positives if (len(last5) == 5 and known >= 4) else None
    diag["fcf_years_known"] = known
    details["fcf_years"] = {"rows": fcf_rows, "known": known}

    # --- share count CAGR (restarts after a break)
    shr_cagr, shares_used = None, []
    series = [(y, _g(bal, "Common Shares Outstanding", y)) for y in (common[-6:] if len(common) >= 6 else common)]
    series = [(y, v) for y, v in series if v and v > 0]
    segment = []
    for y, v in series:
        if segment and abs(v / segment[-1][1] - 1.0) > SHARE_JUMP_LIMIT:
            diag["notes"].append("share count jump >30%% before FY%d: segment restarted" % y)
            segment = []
        segment.append((y, v))
    shares_used = [y for y, _ in segment]
    if len(segment) >= 3:
        n = segment[-1][0] - segment[0][0]
        shr_cagr = ((segment[-1][1] / segment[0][1]) ** (1.0 / n) - 1.0) * 100.0
    diag["shares_years"] = shares_used
    details["shr_cagr"] = {"first_year": segment[0][0] if segment else None, "last_year": segment[-1][0] if segment else None,
                           "first": segment[0][1] if segment else None, "last": segment[-1][1] if segment else None,
                           "points": len(segment), "restarted": any("share count jump" in n_ for n_ in diag["notes"])}

    metrics = {"roic3y": roic3y, "roic_min5": roic_min5, "cfo_ni": cfo_ni,
               "nd_ebitda": nd_ebitda, "fcf_years": fcf_years, "shr_cagr": shr_cagr}
    scores = {}
    for key, spec in SCORE_SPEC.items():
        x = metrics[key]
        if key == "nd_ebitda" and x is not None and x <= 0:
            scores[key] = 100.0                      # net cash or no debt
        elif key == "nd_ebitda" and x is None and nd_note == "EBITDA <= 0":
            scores[key] = 0.0
        else:
            scores[key] = lin(x, spec["lo"], spec["hi"])
    total_w = sum(s["w"] for s in SCORE_SPEC.values())
    avail_w = sum(SCORE_SPEC[k]["w"] for k, v in scores.items() if v is not None)
    structural = (sum(SCORE_SPEC[k]["w"] * v for k, v in scores.items() if v is not None) / avail_w) if avail_w else None
    coverage = avail_w / total_w
    details["struct"] = {"weights": {k: v["w"] for k, v in SCORE_SPEC.items()}, "avail_w": avail_w, "total_w": total_w,
                         "points": {k: (None if scores[k] is None else round(SCORE_SPEC[k]["w"] * scores[k] / avail_w, 2)) for k in SCORE_SPEC} if avail_w else {}}

    flags = []
    if nd_ebitda is not None and nd_ebitda > 4: flags.append("ND/EBITDA>4")
    if nd_note == "EBITDA <= 0": flags.append("EBITDA<=0")
    if shr_cagr is not None and shr_cagr > 5: flags.append("dilution>5%/yr")
    if cfo_ni is not None and cfo_ni < 0.6: flags.append("CFO/NI<0.6")
    if fcf_years is not None and fcf_years <= 2: flags.append("FCF neg 3 of 5y")
    returns_available = scores["roic3y"] is not None or scores["roic_min5"] is not None
    return {
        "metrics": {k: (None if v is None else round(v, 3)) for k, v in metrics.items()},
        "scores": {k: (None if v is None else round(v, 1)) for k, v in scores.items()},
        "partial_structural": None if structural is None else round(structural, 1),
        "coverage_pct": round(coverage * 100),
        "display": "n/a (cov %d%%)" % round(coverage * 100) if (coverage < 0.7 or not returns_available or structural is None)
                   else "%d | cov %d%% | flags: %s" % (round(min(structural, 50) if flags else structural), round(coverage * 100), ", ".join(flags) or "none"),
        "flags": flags,
        "details": details,
        "diagnostics": diag,
    }
