"""
as_qm_data.py v1 -- raw AlphaSpread inputs for the Quality Model (QL / Dir / Outl / Q).
Pure parsers (no browser) + fetch_as_qm() which opens the analyst-estimates and solvency pages. The profitability page, buyback block, moat and
TTM block are already read by provider_json_scraper.py (fetch_as_quality / fetch_as_buyback) and are passed in.

QM payload ("qm", posted as target ASQM, stored in the "QM JSON" cell):
  {v:1, fetched, prof:{roic|opm|fcfm|gm|nm|roe: {now, avg3, prev}}, est:{rev3, rev3_n, rev_cagr_fwd, opi3, opi3_n, opi_cagr_fwd, rev_lt, rev_lt_years},
   bb:{cur, avg5}, solv:{bankr, net_cash, net_debt_text}, moat, ttm:{rev_growth, rev_accel, nd_ebitda, nd_ebitda_prev, int_cover, sbc_pct_rev}, flags:[..]}
"""
import re
from datetime import datetime, timezone

VERSION = "as_qm_data v1.15"   # v1.15 est.earn_lt / earn_lt_years / earn_lt_basis (Operating Income, fallback Net Income) and ttm.earn_g / earn_g_nm | v1.14 Net Income long-term CAGR (analyst-estimates page, fallback Operating Income) and 10Y price change (summary page period button) for the COMPOUNDER gates / PRICE_LAGS_BUSINESS | v1.13 AlphaSpread insider block removed (insider data comes only from InsiderScreener) | v1.12 insider parser tries every "Insider" occurrence, debug dumps windows around Bought/Sold/12 months words | v1.11 v1.11 insider trading block (bought / sold USD, 0-12 months) read on the summary visit; Chinese unit mapping |  v1.10 widget values only from the widget text itself | v1.9 qm_missing (completion pass), solvency debug text 500 chars | v1.8 margins computed + na list | v1.7 ROIC computed from the statements when the page has none | v1.6 ROIC debug text | v1.5 card layout of the profitability page (parse_profitability_cards) | v1.4 qm_prof diagnostics | v1.3 solvency retry | v1.2 read_wall_st shared with the summary visit | v1.1 Wall St widget | v1.0 first

PROFILE_METRICS = {   # key -> label as printed on the profitability checklist
    "gm": "Gross Margin", "opm": "Operating Margin", "nm": "Net Margin", "fcfm": "Free Cash Flow Margin", "roe": "ROE", "roic": "ROIC",
}
TAB_CLICK_JS = ("var want = arguments[0], hit = null;"
                "document.querySelectorAll('button, a, li, span, div, label').forEach(function (e) {"
                "  if (!hit && e.children.length === 0 && (e.textContent || '').trim() === want) { hit = e; } });"
                "if (!hit) { return 'none'; } hit.scrollIntoView({block: 'center'}); hit.click(); return 'clicked';")
NUM = r"(-?\d+(?:[.,]\d+)?)"


def plain_text(html):
    import html as _h
    s = re.sub(r"(?is)<(script|style|noscript)\b.*?</\1>", " ", html or "")
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", _h.unescape(s)).strip()


def _f(x):
    try:
        return float(str(x).replace(",", "."))
    except Exception:
        return None


def parse_profitability(html_or_text):
    """Checklist -> {key: {now, avg3, prev}} in percent (AlphaSpread prints whole numbers). prev = the left number of 'prev% > now%'."""
    t = html_or_text if "<" not in (html_or_text or "")[:200] else plain_text(html_or_text)
    i = t.find("Due Diligence Checks")
    if i >= 0:
        j = t.find("Profitability Score", i)
        t = t[i:j if j > i else i + 4000]
    out = {}
    for key, label in PROFILE_METRICS.items():
        lab = re.escape(label)
        rec = {"now": None, "avg3": None, "prev": None}
        m = re.search(r"3Y Average\s+" + lab + r"\s+" + NUM + r"\s*%", t)
        if m:
            rec["avg3"] = _f(m.group(1))
        m = re.search(lab + r"(?:\s+is\s+(?:Increasing|Declining|Decreasing|Stable))?\s+" + NUM + r"\s*%\s*>\s*" + NUM + r"\s*%", t)
        if m:
            rec["prev"], rec["now"] = _f(m.group(1)), _f(m.group(2))
        if rec["now"] is None:
            m = re.search(r"(?<!Average )(?<!Average\s)\b" + lab + r"\s+" + NUM + r"\s*%(?!\s*>)", t)
            if m:
                rec["now"] = _f(m.group(1))
        out[key] = rec
    return out


