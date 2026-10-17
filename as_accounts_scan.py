"""as_accounts_scan.py v3 -- AlphaSpread account scan for the StockData_60 "AS accounts" sheet.
Started by Apps Script fn_26_50_ASAccountsUpdate (workflow "AS Accounts Scan", input "accounts" = JSON list from the sheet).
Per account: log in, read the logged-in pages, detect the stocks opened on that account and the used/free slots (free plan = 3).
Output (artifact "as-accounts-scan", fetched by fn_26_51_ASAccountsFetch):
  as_scan_out/as_accounts_scan.json  {version, nonce, at, results:[{label,status,used,free,stocks,detector,note}]}
  as_scan_out/as_accounts_scan_debug.txt  (per page: stock links + slot-like text lines; used to refine the detector)
Passwords are never printed or written (masked in the Actions log, scrubbed from every output).

Detector v3 (from the user's screenshots, 2026-10-17):
  login   = /login, fill E-mail address + Password, click "Sign in with email" (never the Google button).
  counter = header badge "Free Plan: N / M" (red, top right)  -> used = N, slots = M, free = M - N.
  stocks  = click the badge -> click "Show Stock Spots" -> modal "Free Plan: Stock Spots" lists
            "1 / <company name> / <ticker>" per spot  -> stocks "TICKER (Company)". If the modal also has
            /security/<exchange>/<ticker> links, those are kept as well (exchange/ticker form) for abbrevAS matching.
            Confirmed: "3 / 3" = 3 used of 3 weekly stock views.
  Free plan is capped at 3 stocks PER WEEK, so the result is this week's spots.

CHANGE LOG
v3 (2026-10-17): stocks read from the "Free Plan: Stock Spots" modal text (numbered list: name + ticker), not from
    page links; modal links kept as "links" for exchange/ticker matching; Stocks written as "TICKER (Company)".
v2 (2026-10-17): real AlphaSpread flow: /login, "Sign in with email" button, "Free Plan: N / M" badge counter,
    "Show Stock Spots" list; screenshots of the badge popup and spots list in the artifact (after login only).
v1 (2026-10-17): first version.
"""
import json, os, re, sys, time
from datetime import datetime, timezone
from seleniumbase import SB

VERSION = "as_accounts_scan v3"
BASE = "https://www.alphaspread.com"
OUT = os.environ.get("OUT_DIR", "as_scan_out")
SLOTS = 3
DEFAULT_PAGES = ""
PAGES = [p.strip() for p in (os.environ.get("PAGES") or DEFAULT_PAGES).split(",") if p.strip()]
NONCE = (os.environ.get("NONCE") or "").strip()
WAIT = float(os.environ.get("WAIT_SECONDS") or 3)
SEC_RX = re.compile(r"^(?:https?://(?:www\.)?alphaspread\.com)?/security/([A-Za-z0-9.\-_]+)/([A-Za-z0-9.\-_]+)", re.I)
COUNTER_RX = re.compile(r"\b([0-3])\s*(?:/|of|out of)\s*3\b", re.I)
COUNTER_HINT = re.compile(r"stock|analys|slot|unlock|free|plan|limit|view", re.I)

PAGE_JS = r"""(function(){
  var lines=String((document.body||document.documentElement).innerText||'').split('\n')
    .map(function(s){return s.replace(/\s+/g,' ').trim();}).filter(Boolean);
  var links=[].slice.call(document.querySelectorAll('a[href]')).map(function(a){return a.getAttribute('href')||'';});
  return JSON.stringify({url:location.href,title:document.title,lines:lines.slice(0,500),links:links.slice(0,800),
    pw:!!document.querySelector('input[type=password]')});
})()"""

CLICK_JS = r"""(function(re){
  var rx=new RegExp(re,'i');
  var els=[].slice.call(document.querySelectorAll('a,button,[role=button]'));
  for(var i=0;i<els.length;i++){var tx=(els[i].innerText||'').replace(/\s+/g,' ').trim();
    if(tx&&tx.length<30&&rx.test(tx)){els[i].click();return 'clicked '+tx;}}
  return 'notfound';
})(%s)"""

