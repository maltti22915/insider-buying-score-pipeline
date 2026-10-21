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


def parse_wall_st(text):
    """Summary page widget "Wall St Estimates" (up to 3 selected indicators): 'Revenue Forecast +3%', 'Earnings Forecast +25%', 'Operating Income Forecast +x%'.
    The indicator menu lists the same names without numbers, so a number must follow the label directly. Returns {rev, opi, earn} in percent (None when not shown)."""
    out = {"rev": None, "opi": None, "earn": None}
    for key, label in (("rev", "Revenue Forecast"), ("opi", "Operating Income Forecast"), ("earn", "Earnings Forecast")):
        m = re.search(re.escape(label) + r"\s*([+-]?\d+(?:[.,]\d+)?)\s*%", text or "")
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


def read_wall_st(sb, step):
    """Scrolls the already open summary page to the 'Wall St Estimates' widget (lazy block) and reads Rev / OpInc / Earnings forecast %. Never raises."""
    wall = {"rev": None, "opi": None, "earn": None}
    try:
        for tick in range(14):
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
    return wall


def fetch_as_qm(sb, abbrev_as, step, open_page, prof_html=None, buyback=None, moat=None, now_block=None, wall=None):
    """Opens analyst-estimates (+ Revenue / Operating Income tabs) and solvency; assembles the QM payload. Never raises; returns {} when nothing was read."""
    base = "https://www.alphaspread.com/security/{}/".format(str(abbrev_as).strip().strip("/"))
    qm = {"v": 1, "fetched": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "flags": []}
    # profitability (page already loaded by fetch_as_quality)
    try:
        qm["prof"] = parse_profitability(prof_html) if prof_html else {}
        got = sum(1 for v in qm["prof"].values() if v.get("now") is not None)
        step("qm_prof", "OK" if got >= 4 else "FAIL", metrics=got)
    except Exception as e:
        qm["prof"] = {}
        step("qm_prof", "FAIL", reason=type(e).__name__)
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
    # solvency
    try:
        src = _open(sb, base + "solvency", r"Net\s+Debt|Altman", open_page)
        qm["solv"] = parse_solvency(plain_text(src)) if src else {}
        step("qm_solv", "OK" if (qm["solv"].get("bankr") is not None or qm["solv"].get("net_cash") is not None) else "FAIL", **{k: v for k, v in qm["solv"].items() if v is not None})
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
    if buyback:
        qm["bb"] = {"cur": buyback.get("current"), "avg5": buyback.get("avg")}
    if moat:
        qm["moat"] = moat.get("rating")
    if now_block:
        lv, sg = now_block.get("levels") or {}, now_block.get("signals") or {}
        qm["ttm"] = {"rev_growth": sg.get("rev_growth"), "rev_accel": sg.get("rev_accel"), "nd_ebitda": lv.get("nd_ebitda_ttm"),
                     "nd_ebitda_prev": lv.get("nd_ebitda_prev"), "int_cover": lv.get("interest_cover_ttm"), "sbc_pct_rev": lv.get("sbc_pct_rev"),
                     "warnings": now_block.get("warnings")}
    if not qm.get("prof") and not qm.get("est"):
        return {}
    return qm
