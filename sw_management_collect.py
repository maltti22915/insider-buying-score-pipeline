"""
sw_management_collect.py v1.2 -- (v1.2: the expand step finds 'Show more' / 'Show all' / 'View all' on any element, not only buttons, clicks it once, and logs which controls it clicked.)
sw_management_collect.py v1 -- DATA COLLECTION ONLY (writes nothing to the sheet).
Collects the Simply Wall St "Management" (6) and "Ownership" (7) pages of every stock in a list, so that a "Skin in the Game" metric
can be designed from real data. Output (workflow artifact "sw-management-data"):
  sw_mgmt_all.json   one record per stock: pages.management / pages.ownership with the cleaned visible text lines,
                     table-like rows, headings, the green/red icons of "Management criteria checks n/4"
  sw_mgmt_all.txt    the same text, readable (one block per stock) -- the easiest file to hand over for analysis
  sw_mgmt_failed.txt stocks that did not work, with the reason

Engine: SeleniumBase CDP mode (the engine that passed Cloudflare 12 of 12 in sw_probe v2), ONE browser for many stocks (the
Cloudflare clearance is kept between pages); the browser is restarted after a block and every 12 stocks.

v1.1: the 16 Salkku stocks are built in (DEFAULT_ABBREVS below), so the workflow needs no input. Edit that list when stocks change.
Env: ABBREVS (optional; when set it REPLACES the built-in list; comma / space / newline separated Simply Wall St abbreviations,
     e.g. de/diversified-financials/etr-ftk/flatexdegiro-shares; full simplywall.st URLs are accepted too), PAGES (default "management,ownership"), WAIT_SECONDS (Cloudflare, default 30),
     PAUSE_SECONDS (between pages, default 3), OUT_DIR (default "sw_mgmt_out").
The extraction was written from screenshots, not from the page source: it takes ALL visible text of the page (after scrolling and
clicking "Show more"-type buttons) plus every table-like row, so nothing is lost; the metric work parses it afterwards.
"""
import csv, json, os, random, re, sys, time
from datetime import datetime, timezone
from seleniumbase import SB

WAIT = int(os.environ.get("WAIT_SECONDS", "30"))
PAUSE = float(os.environ.get("PAUSE_SECONDS", "3"))
PAGES = [p.strip() for p in os.environ.get("PAGES", "management,ownership").split(",") if p.strip()]
OUT_DIR = os.environ.get("OUT_DIR", "sw_mgmt_out")
RESTART_EVERY = 12

# Salkku stocks (abbrevSW from column D of the sheet, checked 2026-10-17)
DEFAULT_ABBREVS = """
us/media/nasdaq-app/applovin
de/diversified-financials/etr-ftk/flatexdegiro-shares
us/retail/nyse-baba/alibaba-group-holding
nl/retail/ams-prx/prosus-shares
us/transportation/nyse-uber/uber-technologies
de/media/etr-evd/cts-eventim-kgaa-shares
us/retail/nasdaq-amzn/amazoncom
us/software/nasdaq-adsk/autodesk
ca/software/tsx-csu/constellation-software-shares
us/retail/nasdaq-meli/mercadolibre
us/healthcare/nyse-unh/unitedhealth-group
us/diversified-financials/nyse-msci/msci
us/media/nasdaq-meta/meta-platforms
dk/pharmaceuticals-biotech/cph-chemm/chemometec-shares
de/software/etr-sap/sap-shares
us/software/nyse-now/servicenow
"""

CF_MARKERS = ("just a moment", "/challenge", "verify you are human", "checking your browser", "attention required")

EXTRACT_JS = r"""(function(){
  try {
    function t(e){ return ((e && e.innerText) || '').replace(/\s+/g,' ').trim(); }
    var root = document.querySelector('main') || document.body;
    var lines = String(root.innerText || '').split('\n').map(function(s){ return s.replace(/\s+/g,' ').trim(); }).filter(Boolean);
    var heads = [].slice.call(root.querySelectorAll('h1,h2,h3,h4')).map(t).filter(Boolean);
    var rows = [];
    [].slice.call(root.querySelectorAll('tr,[role=row]')).forEach(function(r){
      var cells = [].slice.call(r.querySelectorAll('th,td,[role=cell],[role=columnheader],[role=gridcell]')).map(t);
      if (cells.length > 1) { rows.push(cells); }
    });
    var icons = [];
    var all = [].slice.call(root.querySelectorAll('div,section,span,p,h2,h3'));
    var best = null;
    all.forEach(function(e){
      var tx = t(e);
      if (/criteria checks\s*\d\s*\/\s*\d/i.test(tx) && tx.length < 200 && e.querySelectorAll('svg').length >= 2) {
        if (!best || tx.length < t(best).length) { best = e; }
      }
    });
    if (best) {
      [].slice.call(best.querySelectorAll('svg')).forEach(function(s){
        var cs = getComputedStyle(s);
        var p = s.querySelector('path,circle');
        var pc = p ? getComputedStyle(p) : null;
        icons.push({color: cs.color, stroke: pc ? pc.stroke : '', fill: pc ? pc.fill : ''});
      });
    }
    return JSON.stringify({ok: true, url: location.href, title: document.title, heads: heads, lines: lines, rows: rows, icons: icons});
  } catch (e) { return JSON.stringify({ok: false, error: String(e)}); }
})()"""

