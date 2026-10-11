"""
as_ttm_metrics.py v1.2 (profile argument; FIN skips FCF and gross-margin signals; implausible >40pp margin changes ignored)
v1.1 (cell parts joined with a space: "TTM<br>Mar 2024" is read as "TTM Mar 2024") -- "Now" signals from AlphaSpread TTM (income statement, cash flow) and Quarterly (balance sheet) views.

Pure functions, no browser. Input = page HTML after the toggle was clicked:
  income statement  -> TTM       (header cells "TTM Jun 2026")
  cash flow         -> TTM
  balance sheet     -> Quarterly (header cells "Q2 FY2026 Jun 2026"; point-in-time, TTM does not apply)
Fiscal-year labels differ between companies, so periods are identified by the calendar "Mon YYYY" part only.

Signals (latest TTM vs the TTM window ending exactly 12 months earlier):
  rev_growth      revenue growth, %
  rev_accel       growth now minus growth one year earlier, pp (needs >= 9 TTM columns) or minus the 5y CAGR when given
  om_delta        operating margin change, pp
  gm_delta        gross margin change, pp
  fcfm_delta      change of (CFO - |capex| - stock comp) / revenue, pp
Each signal scores 0 at the weak end, 60 at "no change", 100 at the strong end (NOW_SPEC); Now = mean of available signals.
Also returns TTM levels and TTM net debt / EBITDA and interest cover (net debt from the latest quarter).
"""
import re
from html.parser import HTMLParser