FILL_JS = r"""(function(email,pw){
  function set(el,v){var d=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value');d.set.call(el,v);
    el.dispatchEvent(new Event('input',{bubbles:true}));el.dispatchEvent(new Event('change',{bubbles:true}));}
  var p=document.querySelector('input[type=password]'); if(!p){return 'no-password-field';}
  var scope=p.closest('form')||p.closest('[role=dialog]')||p.parentElement.parentElement.parentElement||document;
  var sels=['input[type=email]','input[name*=mail i]','input[autocomplete=username]','input[name*=user i]','input[type=text]'];
  var e=null;for(var i=0;i<sels.length&&!e;i++){e=scope.querySelector(sels[i]);}
  if(!e){return 'no-email-field';}
  set(e,email);set(p,pw);return 'filled';
})(%s,%s)"""

SUBMIT_JS = r"""(function(){
  var els=[].slice.call(document.querySelectorAll('button,input[type=submit],a,[role=button]'));
  for(var i=0;i<els.length;i++){var tx=(els[i].innerText||els[i].value||'').replace(/\s+/g,' ').trim();
    if(/sign in with e-?mail/i.test(tx)){els[i].click();return 'clicked '+tx;}}
  var p=document.querySelector('input[type=password]'); var f=p&&p.closest('form');
  var b=f?f.querySelector('button[type=submit],input[type=submit]'):null;
  if(b&&!/google/i.test(b.innerText||'')){b.click();return 'submit-click';}
  return 'no-email-button';
})()"""

BADGE_JS = r"""(function(click){
  var els=[].slice.call(document.querySelectorAll('a,button,span,div,[role=button]'));
  var best=null;
  for(var i=0;i<els.length;i++){var tx=(els[i].innerText||'').replace(/\s+/g,' ').trim();
    if(/^free plan:\s*\d+\s*\/\s*\d+$/i.test(tx)){best=els[i];}}
  if(!best){return 'notfound';}
  var tx=(best.innerText||'').replace(/\s+/g,' ').trim();
  if(click){best.click();}
  return tx;
})(%s)"""

# Text + links of the "Free Plan: Stock Spots" modal only.
SPOTS_JS = r"""(function(){
  var els=[].slice.call(document.querySelectorAll('h1,h2,h3,h4,h5,div,span,p'));
  var head=null;
  for(var i=0;i<els.length;i++){var tx=(els[i].innerText||'').replace(/\s+/g,' ').trim();
    if(/^free plan:\s*stock spots$/i.test(tx)){head=els[i];break;}}
  if(!head){return JSON.stringify({found:false});}
  var box=head.closest('[role=dialog],.modal,.modal-content,[class*=modal i],[class*=dialog i]');
  if(!box){box=head;for(var k=0;k<6&&box.parentElement;k++){box=box.parentElement;
    if(/you.ve used/i.test(box.innerText||'')&&/\n\s*1\s*\n/.test(box.innerText||'')){break;}}}
  var lines=String(box.innerText||'').split('\n').map(function(s){return s.replace(/\s+/g,' ').trim();}).filter(Boolean);
  var links=[].slice.call(box.querySelectorAll('a[href]')).map(function(a){return a.getAttribute('href')||'';});
  return JSON.stringify({found:true,lines:lines.slice(0,80),links:links.slice(0,40)});
})()"""

HAS_PW_JS = "!!document.querySelector('input[type=password]')"


def log(msg):
    print("[{}] {}".format(VERSION, msg), flush=True)


def js(sb, expr):
    try:
        return sb.cdp.evaluate(expr)
    except Exception as e:
        return "ERR " + str(e)[:120]


def page(sb):
    raw = js(sb, PAGE_JS)
    try:
        return json.loads(raw)
    except Exception:
        return {"error": str(raw)[:200], "lines": [], "links": [], "pw": None}


def wait_cf(sb):
    for _ in range(8):
        title = (sb.cdp.get_title() or "").lower()
        if "just a moment" not in title:
            return True
        try:
            sb.cdp.solve_captcha()
        except Exception:
            pass
        time.sleep(4)
    return False


def sec_links(links):
    out = set()
    for h in links:
        m = SEC_RX.match(h or "")
        if m:
            out.add("{}/{}".format(m.group(1).lower(), m.group(2).lower()))
    return out


def counters(lines):
    hits = []
    for ln in lines:
        if len(ln) < 160 and COUNTER_HINT.search(ln):
            m = COUNTER_RX.search(ln)
            if m:
                hits.append((int(m.group(1)), ln))
    return hits


TICKER_RX = re.compile(r"^[A-Z0-9][A-Z0-9.\-]{0,11}$")