CARD_LABELS = {   # card layout of the profitability page (no "Due Diligence Checks" list): big value, LABEL, "3Y Avg x%"
    "gm": [r"GROSS MARGIN"], "opm": [r"OPERATING MARGIN", r"OPERATING PROFIT MARGIN", r"EBIT MARGIN"], "nm": [r"NET MARGIN", r"NET PROFIT MARGIN"],
    "fcfm": [r"FREE CASH FLOW MARGIN", r"FCF MARGIN"], "roe": [r"ROE"], "roic": [r"ROIC", r"RETURN ON INVESTED CAPITAL"],
}


def parse_profitability_cards(html_or_text):
    """v1.5: card layout (seen on UNH): '+2% 15 .9 % ROE <chart> 3Y Avg 18% 5Y Avg 21% ...'. Returns {key: {now, avg3, prev}}; prev = now - the green/red badge change.
    Values are read as printed (one decimal); a number split over elements ('3' '.5%') is joined."""
    t = html_or_text if "<" not in (html_or_text or "")[:200] else plain_text(html_or_text)
    out = {}
    for key, labels in CARD_LABELS.items():
        rec = {"now": None, "avg3": None, "prev": None}
        for lab in labels:
            for m in re.finditer(r"(?<![A-Za-z])" + lab + r"(?![A-Za-z])", t, re.I):
                after = t[m.end():m.end() + 160]
                avg = re.search(r"3Y\s*Avg\.?\s*" + NUM + r"\s*%", after, re.I)
                if not avg:
                    continue
                before = t[max(0, m.start() - 40):m.start()]
                num = re.search(r"(\d+)\s*(?:\.\s*(\d+))?\s*%?\s*$", before)
                if not num:
                    continue
                rec["now"] = _f(num.group(1) + ("." + num.group(2) if num.group(2) else ""))
                rec["avg3"] = _f(avg.group(1))
                pre = before[:num.start()]
                d = re.search(r"([+-]\d+(?:[.,]\d+)?)\s*%\s*$", pre)
                if d and rec["now"] is not None:
                    rec["prev"] = rec["now"] - _f(d.group(1))
                break
            if rec["now"] is not None:
                break
        out[key] = rec
    return out


def parse_wall_st(text):
    """Summary page widget "Wall St Estimates" (up to 3 selected indicators): 'Revenue Forecast +3%', 'Earnings Forecast +25%', 'Operating Income Forecast +x%'.
    The indicator menu lists the same names without numbers, so a number must follow the label directly. Returns {rev, opi, earn} in percent (None when not shown)."""
    out = {"rev": None, "opi": None, "earn": None}
    text = text or ""
    i = text.find("Wall St Estimates")
    if i >= 0:   # v1.10: only the widget itself (up to its indicator menu), never other 'Forecast' texts further down the page
        seg = text[i:i + 900]
        j = seg.find("Select Indicators")
        text = seg[:j] if j > 0 else seg
    for key, label in (("rev", "Revenue Forecast"), ("opi", "Operating Income Forecast"), ("earn", "Earnings Forecast")):
        m = re.search(re.escape(label) + r"\s*([+-]?\d+(?:[.,]\d+)?)\s*%", text)
        if m:
            out[key] = _f(m.group(1))
    return out


def _block_after(text, marker):
    """Text of the 'In N years' block that starts at marker, up to the next 'In N years' block."""
    i = text.find(marker)
    if i < 0:
        return ""
    m = re.search(r"In \d+ years", text[i + len(marker):])
    return text[i:i + len(marker) + (m.start() if m else 600)]


