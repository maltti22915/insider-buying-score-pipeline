# as_qm_test.py v1 -- PAGE DISCOVERY + STABILITY TEST for the new Quality Model (QL / Dir / Outl, reference of 2026-10-20).
# It does NOT score anything yet. It answers: for each AlphaSpread page the model needs, (1) can it be loaded reliably, (2) which of the phrases the parsers
# will depend on are really on the page, (3) what does the text around them look like (saved as snippets), (4) are the snippets identical on a second load.
# Pages: profitability (checklist: ROIC, margins, 3Y averages, "is Increasing"), analyst-estimates (Revenue / Operating Income tabs, "In 3 years", "Only N analysts",
# CAGR sentences), buybacks (yield), solvency (net debt, interest cover, bankruptcy), economic-moat, summary (insider block), insider-trading page.
# Env: AS_PATHS (default "nasdaq/adsk nyse/orcl nyse/uber nyse/baba"), REPEATS (default 2).
# Output: results_qm.json (snippets per stock/page/phrase, stability flags), qm_pages/<stock>_<page>.html (+ _tab_<name>.html after a tab click), ranking in the step summary.
import json, os, re, time
from seleniumbase import SB

DEFAULT = "nasdaq/adsk nyse/orcl nyse/uber nyse/baba"
PATHS = [p.strip().strip("/") for p in re.split(r"[\s,]+", os.environ.get("AS_PATHS", "").strip() or DEFAULT) if p.strip()]
REPEATS = max(1, int(os.environ.get("REPEATS", "2") or 2))
OUT = "qm_pages"
os.makedirs(OUT, exist_ok=True)
BASE = "https://www.alphaspread.com/security/{}/"

PAGES = {
    "profitability": ("profitability", r"ROIC|Profitability"),
    "estimates": ("analyst-estimates", r"Financial Estimates|In \d+ years|analysts"),
    "buybacks": ("investor-returns/i/buybacks", r"[Bb]uyback"),
    "solvency": ("solvency", r"Net\s+Debt"),
    "moat": ("qualitative/block/economic-moat", r"How we rate moats|What is Economic Moat\?"),
    "summary": ("summary", r"Intrinsic Value|Insider"),
    "insider": ("ownership/block/insider-trading", r"Insider"),
}
PHRASES = {
    "profitability": ["ROIC", "3Y Average", "Operating Margin", "Free Cash Flow Margin", "Gross Margin", "Net Margin", "is Increasing", "is Decreasing", "Profitability Score", "previous"],
    "estimates": ["In 3 years", "Only \\d+ analysts", "compound annual growth rate", "projected CAGR", "Operating Income", "Revenue", "Financial Estimates", "Over the last"],
    "buybacks": ["buyback yield", "Buyback Yield", "shares outstanding", "Average", "5Y|5 Year|5-year"],
    "solvency": ["Net Debt", "Interest Coverage", "Altman", "Bankruptcy", "Debt to Equity|D/E"],
    "moat": ["How we rate moats", "No Moat Narrow Wide"],
    "summary": ["Insider Trading", "bought", "sold", "0-12|12 months|12M", "USD|\\$"],
    "insider": ["Insider Trading", "Bought|Purchase", "Sold|Sale", "Net", "12 months|12M|Last year"],
}
TAB_CLICK_JS = ("var want = arguments[0], hit = null;"
                "document.querySelectorAll('button, a, li, span, div, label').forEach(function (e) {"
                "  if (!hit && e.children.length === 0 && (e.textContent || '').trim() === want) { hit = e; } });"
                "if (!hit) { return 'none'; } hit.scrollIntoView({block: 'center'}); hit.click(); return 'clicked';")
results = []


def plain(html):
    h = re.sub(r"(?is)<(script|style|noscript)\b.*?</\1>", " ", html or "")
    h = re.sub(r"<[^>]+>", " ", h)
    import html as _h
    return re.sub(r"\s+", " ", _h.unescape(h)).strip()


def blocked(sb):
    return "just a moment" in (sb.get_title() or "").lower()


def open_page(sb, url, ready):
    """Cloudflare-aware load: retries at 0 / 20 / 45 s, tries the verification click; waits until the `ready` pattern is in the text. Returns (html, cloudflare_hits)."""
    hits = 0
    for wait in (0, 20, 45):
        if wait:
            sb.sleep(wait)
        sb.uc_open_with_reconnect(url, 4)
        sb.sleep(2.0)
        if blocked(sb):
            hits += 1
            try:
                sb.uc_gui_click_captcha()
                sb.sleep(4.0)
            except Exception:
                pass
            if blocked(sb):
                continue
        for _ in range(14):
            src = sb.get_page_source()
            if re.search(ready, plain(src)):
                return src, hits
            sb.sleep(1.5)
        return sb.get_page_source(), hits
    return "", hits