def parse_spots(lines):
    """Modal lines: '1', ['Uber' logo text], 'Uber Technologies Inc', 'UBER', '2', ... -> [('UBER','Uber Technologies Inc'), ...]
    Each spot = lines between a number line (1-9) and the next number line / button line; ticker = last ticker-like
    line in the block, company = the longest other line."""
    stop = re.compile(r"^(start free trial|close|view plans)$", re.I)
    starts = [i for i, l in enumerate(lines) if re.fullmatch(r"[1-9]", l)]
    out, seen = [], set()
    for k, i in enumerate(starts):
        j = starts[k + 1] if k + 1 < len(starts) else len(lines)
        block = []
        for l in lines[i + 1:j]:
            if stop.match(l):
                break
            block.append(l)
        ticks = [l for l in block if TICKER_RX.match(l)]
        if not ticks:
            continue
        tick = ticks[-1]
        names = [l for l in block if l != tick]
        name = max(names, key=len) if names else ""
        if tick not in seen:
            seen.add(tick); out.append((tick, name))
    return out


def shot(sb, label, name):
    try:
        sb.cdp.save_screenshot(os.path.join(OUT, "{}_{}.png".format(label, name)))
    except Exception:
        pass


def scan_account(acc):
    label = acc.get("label")
    r = {"label": label, "status": "", "pages": {}, "home_links": [], "steps": [],
         "badge": "", "spot_links": [], "before_links": [], "spots": [], "spots_lines": []}
    with SB(uc=True, test=True, locale="en") as sb:
        sb.activate_cdp_mode(BASE + "/login")
        if not wait_cf(sb):
            r["status"] = "Cloudflare blocked"; return r
        time.sleep(WAIT)
        if js(sb, HAS_PW_JS) is not True:
            r["steps"].append("login click: " + str(js(sb, CLICK_JS % json.dumps(r"^(log ?in|sign ?in)$"))))
            time.sleep(WAIT); wait_cf(sb)
        fill = str(js(sb, FILL_JS % (json.dumps(acc["email"]), json.dumps(acc["password"]))))
        r["steps"].append("fill: " + fill)
        if fill != "filled":
            r["status"] = "login form not found"; return r
        time.sleep(1)
        r["steps"].append("submit: " + str(js(sb, SUBMIT_JS)))
        time.sleep(WAIT * 2); wait_cf(sb)
        after = page(sb)
        if after.get("pw"):
            bad = [l for l in after.get("lines", []) if re.search(r"invalid|incorrect|wrong|not found|verify", l, re.I)]
            r["status"] = "login failed" + (": " + bad[0][:60] if bad else "")
            return r
        r["status"] = "OK"
        r["pages"]["after_login"] = after
        shot(sb, label, "1_after_login")

        badge = str(js(sb, BADGE_JS % "false"))
        if badge == "notfound":  # badge may render late or only on the dashboard
            sb.cdp.open(BASE + "/dashboard/watchlists"); wait_cf(sb); time.sleep(WAIT)
            badge = str(js(sb, BADGE_JS % "false"))
        r["badge"] = badge if badge != "notfound" else ""
        r["steps"].append("badge: " + badge)
        before = sec_links(page(sb).get("links", []))
        r["before_links"] = sorted(before)
        if r["badge"]:
            js(sb, BADGE_JS % "true"); time.sleep(2)
            shot(sb, label, "2_badge_popup")
            r["steps"].append("spots: " + str(js(sb, CLICK_JS % json.dumps(r"^show stock spots$"))))
            time.sleep(WAIT); wait_cf(sb)
            raw = js(sb, SPOTS_JS)
            try:
                modal = json.loads(raw)
            except Exception:
                modal = {"found": False, "error": str(raw)[:160]}
            shot(sb, label, "3_stock_spots")
            r["steps"].append("spots modal found: " + str(modal.get("found")))
            if modal.get("found"):
                r["spots_lines"] = modal.get("lines", [])
                r["spots"] = parse_spots(r["spots_lines"])
                r["spot_links"] = sorted(sec_links(modal.get("links", [])))
            else:
                spots = page(sb)
                r["pages"]["stock_spots"] = spots
                r["spot_links"] = sorted(sec_links(spots.get("links", [])) - before)
        for path in PAGES:
            try:
                sb.cdp.open(BASE + path); wait_cf(sb); time.sleep(WAIT)
                r["pages"][path] = page(sb)
            except Exception as e:
                r["pages"][path] = {"error": str(e)[:160], "lines": [], "links": []}
    return r