def parse_estimates(text, metric="Revenue"):
    """One estimates tab (Revenue or Operating Income) -> {three, three_n, only, cagr_fwd, cagr_fwd_years, cagr_hist, cagr_hist_years}.
    three = the 'In 3 years' change in percent versus the last fiscal year (None when 'Only N analysts' marks the block or the value is 0)."""
    out = {"three": None, "three_n": None, "only": False, "cagr_fwd": None, "cagr_fwd_years": None, "cagr_hist": None, "cagr_hist_years": None}
    blk = _block_after(text, "In 3 years")
    if blk:
        m = re.search(r"([+-]\d[\d.,]*)\s*%", blk)
        if m:
            out["three"] = _f(m.group(1).replace(",", ""))
        m = re.search(r"Average of (\d+) analysts", blk)
        if m:
            out["three_n"] = int(m.group(1))
        if re.search(r"Only \d+ analysts?", blk):
            out["only"] = True
            out["three"] = None
    seg = re.search(r"What is the " + re.escape(metric) + r" forecast for.*?(?=What is the |Back to Top|$)", text)
    seg = seg.group(0) if seg else ""
    m = re.search(r"projected CAGR for the next (\d+) years is " + NUM + r"\s*%", seg)
    if m:
        out["cagr_fwd_years"], out["cagr_fwd"] = int(m.group(1)), _f(m.group(2))
    m = re.search(r"Over the last (\d+) years?, the compound annual growth rate for " + re.escape(metric) + r" has been " + NUM + r"\s*%", seg)
    if m:
        out["cagr_hist_years"], out["cagr_hist"] = int(m.group(1)), _f(m.group(2))
    return out


def parse_solvency(text):
    out = {"bankr": None, "net_cash": None, "net_debt_text": None}
    m = (re.search(r"probability of bankruptcy is " + NUM + r"\s*%", text, re.I) or re.search(r"Bankruptcy Probability.{0,80}?" + NUM + r"\s*%", text, re.I)
         or re.search(r"Probability of Bankruptcy\s+" + NUM + r"\s*%", text, re.I))
    if m:
        out["bankr"] = _f(m.group(1))
    m = re.search(r"(Negative|Positive) Net Debt\s+(-?[\d.,]+\s*[KMBT]?\s*[A-Z]{3})", text)
    if m:
        out["net_cash"] = (m.group(1) == "Negative")
        out["net_debt_text"] = m.group(2).strip()
    return out


def _open(sb, url, ready_pattern, open_page):
    return open_page(sb, url, ready_pattern) if open_page else ""


def qm_missing(qm):
    """Python twin of fn_94_03_QualityModelMissing_: inputs the Quality Model cannot do without and the scraper could still get with another try."""
    miss = []
    isn = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool)
    qm = qm or {}
    prof, est, bb, ttm, solv = qm.get("prof") or {}, qm.get("est") or {}, qm.get("bb") or {}, qm.get("ttm") or {}, qm.get("solv") or {}
    na = qm.get("na") or []
    for k, label in (("roic", "ROIC"), ("opm", "Op mgn"), ("fcfm", "FCF mgn"), ("gm", "Gross Margin")):
        if not isn((prof.get(k) or {}).get("now")) and k not in na:
            miss.append(label)
    if not isn(est.get("rev_lt")): miss.append("Rev LT")
    if not (isn(est.get("rev_w")) or isn(est.get("rev3")) or isn(est.get("rev_cagr_fwd"))): miss.append("Rev est")
    if not (isn(est.get("opi_w")) or isn(est.get("earn_w")) or isn(est.get("opi3")) or isn(est.get("opi_cagr_fwd"))): miss.append("OpInc est")
    if not isn(bb.get("cur")): miss.append("Shr chg")
    if not qm.get("moat"): miss.append("Moat")
    if not isn(ttm.get("rev_growth")): miss.append("Rev g")
    if not qm.get("fin") and not isn(ttm.get("nd_ebitda")) and solv.get("net_cash") is not True: miss.append("ND/EBITDA")
    return miss


_UNIT = {"k": 1e3, "m": 1e6, "b": 1e9, "t": 1e12, "\u5343": 1e3, "\u4e07": 1e4, "\u767e\u4e07": 1e6, "\u4ebf": 1e8, "\u5341\u4ebf": 1e9, "\u4e07\u4ebf": 1e12}


def _usd(txt):
    """'$25.7M' / '25.7 B' / '8.08\u4ebf' -> float USD, or None. Never 0 for unreadable text."""
    m = re.search(r"(-?\d[\d,]*\.?\d*)\s*(\u4e07\u4ebf|\u5341\u4ebf|\u767e\u4e07|\u4ebf|\u4e07|\u5343|[KMBTkmbt])?(?![A-Za-z])", txt or "")
    if not m:
        return None
    try:
        v = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    u = (m.group(2) or "").lower()
    return v * _UNIT.get(u, 1.0)