EXPAND_JS = r"""(function(){
  var clicked = [], seen = [];
  var els = [].slice.call(document.querySelectorAll('button,a,[role=button],div,span,p'));
  els.forEach(function(e){
    if (e.children.length > 3) { return; }
    var tx = (e.innerText || '').replace(/\s+/g,' ').trim();
    if (!tx || tx.length > 40) { return; }
    if (/^(show|view|see|load|read)\s+(more|all|full)\b/i.test(tx) || /^(more|expand)$/i.test(tx)) {
      if (/update|news|less|hide/i.test(tx)) { return; }
      seen.push(tx);
      var target = e.closest('button,a,[role=button]') || e;
      if (target.getAttribute && target.getAttribute('data-sw-clicked')) { return; }
      try { target.setAttribute('data-sw-clicked', '1'); target.scrollIntoView({block:'center'}); target.click(); clicked.push(tx); } catch (err) {}
    }
  });
  return JSON.stringify({clicked: clicked, seen: seen});
})()"""


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def clean_abbrev(token):
    token = token.strip().strip(",;")
    token = re.sub(r"^https?://(www\.)?simplywall\.st/stocks/", "", token)
    token = re.sub(r"/(valuation|future|past|health|dividend|management|ownership|news)?/?$", "", token)
    return token.strip("/")


def parse_abbrevs(text):
    out, seen = [], set()
    for token in re.split(r"[\s,;]+", text or ""):
        a = clean_abbrev(token)
        if a and "/" in a and a not in seen:
            seen.add(a)
            out.append(a)
    return out


class Browser(object):
    def __init__(self):
        self.ctx = SB(uc=True, test=True, locale="en")
        self.sb = self.ctx.__enter__()
        self.opened = False
        self.count = 0

    def close(self):
        try:
            self.ctx.__exit__(None, None, None)
        except Exception:
            pass

    def open(self, url):
        if not self.opened:
            self.sb.activate_cdp_mode(url)
            self.opened = True
        else:
            self.sb.cdp.open(url)
        time.sleep(3)

    def js(self, expression):
        return self.sb.cdp.evaluate(expression)

    def is_challenge(self):
        try:
            title = (self.sb.cdp.get_title() or "").lower()
            url = (self.sb.cdp.get_current_url() or "").lower()
            body = (self.js("String(document.body ? document.body.innerText : '').slice(0, 600)") or "").lower()
        except Exception:
            return True
        hay = title + " " + url + " " + body
        return any(m in hay for m in CF_MARKERS)

    def wait_clear(self):
        t0 = time.monotonic()
        last_click = None
        while self.is_challenge():
            if time.monotonic() - t0 > WAIT:
                return False
            now = time.monotonic()
            if last_click is None or now - last_click >= 8:
                last_click = now
                try:
                    self.sb.cdp.solve_captcha()
                except Exception:
                    pass
            time.sleep(2)
        return True

    def scroll_all(self):
        last_height, same = 0, 0
        for _ in range(40):
            try:
                self.js("window.scrollBy(0, 900)")
                time.sleep(0.6)
                height = int(self.js("document.body.scrollHeight") or 0)
            except Exception:
                break
            same = same + 1 if height == last_height else 0
            last_height = height
            if same >= 3:
                break
        try:
            self.js("window.scrollTo(0, 0)")
        except Exception:
            pass

    def read_page(self, url):
        self.open(url)
        if not self.wait_clear():
            raise RuntimeError("blocked by Cloudflare")
        time.sleep(2)
        self.scroll_all()
        expanded = 0
        controls = []
        for _ in range(4):
            res = self.js(EXPAND_JS)
            try:
                res = json.loads(res) if isinstance(res, str) else (res or {})
            except Exception:
                res = {}
            n = len(res.get("clicked") or [])
            controls.extend(res.get("clicked") or [])
            expanded += n
            if not n:
                break
            time.sleep(1.5)
            self.scroll_all()
        raw = self.js(EXTRACT_JS)
        data = json.loads(raw) if isinstance(raw, str) else raw
        if not data or not data.get("ok"):
            raise RuntimeError("extract failed: {}".format((data or {}).get("error")))
        if len(data.get("lines") or []) < 15:
            raise RuntimeError("page nearly empty ({} lines)".format(len(data.get("lines") or [])))
        data["expandedClicks"] = expanded
        data["clickedControls"] = controls
        return data


