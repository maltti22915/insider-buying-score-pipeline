# as_probe.py v1 -- can we read AlphaSpread ratio pages from a GitHub runner, and which ratios exist?
# Needs: pip install curl_cffi seleniumbase beautifulsoup4
import os, re, json, html as htmllib

AS_PATH = os.environ.get("AS_PATH", "nyse/baba").strip("/")          # exchange/ticker as in the AS URL
BASE = "https://www.alphaspread.com/security/{}/relative-valuation/ratio/".format(AS_PATH)
START = BASE + "price-to-earnings"
MAX_PAGES = int(os.environ.get("AS_MAX_PAGES", "40"))
results = {}


def strip(h):
    h = re.sub(r"(?is)<(script|style|noscript).*?</\1>", " ", h)
    h = re.sub(r"(?s)<[^>]+>", " ", h)
    return re.sub(r"\s+", " ", htmllib.unescape(h)).strip()


def title_of(h):
    m = re.search(r"(?is)<title>(.*?)</title>", h)
    return m.group(1).strip() if m else ""


def blocked(h):
    t = title_of(h).lower()
    return "just a moment" in t or "attention required" in t or len(h) < 3000


def num(s):
    m = re.search(r"-?\d[\d,]*\.?\d*", s or "")
    return float(m.group(0).replace(",", "")) if m else None


def extract(text):
    """Pull the headline numbers out of the tag-stripped text of one ratio page."""
    out = {}
    m = re.search(r"([\d.,]+)\s*Current\b", text) or re.search(r"Current\s*([\d.,]+)", text)
    if m: out["current"] = num(m.group(1))
    for label, key in (("3-y average", "avg3y"), ("5-y average", "avg5y"), ("10-y average", "avg10y"),
                       ("3-Year Average", "avg3y"), ("5-Year Average", "avg5y"), ("10-Year Average", "avg10y"),
                       ("Industry Average", "industry"), ("Country Average", "country")):
        m = re.search(re.escape(label) + r"\s*(?:of\s*)?(-?[\d.,]+)", text, re.I)
        if m and key not in out: out[key] = num(m.group(1))
    m = re.search(r"(Expensive|Cheap|Cheaper|More Expensive|Less Expensive)", text)
    if m: out["verdict_word"] = m.group(1)
    return out


def links_in(h):
    found = re.findall(r'href="([^"]*?/relative-valuation/ratio/([a-z0-9\-]+))"', h)
    seen, slugs = set(), []
    for _href, slug in found:
        if slug not in seen:
            seen.add(slug); slugs.append(slug)
    return slugs


def get_curl(url):
    from curl_cffi import requests as cr
    r = cr.get(url, impersonate="chrome131", timeout=45)
    return r.status_code, r.text


# ---- Method A: plain HTTP with a Chrome fingerprint
pages = {}
try:
    code, body = get_curl(START)
    print("A curl_cffi {} http={} len={} title={!r} blocked={}".format(START, code, len(body), title_of(body), blocked(body)))
    results["curl_cffi_start"] = "OK" if code == 200 and not blocked(body) else "BLOCKED"
    if results["curl_cffi_start"] == "OK":
        pages[START] = body
except Exception as e:
    print("A error", type(e).__name__, str(e)[:150]); results["curl_cffi_start"] = "ERROR"

# ---- Method B: browser, only if A failed
if not pages:
    try:
        from seleniumbase import SB
        with SB(uc=True, headless=False, locale_code="en", test=True) as sb:
            sb.uc_open_with_reconnect(START, 6)
            body = sb.get_page_source()
            ok = not blocked(body)
            print("B browser title={!r} len={} ok={}".format(sb.get_title(), len(body), ok))
            results["browser_start"] = "OK" if ok else "BLOCKED"
            if ok:
                pages[START] = body
                # in the same browser, walk the discovered ratio pages
                for slug in links_in(body)[:MAX_PAGES]:
                    u = BASE + slug
                    if u in pages: continue
                    sb.uc_open_with_reconnect(u, 3)
                    pages[u] = sb.get_page_source()
    except Exception as e:
        print("B error", type(e).__name__, str(e)[:150]); results["browser_error"] = type(e).__name__

# ---- Discover and read every ratio page (Method A path walks over HTTP)
if pages:
    first = pages[START]
    slugs = links_in(first)
    print("DISCOVERED {} ratio pages: {}".format(len(slugs), ", ".join(slugs)))
    for slug in slugs[:MAX_PAGES]:
        u = BASE + slug
        if u not in pages:
            try:
                code, body = get_curl(u)
                if code == 200 and not blocked(body): pages[u] = body
                else: print("  {} -> http {}".format(slug, code)); continue
            except Exception as e:
                print("  {} -> {}".format(slug, type(e).__name__)); continue
    table = {}
    for u, body in pages.items():
        slug = u.rsplit("/", 1)[-1]
        table[slug] = extract(strip(body))
        print("  {:<34} {}".format(slug, json.dumps(table[slug])))
    results["ratios"] = table
    # forward P/E rows of the start page
    txt = strip(first)
    fwd = re.findall(r"((?:Mar|Jun|Sep|Dec) 20\d\d)\s*[A-Z]{3}\s*[\d.,]+\s*[BMT]?\s*([\d.,]+)", txt)
    print("FORWARD rows:", fwd[:10])
    results["forward_rows"] = fwd[:10]

print("PROBE_SUMMARY " + json.dumps({"as_path": AS_PATH, "results": results}))