def parse_insider(text):
    """v1.11/v1.12: the summary page 'Insider Trading' block, window 0-12 months: {'bought': USD, 'sold': USD} (None when not readable).
    Tries every occurrence of 'Insider Trading' (the first is often only a header)."""
    out = {"bought": None, "sold": None}
    text = text or ""
    for hit in re.finditer(r"Insider Trading", text):
        seg = text[hit.start():hit.start() + 1200]
        got = {"bought": None, "sold": None}
        for key, word in (("bought", r"(?:Bought|Purchased|Buys?|Purchases)"), ("sold", r"(?:Sold|Sales|Sells?)")):
            m = re.search(word + r"[^0-9$\-]{0,40}\$?\s*(-?\d[\d,]*\.?\d*\s*(?:\u4e07\u4ebf|\u5341\u4ebf|\u767e\u4e07|\u4ebf|\u4e07|[KMBkmb])?)", seg)
            if m:
                got[key] = _usd(m.group(1))
        if got["bought"] is not None or got["sold"] is not None:
            return got
    return out


def insider_debug_text(text):
    """v1.12: windows around the words that should sit in the insider block, to see its real layout in the log."""
    wins = []
    for m in re.finditer(r"(?i)bought|sold|insider (?:buy|sell|trad)|12 months|0-12|last year", text or ""):
        a = max(0, m.start() - 80)
        if not wins or a > wins[-1][1]:
            wins.append((a, m.start() + 260))
        if len(wins) >= 4:
            break
    return " || ".join((text[a:b]) for a, b in wins) if wins else "no insider words on the page"


def read_insider(sb, step):
    """Scrolls the open summary page to the 'Insider Trading' block and reads bought / sold USD. Never raises."""
    ins = {"bought": None, "sold": None}
    try:
        for tick in range(10):
            try:
                sb.execute_script("var w=null;document.querySelectorAll('h1,h2,h3,h4,div,span').forEach(function(e){if(!w&&e.children.length===0&&(e.textContent||'').trim()==='Insider Trading'){w=e;}});"
                                  "if(w){w.scrollIntoView({block:'center'});}else{window.scrollBy(0,700);}")
            except Exception:
                pass
            sb.sleep(2.0)
            t = plain_text(sb.get_page_source())
            ins = parse_insider(t)
            if ins.get("bought") is not None or ins.get("sold") is not None:
                break
        if ins.get("bought") is None and ins.get("sold") is None:
            t = plain_text(sb.get_page_source())
            step("qm_insider_debug", "INFO", text=insider_debug_text(t)[:1400])
        else:
            step("qm_insider", "OK", bought=ins.get("bought"), sold=ins.get("sold"))
    except Exception as e:
        step("qm_insider_debug", "FAIL", reason=type(e).__name__)
    return ins


def parse_px10(text):
    """v1.14: '10Y +111%' (price chart period button / change label) -> 111.0, or None."""
    for m in re.finditer(r"\b10\s?Y(?:ears?)?\b\D{0,40}?([+-]?\d[\d,]*\.?\d*)\s*%", text or ""):
        try:
            return float(m.group(1).replace(",", ""))
        except ValueError:
            continue
    return None


def read_price_10y(sb, step):
    """v1.14: clicks the '10Y' period button of the price chart on the open summary page and reads the price change in percent. Never raises; None when unreadable."""
    try:
        px = parse_px10(plain_text(sb.get_page_source()))
        how = "label"
        if px is None:
            sb.execute_script("window.scrollTo(0, 0);")
            how = sb.execute_script(TAB_CLICK_JS, "10Y")
            sb.sleep(2.5)
            px = parse_px10(plain_text(sb.get_page_source()))
        if px is None:
            t = plain_text(sb.get_page_source())
            hits = [t[max(0, m.start() - 60):m.start() + 160] for m in re.finditer(r"10\s?Y", t)][:3]
            step("qm_px10_debug", "INFO", click=how, text=" || ".join(hits) if hits else "no 10Y text on the page")
        else:
            step("qm_px10", "OK", pct=px, how=how)
        return px
    except Exception as e:
        step("qm_px10_debug", "FAIL", reason=type(e).__name__)
        return None