def collect_stock(browser, abbrev):
    record = {"abbrev": abbrev, "scrapedAtUtc": now_iso(), "pages": {}, "errors": {}}
    for page in PAGES:
        url = "https://simplywall.st/stocks/{}/{}".format(abbrev, page)
        try:
            record["pages"][page] = browser.read_page(url)
            print("  OK   {} | {} lines | {} rows | icons={} | expanded={} {}".format(
                page, len(record["pages"][page]["lines"]), len(record["pages"][page]["rows"]),
                len(record["pages"][page]["icons"]), record["pages"][page]["expandedClicks"],
                record["pages"][page].get("clickedControls") or ""), flush=True)
        except Exception as e:
            record["errors"][page] = "{}: {}".format(type(e).__name__, str(e)[:150])
            print("  FAIL {} | {}".format(page, record["errors"][page]), flush=True)
            if "Cloudflare" in str(e):
                break
        time.sleep(PAUSE + random.uniform(0, 2))
    return record


def write_outputs(records):
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, "sw_mgmt_all.json"), "w", encoding="utf-8") as fh:
        json.dump(records, fh, ensure_ascii=False, indent=1)
    with open(os.path.join(OUT_DIR, "sw_mgmt_all.txt"), "w", encoding="utf-8") as fh:
        for r in records:
            fh.write("=" * 100 + "\nSTOCK {} | read {}\n".format(r["abbrev"], r["scrapedAtUtc"]) + "=" * 100 + "\n")
            for page, d in r["pages"].items():
                fh.write("\n----- {} ({}) -----\n".format(page.upper(), d.get("title", "")))
                if d.get("icons"):
                    fh.write("[criteria icons: {}]\n".format("; ".join("color={} stroke={}".format(i.get("color"), i.get("stroke")) for i in d["icons"])))
                fh.write("\n".join(d.get("lines", [])) + "\n")
                if d.get("rows"):
                    fh.write("\n[table-like rows]\n" + "\n".join(" | ".join(c) for c in d["rows"]) + "\n")
            for page, err in r["errors"].items():
                fh.write("\n!!! {} FAILED: {}\n".format(page, err))
            fh.write("\n")
    failed = [r for r in records if r["errors"]]
    with open(os.path.join(OUT_DIR, "sw_mgmt_failed.txt"), "w", encoding="utf-8") as fh:
        for r in failed:
            fh.write("{} | {}\n".format(r["abbrev"], json.dumps(r["errors"])))


def main():
    abbrevs = parse_abbrevs(os.environ.get("ABBREVS", "").strip() or DEFAULT_ABBREVS)
    if not abbrevs:
        print("no abbreviations to collect")
        sys.exit(1)
    print("SW management collect v1.2 | {} stocks | pages={}".format(len(abbrevs), PAGES), flush=True)
    records, browser = [], None
    try:
        for index, abbrev in enumerate(abbrevs, 1):
            print("[{}/{}] {}".format(index, len(abbrevs), abbrev), flush=True)
            record = None
            for attempt in (1, 2):
                if browser is None or browser.count >= RESTART_EVERY:
                    if browser is not None:
                        browser.close()
                    browser = Browser()
                try:
                    record = collect_stock(browser, abbrev)
                    browser.count += 1
                except Exception as e:
                    record = {"abbrev": abbrev, "scrapedAtUtc": now_iso(), "pages": {}, "errors": {"run": str(e)[:150]}}
                blocked = any("Cloudflare" in v for v in record["errors"].values())
                if blocked and attempt == 1:
                    print("  blocked -> new browser, one more try", flush=True)
                    browser.close()
                    browser = None
                    time.sleep(random.uniform(10, 20))
                    continue
                break
            records.append(record)
            write_outputs(records)
    finally:
        if browser is not None:
            browser.close()
    ok = [r for r in records if r["pages"] and not r["errors"]]
    summary = "## SW management collect: {} of {} stocks complete\n\n{}\n".format(
        len(ok), len(records), "\n".join("- {}: {}".format(r["abbrev"], "ok" if r["pages"] and not r["errors"] else json.dumps(r["errors"])) for r in records))
    print(summary)
    sf = os.environ.get("GITHUB_STEP_SUMMARY")
    if sf:
        with open(sf, "a", encoding="utf-8") as fh:
            fh.write(summary)


if __name__ == "__main__":
    main()
