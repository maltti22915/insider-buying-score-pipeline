"""
as_fin_data.py v1 -- raw AlphaSpread financial data for Quality v2 ("AS Fin JSON", spec section 2).

Pure parsing functions (no browser) + one browser routine fetch_as_fin(sb, abbrev_as, step, open_page).

Pages (base https://www.alphaspread.com/security/{abbrev}/):
  financials/income-statement, financials/balance-sheet, financials/cash-flow-statement  -> annual view, unit selector set to "Millions"
  solvency (net debt, interest coverage, D/E, Altman Z, bankruptcy probability), qualitative/block/economic-moat, profitability ("3Y Average ROIC")

Parsing rules (spec 2.2):
  * annual column headers look like "FY2026 Jan 2026" -> fiscal label "FY2026" (+ period-end month)
  * rows are identified by the SLUG at the end of the row link (href); when a row has no link the visible label is mapped to a slug (LABEL_TO_SLUG)
  * values: "(419.1m)" negative, suffix k / m / B / T, "—" or empty = None; localised units 十亿->B, 万亿->T, 百万->m
  * output money values are in MILLIONS; per-share rows (eps-diluted) are left as printed
  * if the unit selector cannot be switched to "Millions" the values are converted from their suffixes and the flag ROUNDED_DATA is set
"""
import json
import re
from datetime import datetime, timezone
from html.parser import HTMLParser

BASE = "https://www.alphaspread.com/security/{}/"
PAGES = {
    "is": "financials/income-statement",
    "bs": "financials/balance-sheet",
    "cf": "financials/cash-flow-statement",
}
SLUGS = {
    "is": ["revenue", "operating-income", "pre-tax-income", "tax-provision", "net-income-common", "eps-diluted"],
    "bs": ["cash-cash-equivalents", "short-term-investments", "short-term-debt", "current-portion-of-long-term-debt", "long-term-debt",
           "total-equity", "goodwill", "common-shares-outstanding"],
    "cf": ["cash-from-operating-activities", "capital-expenditures", "free-cash-flow", "stock-based-compensation", "depreciation-amortization"],
}
OPTIONAL = {"is": ["interest-expense", "interest-income-expense"]}   # not every company has them (ADSK only has the net row); never reported as missing
NO_SCALE = {"eps-diluted"}   # per-share values are not money in millions

# fallback when a row has no link: visible English label (lower case) -> slug
LABEL_TO_SLUG = {
    "revenue": "revenue", "total revenue": "revenue", "operating income": "operating-income", "pre-tax income": "pre-tax-income",
    "income before tax": "pre-tax-income", "tax provision": "tax-provision", "income tax": "tax-provision",
    "net income common": "net-income-common", "net income to common": "net-income-common", "eps diluted": "eps-diluted", "diluted eps": "eps-diluted",
    "interest expense": "interest-expense", "interest income (expense)": "interest-income-expense", "cash & cash equivalents": "cash-cash-equivalents", "cash and cash equivalents": "cash-cash-equivalents",
    "short-term investments": "short-term-investments", "short term investments": "short-term-investments", "short-term debt": "short-term-debt",
    "short term debt": "short-term-debt", "current portion of long-term debt": "current-portion-of-long-term-debt",
    "long-term debt": "long-term-debt", "long term debt": "long-term-debt", "total equity": "total-equity", "goodwill": "goodwill",
    "common shares outstanding": "common-shares-outstanding", "cash from operating activities": "cash-from-operating-activities",
    "operating cash flow": "cash-from-operating-activities", "capital expenditures": "capital-expenditures", "capital expenditure": "capital-expenditures",
    "free cash flow": "free-cash-flow", "stock-based compensation": "stock-based-compensation", "stock based compensation": "stock-based-compensation",
    "depreciation & amortization": "depreciation-amortization", "depreciation and amortization": "depreciation-amortization",
}

_UNIT_MAP = [("十亿", "B"), ("万亿", "T"), ("百万", "m")]
_TO_MILLIONS = {"T": 1e6, "B": 1e3, "M": 1.0, "m": 1.0, "K": 1e-3, "k": 1e-3, "": None}


def normalise_units(text):
    """Localised units -> B / T / m (spec 2.2)."""
    for src, dst in _UNIT_MAP:
        text = (text or "").replace(src, dst)
    return text