def read_wall_st(sb, step):
    """Scrolls the already open summary page to the 'Wall St Estimates' widget (lazy block) and reads Rev / OpInc / Earnings forecast %. Never raises."""
    wall = {"rev": None, "opi": None, "earn": None}
    try:
        for tick in range(18):
            try:
                sb.execute_script("var w=null;document.querySelectorAll('h1,h2,h3,h4,div,span').forEach(function(e){if(!w&&e.children.length===0&&(e.textContent||'').trim()==='Wall St Estimates'){w=e;}});"
                                  "if(w){w.scrollIntoView({block:'center'});}else{window.scrollBy(0,600);}")
            except Exception:
                pass
            sb.sleep(2.0)
            wall = parse_wall_st(plain_text(sb.get_page_source()))
            if wall.get("rev") is not None or wall.get("earn") is not None:
                sb.sleep(1.5)
                wall = parse_wall_st(plain_text(sb.get_page_source()))
                break
        if wall.get("rev") is None and wall.get("earn") is None:
            t = plain_text(sb.get_page_source())
            i = t.find("Wall St Estimates")
            step("qm_wall_debug", "INFO", text=t[i:i + 220] if i >= 0 else "no widget text")
    except Exception as e:
        step("qm_wall_debug", "FAIL", reason=type(e).__name__)
    wall["px10"] = read_price_10y(sb, step)   # v1.14
    return wall