def snippets(text, patterns, width=170, limit=3):
    out = {}
    for p in patterns:
        found = [text[max(0, m.start() - width): m.end() + width] for m in re.finditer(p, text)]
        out[p] = {"count": len(found), "snippets": found[:limit]}
    return out


def save(name, text):
    try:
        with open(os.path.join(OUT, name), "w", encoding="utf-8") as h:
            h.write(text)
    except Exception:
        pass


def run_page(sb, stock, name, rep):
    suffix, ready = PAGES[name]
    t0 = time.time()
    html, hits = open_page(sb, BASE.format(stock) + suffix, ready)
    rec = {"stock": stock, "page": name, "rep": rep, "ok": bool(html), "cloudflare_hits": hits, "seconds": None, "chars": len(html or "")}
    if html:
        text = plain(html)
        rec["found"] = snippets(text, PHRASES[name])
        rec["missing_phrases"] = [p for p, v in rec["found"].items() if not v["count"]]
        if rep == 1:
            save("{}_{}.html".format(stock.replace("/", "_"), name), html)
        if name == "estimates":
            tabs = {}
            for tab in ("Revenue", "Operating Income"):
                how = None
                try:
                    how = sb.execute_script(TAB_CLICK_JS, tab)
                    sb.sleep(2.5)
                    tab_html = sb.get_page_source()
                    tab_text = plain(tab_html)
                    tabs[tab] = {"click": how, "found": snippets(tab_text, ["In 3 years", "Only \\d+ analysts", "projected CAGR", "compound annual growth rate"])}
                    if rep == 1:
                        save("{}_estimates_tab_{}.html".format(stock.replace("/", "_"), tab.replace(" ", "")), tab_html)
                except Exception as e:
                    tabs[tab] = {"click": how, "error": type(e).__name__}
            rec["tabs"] = tabs
    rec["seconds"] = round(time.time() - t0, 1)
    results.append(rec)
    print("[{}] {} rep{}: {} cf={} missing={} ({:.0f}s)".format(stock, name, rep, "OK" if rec["ok"] else "FAIL", hits, rec.get("missing_phrases", "-"), rec["seconds"]))
    return rec


def snippet_signature(rec):
    return {p: v["snippets"][:1] for p, v in (rec.get("found") or {}).items()}


def summary():
    lines = ["| stock | page | loads ok | Cloudflare hits | stable on repeat | phrases missing |", "|---|---|---|---|---|---|"]
    keys = []
    for r in results:
        k = (r["stock"], r["page"])
        if k not in keys:
            keys.append(k)
    for stock, page in keys:
        rs = [r for r in results if r["stock"] == stock and r["page"] == page]
        ok = sum(1 for r in rs if r["ok"])
        sigs = [json.dumps(snippet_signature(r), sort_keys=True) for r in rs if r["ok"]]
        stable = "-" if len(sigs) < 2 else ("yes" if len(set(sigs)) == 1 else "NO")
        miss = sorted({m for r in rs for m in r.get("missing_phrases", [])})
        lines.append("| {} | {} | {}/{} | {} | {} | {} |".format(stock, page, ok, len(rs), sum(r["cloudflare_hits"] for r in rs), stable, "; ".join(miss)[:110]))
    text = "\n".join(lines)
    print("\n" + text)
    p = os.environ.get("GITHUB_STEP_SUMMARY")
    if p:
        with open(p, "a", encoding="utf-8") as h:
            h.write("## AS Quality Model page test\n" + text + "\n")


def main():
    print("as_qm_test v1 | stocks: {} | repeats: {}".format(PATHS, REPEATS))
    with SB(uc=True, headless=False, locale_code="en") as sb:
        for stock in PATHS:
            for rep in range(1, REPEATS + 1):
                for name in PAGES:
                    try:
                        run_page(sb, stock, name, rep)
                    except Exception as e:
                        print("[{}] {} rep{} aborted: {}".format(stock, name, rep, type(e).__name__))
                    sb.sleep(2.5)
    with open("results_qm.json", "w", encoding="utf-8") as h:
        json.dump(results, h, ensure_ascii=False, indent=1)
    summary()


if __name__ == "__main__":
    main()