def parse_value(text, unit_selected_millions=True):
    """Returns (value_in_millions or None). '(419.1m)' -> -419.1; '1.3B' -> 1300; plain '1,234.5' is millions when the unit selector is on
    Millions, else raw units (-> /1e6). '—', '', '-' -> None."""
    s = normalise_units(text).strip()
    s = re.sub(r"(?<=\d)[\u00a0\u202f\u2009 ](?=\d)", "", s)   # "37 792" (space / thin space as thousands separator) -> "37792"
    s = s.replace(",", "").replace("$", "").replace("¥", "").replace("€", "")
    if s in ("", "-", "—", "–", "N/A", "n/a", "NaN", "nan"):
        return None
    neg = (s.startswith("(") and s.endswith(")")) or s.startswith("-") or s.startswith("−")
    m = re.search(r"(\d+(?:\.\d+)?)\s*([TBMKmk]?)", s)
    if not m:
        return None
    number = float(m.group(1))
    suffix = m.group(2)
    if suffix:
        number *= _TO_MILLIONS[suffix]
    elif not unit_selected_millions:
        number /= 1e6
    return -number if neg else number


class _Rows(HTMLParser):
    """Collects every <table> as rows of cells; each cell keeps its text and all hrefs inside it."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables, self._t, self._r, self._c, self._h = [], None, None, None, None

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self._t = []
        elif tag == "tr" and self._t is not None:
            self._r = []
        elif tag in ("td", "th") and self._r is not None:
            self._c, self._h = [], []
        elif tag == "a" and self._h is not None:
            href = dict(attrs).get("href")
            if href:
                self._h.append(href)

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._c is not None and self._r is not None:
            self._r.append({"text": re.sub(r"\s+", " ", "".join(self._c)).strip(), "hrefs": self._h or []})
            self._c, self._h = None, None
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


def slug_of_row(label_cell):
    """Slug = last path segment of the row link; falls back to the visible label."""
    for href in label_cell.get("hrefs", []):
        seg = re.split(r"[?#]", href)[0].rstrip("/").split("/")[-1]
        if seg:
            return seg.lower()
    return LABEL_TO_SLUG.get(re.sub(r"\s+", " ", label_cell.get("text", "")).strip().lower())


def parse_statement(html, group, unit_selected_millions=True):
    """Returns (fy_labels_ascending, {slug: [values aligned with fy_labels]}, info). Only the wanted slugs are kept."""
    parser = _Rows()
    parser.feed(html or "")
    best = None
    for table in parser.tables:
        for row in table[:3]:
            count = sum(1 for c in row if re.search(r"FY\s*20\d\d", c["text"]))
            if count >= 4 and (best is None or count > best[0]):
                best = (count, table, row)
                break
    if best is None:
        return [], {}, {"error": "no table with FY headers"}
    _, table, header = best
    col_label = {}
    for index, cell in enumerate(header):
        m = re.search(r"FY\s*(20\d\d)", cell["text"])
        if m:
            col_label[index] = "FY" + m.group(1)
    order = sorted(set(col_label.values()))
    required = set(SLUGS[group])
    wanted = required | set(OPTIONAL.get(group, []))
    series = {}
    for row in table:
        if not row or row is header:
            continue
        slug = slug_of_row(row[0])
        if slug not in wanted or slug in series:
            continue
        by_label = {}
        for i, label in col_label.items():
            if i < len(row):
                v = parse_value(row[i]["text"], unit_selected_millions)
                if v is not None and slug in NO_SCALE and unit_selected_millions is False:
                    v = v * 1e6   # per-share rows are not scaled
                by_label[label] = v
        series[slug] = [by_label.get(l) for l in order]
    return order, series, {"columns": len(header), "rows": len(series), "missing": sorted(required - set(series))}


def merge_statements(parts):
    """parts = [(order, series)] for is / bs / cf -> common fy list (union, ascending, last 10) and aligned series."""
    labels = sorted({l for order, _ in parts for l in order})[-10:]
    out = []
    for order, series in parts:
        aligned = {}
        for slug, vals in series.items():
            m = dict(zip(order, vals))
            aligned[slug] = [m.get(l) for l in labels]
        out.append(aligned)
    return labels, out


# ----------------------------------------------------------------------------- solvency / moat / profitability
def strip_text(html):
    html = re.sub(r"(?is)<(script|style|noscript).*?</\1>", " ", html or "")
    html = re.sub(r"(?s)<[^>]+>", " ", html)
    import html as _h
    return re.sub(r"\s+", " ", _h.unescape(html)).strip()


def _money_to_millions(text):
    return parse_value(text, unit_selected_millions=False)


def parse_solvency(html):
    """Latest values from the solvency page text. Missing items stay None."""
    text = normalise_units(strip_text(html))
    out = {"net_debt": None, "int_cov": None, "de": None, "altman_z": None, "bankrupt_pct": None}
    m = re.search(r"(Positive|Negative)\s+Net\s+Debt\s*(-?\(?[\d.,]+\s*[TBMKmk]?\)?)\s*[A-Z]{3}", text, re.I)
    if m:
        v = _money_to_millions(m.group(2))
        if v is not None:
            v = abs(v)
            out["net_debt"] = v if m.group(1).lower() == "positive" else -v
    m = re.search(r"Interest\s+Coverage[^0-9]{0,40}?(-?\d+(?:[.,]\d+)?)", text, re.I)
    if m:
        out["int_cov"] = float(m.group(1).replace(",", "."))
    m = re.search(r"(?:Debt\s*(?:to|/)\s*Equity|D/E)[^0-9]{0,40}?(-?\d+(?:[.,]\d+)?)", text, re.I)
    if m:
        out["de"] = float(m.group(1).replace(",", "."))
    m = re.search(r"Altman\s+Z[^0-9]{0,40}?(-?\d+(?:[.,]\d+)?)", text, re.I)
    if m:
        out["altman_z"] = float(m.group(1).replace(",", "."))
    m = re.search(r"probability\s+of\s+bankruptcy\s+is\s+(\d+(?:[.,]\d+)?)\s*%", text, re.I)
    if m:
        out["bankrupt_pct"] = float(m.group(1).replace(",", "."))
    return out


def parse_moat_rating(rating):
    """Wide / Narrow / None ('No Moat' -> 'None')."""
    r = (rating or "").strip().lower()
    if r.startswith("wide"):
        return "Wide"
    if r.startswith("narrow"):
        return "Narrow"
    if r:
        return "None"
    return None


def parse_roic3y(html):
    text = strip_text(html)
    i = text.find("3Y Average ROIC")
    if i < 0:
        return None
    after = text[i + 15: i + 15 + 40]
    before = text[max(0, i - 24): i]
    cands = []
    m = re.search(r"(-?\d+(?:\.\d+)?)\s*%", after)
    if m:
        cands.append((m.start(), float(m.group(1))))
    m = re.search(r"(-?\d+(?:\.\d+)?)\s*%((?:\s*[A-Za-z]+){0,2}\s*)$", before)
    if m:
        cands.append((len(m.group(2)), float(m.group(1))))
    return sorted(cands, key=lambda c: c[0])[0][1] if cands else None


def build_fin(parts, solvency_html, moat_rating, profitability_html, currency=None, rounded=False):
    """parts = {'is': (order, series), 'bs': ..., 'cf': ...}. Returns the AS Fin JSON dict (spec 2.3)."""
    labels, (is_, bs_, cf_) = merge_statements([parts["is"], parts["bs"], parts["cf"]])
    flags = []
    if rounded:
        flags.append("ROUNDED_DATA")
    return {
        "v": 1,
        "fetched": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
        "currency": currency or "",
        "unit": "Auto" if rounded else "m",
        "fy": labels,
        "is": is_, "bs": bs_, "cf": cf_,
        "solv": parse_solvency(solvency_html),
        "moat": parse_moat_rating(moat_rating),
        "roic3y_as": parse_roic3y(profitability_html),
        "flags": flags,
    }


# ----------------------------------------------------------------------------- browser side
_SET_MILLIONS_JS = """
var want = 'Millions', done = 'none';
var sels = document.querySelectorAll('select');
for (var i = 0; i < sels.length; i++) {
  for (var j = 0; j < sels[i].options.length; j++) {
    if ((sels[i].options[j].text || '').trim() === want) {
      sels[i].value = sels[i].options[j].value;
      sels[i].dispatchEvent(new Event('input', {bubbles: true}));
      sels[i].dispatchEvent(new Event('change', {bubbles: true}));
      return 'select';
    }
  }
}
var els = document.querySelectorAll('button, a, label, li, span, div');
for (var k = 0; k < els.length; k++) {
  var e = els[k];
  if (e.children.length === 0 && (e.textContent || '').trim() === 'Auto') { e.scrollIntoView({block: 'center'}); e.click(); done = 'opened'; break; }
}
if (done === 'opened') {
  var opts = document.querySelectorAll('button, a, label, li, span, div, option');
  for (var n = 0; n < opts.length; n++) {
    var o = opts[n];
    if (o.children.length === 0 && (o.textContent || '').trim() === want) { o.click(); return 'clicked'; }
  }
}
return done;
"""


def millions_ready(src):
    """True when the page says 'Scale: Millions' AND the statement table shows no B/T suffix (a half-rendered table fails the second test)."""
    if 'Scale: Millions' not in (src or ""):
        return False
    tables = re.findall(r"<table.*?</table>", src, re.S)
    tables.sort(key=lambda x: -len(re.findall(r"FY\s*20\d\d", x)))
    text = re.sub(r"<[^>]+>", " ", tables[0] if tables else "")
    return not re.search(r"\d\s?[BT]\b", text)


def ensure_millions(sb, url, source, open_page, step):
    """Switches the statement table to Millions (3 attempts: switch, switch again, reload + switch). The success test is the page itself
    ('Scale: Millions' + no B/T in the table), never 'the page changed' (a loading state also changes it). Returns (source, millions_bool)."""
    if millions_ready(source):
        step("OK", how="already", attempt=0)
        return source, True
    for attempt in (1, 2, 3):
        try:
            if attempt == 3:
                reloaded = open_page(sb, url, r"FY\s*20\d\d")
                if not reloaded:
                    step("INFO", how="reload blocked", attempt=attempt)
                    break
                source = reloaded
                if millions_ready(source):
                    step("OK", how="already after reload", attempt=attempt)
                    return source, True
            how = sb.execute_script(_SET_MILLIONS_JS)
            for _ in range(14):
                sb.sleep(1.0)
                now = sb.get_page_source()
                if millions_ready(now):
                    step("OK", how=how, attempt=attempt)
                    return now, True
            step("INFO", how=how, attempt=attempt, reason="not Millions after 14 s")
        except Exception as e:
            step("INFO", reason=type(e).__name__, attempt=attempt)
    return source, False


def fetch_as_fin(sb, abbrev_as, step, open_page):
    """Browser routine. open_page(sb, url) must open the URL and return the page source ('' when blocked). Returns the AS Fin JSON dict or None.
    Never raises."""
    base = BASE.format(str(abbrev_as).strip().strip("/"))
    parts, rounded = {}, False
    for group, path in PAGES.items():
        try:
            source = open_page(sb, base + path, r"FY\s*20\d\d")
            if not source:
                step("fin_" + group, "FAIL", reason="blocked")
                return None
            source, millions = ensure_millions(sb, base + path, source, open_page, lambda *a, **k: step("fin_unit_" + group, *a, **k))
            if not millions:
                rounded = True
            order, series, info = parse_statement(source, group, unit_selected_millions=millions)
            if not order:
                step("fin_" + group, "FAIL", reason=info.get("error", "no data"))
                return None
            parts[group] = (order, series)
            step("fin_" + group, "OK", years=len(order), rows=info.get("rows"), missing=",".join(info.get("missing", [])) or "none")
        except Exception as page_error:
            step("fin_" + group, "FAIL", reason=type(page_error).__name__)
            return None
    solvency_html, moat_rating, profitability_html = "", None, ""
    try:
        solvency_html = open_page(sb, base + "solvency", r"Net\s+Debt") or ""
        step("fin_solvency", "OK" if solvency_html else "FAIL", chars=len(solvency_html))
    except Exception as e:
        step("fin_solvency", "FAIL", reason=type(e).__name__)
    try:
        moat_html = open_page(sb, base + "qualitative/block/economic-moat", r"What is Economic Moat\?") or ""
        try:
            import as_moat
            moat_rating = as_moat.parse_moat(moat_html).get("rating") if moat_html else None
        except Exception:
            moat_rating = None
        step("fin_moat", "OK" if moat_rating else "INFO", rating=moat_rating)
    except Exception as e:
        step("fin_moat", "FAIL", reason=type(e).__name__)
    try:
        profitability_html = open_page(sb, base + "profitability", r"3Y Average ROIC") or ""
        step("fin_profitability", "OK" if profitability_html else "FAIL", chars=len(profitability_html))
    except Exception as e:
        step("fin_profitability", "FAIL", reason=type(e).__name__)
    return build_fin(parts, solvency_html, moat_rating, profitability_html, rounded=rounded)