def fetch_as_qm(sb, abbrev_as, step, open_page, prof_html=None, buyback=None, moat=None, now_block=None, wall=None, roic_series=None, margin_series=None):
    """Opens analyst-estimates (+ Revenue / Operating Income tabs) and solvency; assembles the QM payload. Never raises; returns {} when nothing was read."""
    base = "https://www.alphaspread.com/security/{}/".format(str(abbrev_as).strip().strip("/"))
    qm = {"v": 1, "fetched": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "flags": []}
    # profitability (page already loaded by fetch_as_quality)
    try:
        qm["prof"] = parse_profitability(prof_html) if prof_html else {}
        if prof_html and sum(1 for v in qm["prof"].values() if v.get("now") is not None) < 4:   # v1.5: card layout (no checklist)
            cards = parse_profitability_cards(prof_html)
            for k, v in cards.items():
                if v.get("now") is not None and (qm["prof"].get(k) or {}).get("now") is None:
                    qm["prof"][k] = v
            step("qm_prof_cards", "INFO", metrics=sum(1 for v in cards.values() if v.get("now") is not None), got=[k for k, v in cards.items() if v.get("now") is not None])
            if (qm["prof"].get("roic") or {}).get("now") is None:   # ROIC is on the page: show the text around it so the label can be matched
                pt = plain_text(prof_html)
                hits = [pt[max(0, m.start() - 70):m.start() + 130] for m in re.finditer(r"ROIC|Invested Capital", pt, re.I)][:3]
                step("qm_prof_roic_debug", "INFO", hits=len(hits), text=" || ".join(hits)[:600])
        got = sum(1 for v in qm["prof"].values() if v.get("now") is not None)
        if got >= 4:
            step("qm_prof", "OK", metrics=got)
        else:
            t = plain_text(prof_html) if prof_html else ""
            i = t.find("Due Diligence Checks")
            step("qm_prof", "FAIL", metrics=got, have=[k for k, v in qm["prof"].items() if v.get("now") is not None],
                 text=(t[i:i + 700] if i >= 0 else "no 'Due Diligence Checks' text; page chars=%d" % len(t)))
    except Exception as e:
        qm["prof"] = {}
        step("qm_prof", "FAIL", reason=type(e).__name__)
    # ROIC missing on the page (UNH: no ROIC card) -> computed yearly ROIC from the statements (same basis as the Quality step)
    try:
        if (qm["prof"].get("roic") or {}).get("now") is None and roic_series:
            ys = sorted(roic_series.keys(), key=lambda y: str(y))
            vals = [float(roic_series[y]) for y in ys]
            if vals:
                qm["prof"]["roic"] = {"now": round(vals[-1], 1), "avg3": round(sum(vals[-3:]) / len(vals[-3:]), 1) if len(vals) >= 3 else None,
                                      "prev": round(vals[-2], 1) if len(vals) >= 2 else None, "src": "computed from statements, FY " + str(ys[-1])}
                step("qm_roic_computed", "OK", now=qm["prof"]["roic"]["now"], prev=qm["prof"]["roic"]["prev"], fy=ys[-1])
    except Exception as e:
        step("qm_roic_computed", "FAIL", reason=type(e).__name__)
    # margins missing on the page (card layout shows only some) -> yearly margins computed from the statements
    try:
        if margin_series:
            ys = sorted(margin_series.keys(), key=lambda y: str(y))
            filled = []
            for key in ("opm", "gm", "fcfm", "nm"):
                if (qm["prof"].get(key) or {}).get("now") is not None:
                    continue
                vals = [float(margin_series[y][key]) for y in ys if key in margin_series[y]]
                if vals:
                    qm["prof"][key] = {"now": round(vals[-1], 1), "avg3": round(sum(vals[-3:]) / len(vals[-3:]), 1) if len(vals) >= 3 else None,
                                       "prev": round(vals[-2], 1) if len(vals) >= 2 else None, "src": "computed from statements, FY " + str(ys[-1])}
                    filled.append(key)
            if filled:
                step("qm_margins_computed", "OK", filled=filled)
        # metrics that neither the page nor the statements can give (e.g. no Gross Profit line for an insurer): not "missing", do not re-scrape for them
        if margin_series or roic_series:
            qm["na"] = [k for k in ("roic", "opm", "fcfm", "gm") if (qm["prof"].get(k) or {}).get("now") is None]
            if qm["na"]:
                step("qm_not_available", "INFO", metrics=qm["na"])
    except Exception as e:
        step("qm_margins_computed", "FAIL", reason=type(e).__name__)
    # analyst estimates
    est = {}
    try:
        src = _open(sb, base + "analyst-estimates", r"Financial Estimates|In \d+ years|analysts", open_page)
        if not src:
            step("qm_est", "FAIL", reason="blocked")
        else:
            for tab, key in (("Revenue", "rev"), ("Operating Income", "opi")):
                text = ""
                for attempt in (1, 2, 3):
                    how = sb.execute_script(TAB_CLICK_JS, tab)
                    sb.sleep(2.5)
                    text = plain_text(sb.get_page_source())
                    p = parse_estimates(text, "Revenue" if key == "rev" else "Operating Income")
                    same_as_rev = key == "opi" and p["three"] is not None and (est.get("rev") or {}).get("three") == p["three"]   # tab did not switch
                    if (p["three"] is not None and not same_as_rev) or p["only"] or attempt == 3:
                        if same_as_rev:
                            p["three"] = None
                        break
                    sb.sleep(3.0 * attempt)
                est[key] = p
            r, o = est.get("rev", {}), est.get("opi", {})
            qm["est"] = {"rev3": r.get("three"), "rev3_n": r.get("three_n"), "rev_only": r.get("only"), "rev_cagr_fwd": r.get("cagr_fwd"),
                         "rev_cagr_fwd_years": r.get("cagr_fwd_years"), "opi3": o.get("three"), "opi3_n": o.get("three_n"), "opi_only": o.get("only"),
                         "opi_cagr_fwd": o.get("cagr_fwd"), "opi_cagr_fwd_years": o.get("cagr_fwd_years"),
                         "rev_lt": r.get("cagr_hist"), "rev_lt_years": r.get("cagr_hist_years")}
            ni = {}
            try:   # v1.14: Net Income long-term CAGR (tab may not exist: then Operating Income is the fallback in the calc)
                for attempt in (1, 2):
                    how_ni = sb.execute_script(TAB_CLICK_JS, "Net Income")
                    if how_ni == "none":
                        break
                    sb.sleep(2.5 * attempt)
                    ni = parse_estimates(plain_text(sb.get_page_source()), "Net Income")
                    if ni.get("cagr_hist") is not None:
                        break
                step("qm_ni", "OK" if ni.get("cagr_hist") is not None else "INFO", ni_lt=ni.get("cagr_hist"), years=ni.get("cagr_hist_years"), opi_lt=o.get("cagr_hist"))
            except Exception as e_ni:
                step("qm_ni", "FAIL", reason=type(e_ni).__name__)
            _e_basis = "OpInc" if o.get("cagr_hist") is not None else ("NI" if ni.get("cagr_hist") is not None else None)   # v1.15
            _e_src = o if _e_basis == "OpInc" else ni
            qm["est"].update({"earn_lt": _e_src.get("cagr_hist") if _e_basis else None, "earn_lt_years": _e_src.get("cagr_hist_years") if _e_basis else None, "earn_lt_basis": _e_basis})
            qm["est"].update({"ni_lt": ni.get("cagr_hist"), "ni_lt_years": ni.get("cagr_hist_years"), "opi_lt": o.get("cagr_hist"), "opi_lt_years": o.get("cagr_hist_years")})
            if o.get("three") is None and not o.get("only"):
                step("qm_est_debug", "INFO", opi_block=(_block_after(text, "In 3 years") or "")[:200], tab_click=how)
            step("qm_est", "OK" if (r.get("three") is not None or r.get("cagr_fwd") is not None) else "FAIL",
                 rev3=r.get("three"), opi3=o.get("three"), rev_lt=r.get("cagr_hist"), only=(r.get("only"), o.get("only")))
    except Exception as e:
        step("qm_est", "FAIL", reason=type(e).__name__ + ": " + str(e)[:60])
    # Wall St Estimates widget on the summary page: normally read during the summary visit of fetch_as_hist (wall passed in);
    # the page is opened here only when that visit did not happen / was blocked
    try:
        if wall is not None and wall.get("visited"):
            w = wall
        else:
            wsrc = _open(sb, base + "summary", r"Wall St Estimates", open_page)
            w = read_wall_st(sb, step) if wsrc else {"rev": None, "opi": None, "earn": None}
        est_extra = {"rev_w": w.get("rev"), "opi_w": w.get("opi"), "earn_w": w.get("earn")}
        qm.setdefault("est", {}).update(est_extra)
        step("qm_wall", "OK" if (w.get("rev") is not None or w.get("earn") is not None) else "FAIL", **{k: v for k, v in est_extra.items() if v is not None})
    except Exception as e:
        step("qm_wall", "FAIL", reason=type(e).__name__ + ": " + str(e)[:60])
    # solvency (one retry with a short wait when the first read gives nothing: blocked page or lazy block)
    try:
        solv = {}
        for attempt in (1, 2):
            src = _open(sb, base + "solvency", r"Net\s+Debt|Altman", open_page) if attempt == 1 else None
            if attempt == 2:
                sb.sleep(6.0)
                try:
                    sb.execute_script("window.scrollBy(0,700);")
                except Exception:
                    pass
                sb.sleep(3.0)
                src = sb.get_page_source()
            solv = parse_solvency(plain_text(src)) if src else {}
            if solv.get("bankr") is not None or solv.get("net_cash") is not None:
                break
        qm["solv"] = solv
        if solv.get("bankr") is not None or solv.get("net_cash") is not None:
            step("qm_solv", "OK", **{k: v for k, v in solv.items() if v is not None})
        else:
            t = plain_text(src) if src else ""
            i = max(t.find("Net Debt"), t.find("Altman"))
            step("qm_solv", "FAIL", reason=("page empty/blocked" if not src else "no values parsed"), text=(t[i:i + 500] if i >= 0 else t[:300]))
    except Exception as e:
        qm["solv"] = {}
        step("qm_solv", "FAIL", reason=type(e).__name__)
    # moat: normally taken from the quality step; read it here when that step was blocked
    try:
        if not moat or not moat.get("rating"):
            msrc = _open(sb, base + "qualitative/block/economic-moat", r"How we rate moats|What is Economic Moat\?", open_page)
            if msrc:
                import as_moat
                moat = as_moat.parse_moat(msrc)
                step("qm_moat", "OK" if moat.get("rating") else "FAIL", rating=moat.get("rating"))
            else:
                step("qm_moat", "FAIL", reason="blocked")
    except Exception as e:
        step("qm_moat", "FAIL", reason=type(e).__name__)
    # data the scraper already holds
    if (wall or {}).get("px10") is not None:
        qm["px10"] = wall.get("px10")
    if buyback:
        qm["bb"] = {"cur": buyback.get("current"), "avg5": buyback.get("avg")}
    if moat:
        qm["moat"] = moat.get("rating")
    if now_block:
        lv, sg = now_block.get("levels") or {}, now_block.get("signals") or {}
        qm["ttm"] = {"rev_growth": sg.get("rev_growth"), "rev_accel": sg.get("rev_accel"), "nd_ebitda": lv.get("nd_ebitda_ttm"),
                     "nd_ebitda_prev": lv.get("nd_ebitda_prev"), "int_cover": lv.get("interest_cover_ttm"), "sbc_pct_rev": lv.get("sbc_pct_rev"),
                     "capex_ttm": lv.get("capex_ttm"), "ocf_ttm": lv.get("ocf_ttm"), "earn_g": lv.get("earn_g"), "earn_g_nm": lv.get("earn_g_nm"), "sga_ttm": lv.get("sga_ttm"), "sga_prev": lv.get("sga_prev"),
                     "warnings": now_block.get("warnings")}
    if not qm.get("prof") and not qm.get("est"):
        return {}
    return qm