def scrub(obj, secrets):
    s = json.dumps(obj, ensure_ascii=False)
    for sec in secrets:
        s = s.replace(sec, "***")
    return json.loads(s)


def main():
    log("start | nonce " + (NONCE or "-") + " | pages " + ",".join(PAGES))
    try:
        accounts = json.loads((os.environ.get("ACCOUNTS_JSON") or "").strip() or "[]")
    except Exception:
        log("accounts input is not valid JSON"); sys.exit(1)
    accounts = [a for a in accounts if a.get("label") and a.get("email") and a.get("password")]
    if not accounts:
        log("no complete accounts (label + email + password) in the input"); sys.exit(1)
    secrets = [a["password"] for a in accounts]
    for sec in secrets:
        print("::add-mask::" + sec)
    os.makedirs(OUT, exist_ok=True)
    log("accounts: " + ", ".join(a["label"] for a in accounts))

    raw = []
    for acc in accounts:
        try:
            r = scan_account(acc)
        except Exception as e:
            r = {"label": acc["label"], "status": "error: " + str(e)[:100], "pages": {}, "home_links": [], "steps": []}
        r = scrub(r, secrets)
        log("{}: {} | {}".format(r["label"], r["status"], " || ".join(r["steps"])))
        raw.append(r)

    # detector v2
    results = []
    for r in raw:
        res = {"label": r["label"], "status": r["status"], "used": "", "free": "", "stocks": [], "detector": "", "note": ""}
        if r["status"] == "OK":
            m = re.search(r"(\d+)\s*/\s*(\d+)", r.get("badge") or "")
            stocks = ["{} ({})".format(t, n) for t, n in r.get("spots", [])] or (r.get("spot_links") or [])
            res["links"] = r.get("spot_links") or []
            if m:
                used, slots = int(m.group(1)), int(m.group(2))
                res["detector"] = "badge"
            else:
                used, slots = min(len(stocks), SLOTS), SLOTS
                res["detector"] = "spots-only"; res["note"] = "badge not found"
            res.update(used=used, free=max(slots - used, 0), stocks=stocks)
            if r.get("badge") and len(stocks) != used:
                res["note"] = (res["note"] + " | " if res["note"] else "") + \
                    "{} spots read vs badge {} (check debug)".format(len(stocks), r["badge"])
        results.append(res)
        log("{}: badge='{}' used={} free={} stocks={} ({})".format(res["label"], r.get("badge", ""), res["used"],
            res["free"], ",".join(res["stocks"]) or "-", res["detector"] or "-"))

    out = {"version": VERSION, "nonce": NONCE, "at": datetime.now(timezone.utc).isoformat(), "results": results}
    with open(os.path.join(OUT, "as_accounts_scan.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    with open(os.path.join(OUT, "as_accounts_scan_debug.txt"), "w", encoding="utf-8") as fh:
        fh.write("{} | nonce {}\n".format(VERSION, NONCE))
        for r in raw:
            fh.write("=" * 70 + "\n{} | {}\n{}\n".format(r["label"], r["status"], "\n".join(r["steps"])))
            fh.write("links before spots click (excluded): " + (", ".join(r.get("before_links", [])) or "-") + "\n")
            fh.write("spot links: " + (", ".join(r.get("spot_links", [])) or "-") + "\n")
            fh.write("spots parsed: " + (", ".join("{} ({})".format(t, n) for t, n in r.get("spots", [])) or "-") + "\n")
            fh.write("spots modal text:\n" + "\n".join("  | " + l for l in r.get("spots_lines", [])) + "\n")
            for name, d in r["pages"].items():
                fh.write("\n--- {} | {} | {}\n".format(name, d.get("url"), d.get("title")))
                fh.write("stock links: " + (", ".join(sorted(sec_links(d.get("links", [])))) or "-") + "\n")
                lines = d.get("lines", [])
                if name == "stock_spots":
                    lines = lines[:200]
                else:
                    lines = [ln for ln in lines if re.search(r"\d", ln) and COUNTER_HINT.search(ln) and len(ln) < 160]
                for ln in lines:
                    fh.write("  text: " + ln + "\n")
    log("done")


if __name__ == "__main__":
    main()