NOW_SPEC = {  # (weak, strong) in pp; 0 -> 0 points, 0 change -> 60, strong -> 100
    "rev_accel":  (-5.0, 5.0),
    "om_delta":   (-4.0, 3.0),
    "gm_delta":   (-4.0, 3.0),
    "fcfm_delta": (-3.0, 2.0),
}
MONTHS = {m: i + 1 for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
PERIOD_RE = re.compile(r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(\d{4})")
DEBT_LABELS = ("Short-Term Debt", "Current Portion of Long-Term Debt", "Long-Term Debt")


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
            self._r.append(re.sub(r"\s+", " ", " ".join(self._c)).strip())
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
    s = (text or "").strip().replace(",", "").replace("$", "")
    if s in ("", "-", "—", "–", "N/A", "n/a", "NaN"):
        return None
    neg = (s.startswith("(") and s.endswith(")")) or s.startswith("-") or s.startswith("−")
    m = re.search(r"(\d+(?:\.\d+)?)\s*([TBMKmk]?)", s)
    if not m:
        return None
    value = float(m.group(1)) * {"T": 1e12, "B": 1e9, "M": 1e6, "m": 1e6, "K": 1e3, "k": 1e3, "": 1}[m.group(2)]
    return -value if neg else value


def _period_of(cell, kind):
    """(year, month) of a header cell of the wanted kind, else None."""
    c = cell or ""
    if kind == "ttm" and not re.match(r"\s*TTM", c):
        return None
    if kind == "q" and not re.match(r"\s*Q\d\s*FY", c):
        return None
    m = PERIOD_RE.search(c)
    return (int(m.group(2)), MONTHS[m.group(1).lower()]) if m else None


def parse_period_table(html, kind):
    """kind 'ttm' | 'q'. Returns ({label: {(year, month): value}}, periods_sorted, info)."""
    parser = _Tables()
    parser.feed(html or "")
    best = None
    for table in parser.tables:
        for row in table[:3]:
            periods = [_period_of(c, kind) for c in row]
            count = sum(1 for p in periods if p)
            if count >= 2 and (best is None or count > best[0]):
                best = (count, table, row, periods)
                break
    if best is None:
        return {}, [], {"error": "no table with {} headers".format(kind.upper())}
    _, table, header, periods = best
    cols = {i: p for i, p in enumerate(periods) if p}
    rows = {}
    for row in table:
        if not row or row is header:
            continue
        label = row[0]
        if not label or label in rows:
            continue
        rows[label] = {cols[i]: parse_value(row[i]) for i in cols if i < len(row)}
    plist = sorted(set(cols.values()))
    return rows, plist, {"columns": len(header), "periods": plist, "rows": len(rows)}


def _months(p):
    return p[0] * 12 + p[1]


def _shift(p, months):
    total = _months(p) - 1 + months
    return (total // 12, total % 12 + 1)


def _lease_total(rows, period):
    total, found = 0.0, False
    for label, series in rows.items():
        low = label.lower()
        if "lease" in low and "receivable" not in low and series.get(period) is not None:
            total += series[period]
            found = True
    return total if found else 0.0


def _g(rows, label, period):
    s = rows.get(label)
    return None if s is None else s.get(period)


def _first(rows, labels, period):
    for l in labels:
        v = _g(rows, l, period)
        if v is not None:
            return v
    return None


def score_signal(x, weak, strong):
    """0 at weak, 60 at 0, 100 at strong (linear on each side)."""
    if x is None:
        return None
    if x <= weak:
        return 0.0
    if x >= strong:
        return 100.0
    return 60.0 * (x - weak) / (0.0 - weak) if x < 0 else 60.0 + 40.0 * x / strong


def _margin(num, rev):
    return None if num is None or not rev else 100.0 * num / rev


def _fcf_sbc(cfs, p):
    cfo = _g(cfs, "Cash from Operating Activities", p)
    capex = _g(cfs, "Capital Expenditures", p)
    sbc = _g(cfs, "Stock-Based Compensation", p) or 0.0
    if cfo is None or capex is None:
        return None
    return cfo - abs(capex) - abs(sbc)


def _window(inc, cfs, p):
    rev = _g(inc, "Revenue", p)
    gp = _g(inc, "Gross Profit", p)
    op = _g(inc, "Operating Income", p)
    return {"revenue": rev, "gross_profit": gp, "operating_income": op, "fcf_after_sbc": _fcf_sbc(cfs, p),
            "gm": _margin(gp, rev), "om": _margin(op, rev), "fcfm": _margin(_fcf_sbc(cfs, p), rev)}


def compute_now(income_ttm_html, cashflow_ttm_html, balance_q_html, rev_cagr5_pct=None, profile="NF"):
    out = {"signals": {}, "scores": {}, "levels": {}, "now": None, "warnings": [], "details": {}}
    inc, ip, iinfo = parse_period_table(income_ttm_html, "ttm")
    cfs, cp, cinfo = parse_period_table(cashflow_ttm_html, "ttm")
    bal, bp, binfo = parse_period_table(balance_q_html, "q")
    for name, info in (("income", iinfo), ("cashflow", cinfo), ("balance", binfo)):
        if info.get("error"):
            out["warnings"].append("{}: {}".format(name, info["error"]))
    if not ip or not cp:
        out["warnings"].append("TTM tables missing: no Now score")
        return out
    latest = ip[-1]
    if cp[-1] != latest:
        out["warnings"].append("income TTM ends {} but cash flow TTM ends {}".format(latest, cp[-1]))
        latest = min(latest, cp[-1])
    out["details"]["latest"] = latest
    prev = _shift(latest, -12)
    prev2 = _shift(latest, -24)
    now_w, prev_w = _window(inc, cfs, latest), _window(inc, cfs, prev)
    out["levels"] = {"revenue_ttm": now_w["revenue"], "gm": now_w["gm"], "om": now_w["om"], "fcfm_after_sbc": now_w["fcfm"]}
    if prev not in ip:
        out["warnings"].append("no TTM window 12 months before {}: no change signals".format(latest))
        return out
    sig = out["signals"]
    if now_w["revenue"] and prev_w["revenue"]:
        growth = 100.0 * (now_w["revenue"] / prev_w["revenue"] - 1.0)
        sig["rev_growth"] = growth
        base = None
        if rev_cagr5_pct is not None:
            base, how = rev_cagr5_pct, "5y CAGR"
        elif prev2 in ip:
            r2 = _g(inc, "Revenue", prev2)
            if r2:
                base, how = 100.0 * (prev_w["revenue"] / r2 - 1.0), "growth one year earlier"
        if base is not None:
            sig["rev_accel"] = growth - base
            out["details"]["rev_accel_vs"] = how
    for key, name in (("om_delta", "om"), ("gm_delta", "gm"), ("fcfm_delta", "fcfm")):
        if profile == "FIN" and name in ("fcfm", "gm"):
            continue   # client cash flows (brokers, banks) make FCF meaningless; no gross profit concept
        a, b = now_w[name], prev_w[name]
        if a is not None and b is not None:
            if abs(a - b) > 40:   # a change of more than 40pp in a margin is a data artefact, not a signal
                out["warnings"].append("{} change {:.0f}pp ignored (implausible)".format(key, a - b))
                continue
            sig[key] = a - b
    for key, (weak, strong) in NOW_SPEC.items():
        s = score_signal(sig.get(key), weak, strong)
        if s is not None:
            out["scores"][key] = s
    if out["scores"]:
        out["now"] = sum(out["scores"].values()) / len(out["scores"])
    out["details"]["now_window"] = now_w
    out["details"]["prev_window"] = prev_w
    # --- TTM leverage with the latest quarterly balance sheet
    if bp:
        q = bp[-1]
        gap = _months(latest) - _months(q)
        if abs(gap) > 3:
            out["warnings"].append("balance sheet quarter {} is {} months from TTM end {}".format(q, gap, latest))
        debt = sum(_g(bal, l, q) or 0.0 for l in DEBT_LABELS) + _lease_total(bal, q)
        cash = (_first(bal, ["Cash & Cash Equivalents", "Cash Equivalents"], q) or 0.0) + (_g(bal, "Short-Term Investments", q) or 0.0)
        op = now_w["operating_income"]
        da = _g(cfs, "Depreciation & Amortization", latest)
        net_debt = debt - cash
        lev = {"quarter": q, "debt": debt, "cash": cash, "net_debt": net_debt, "op": op, "da": da}
        if op is not None and da is not None:
            ebitda = op + da
            lev["ebitda"] = ebitda
            out["levels"]["nd_ebitda_ttm"] = (net_debt / ebitda) if ebitda > 0 else (-1.0 if net_debt <= 0 else None)
        interest = _g(inc, "Interest Expense", latest)
        if op is not None and interest:
            out["levels"]["interest_cover_ttm"] = op / abs(interest)
        out["details"]["leverage"] = lev
    return out
