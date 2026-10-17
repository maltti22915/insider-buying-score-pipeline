"""
sw_skin.py v1 -- "Skin" score (skin in the game of management, 0-100) from Simply Wall St Management + Ownership pages.

What it does: for every stock (built-in Salkku list, or env ABBREVS) it opens the SW Management and Ownership pages in ONE
browser (same engine as sw_management_collect.py: CDP mode, lazy sections scrolled in), computes the score and the
explanation note in Python, and POSTs {score, note, inputs} to the Apps Script webhook (target "SKIN", handler
fn_91_10_SkinHandler). The webhook finds the sheet rows by abbrevSW (column D) in Salkku AND Moat and writes the
"Skin" column + the note next to it. The data changes slowly: run it weekly / by hand, not with every row refresh.

Score (0-100):
  Insider stake      30  Individual Insiders % (SW Ownership Breakdown) AND the USD value of that stake
  CEO alignment      45  CEO ownership % AND its USD value (if SW has no CEO ownership: largest leadership-team holder)
  Team breadth       15  average stake value over everybody in the Leadership + Board tables ("no data" = 0)
  Founder / tenure   10  founder or co-founder in the first leadership rows, or CEO tenure >= 10 y (10), >= 5 y (6), >= 2 y (3)
Size is handled by using BOTH lenses (percent of the company and money at stake): weight 70 % on the better lens, 30 % on the weaker.
Insider buying/selling is NOT part of this score (separate metric).

Env: GAS_WEBHOOK_URL (secret, required unless DRY_RUN=1), ABBREVS (optional), SHEETS (default "Salkku,Moat"),
     DRY_RUN=1 (collect + score, post nothing), OUT_DIR (default sw_skin_out), WAIT_SECONDS / PAUSE_SECONDS (as the collector).
Needs sw_management_collect.py in the same folder (browser engine).
"""
import json, math, os, re, sys, time
import requests

VERSION = "v1"

# approximate FX to USD (only used to size the stake in money terms; refresh now and then)
FX = {"US$": 1.0, "$": 1.0, "€": 1.16, "EUR": 1.16, "CA$": 0.72, "C$": 0.72, "DKK": 0.155, "DKr": 0.155, "kr": 0.155,
      "CN¥": 0.14, "¥": 0.0066, "£": 1.30, "R$": 0.18, "CHF": 1.25, "A$": 0.65, "HK$": 0.128, "S$": 0.75, "NT$": 0.031,
      "SEK": 0.10, "NOK": 0.095}
UNIT = {"": 1e-6, "k": 1e-3, "m": 1.0, "b": 1e3, "t": 1e6}


def _lin(x, pts):
    if x is None:
        return 0.0
    for (a, fa), (b, fb) in zip(pts, pts[1:]):
        if x <= b:
            return fa + (fb - fa) * (max(x, a) - a) / (b - a)
    return pts[-1][1]


PCT_PTS = [(0, 0.0), (0.5, 0.2), (2, 0.4), (5, 0.6), (15, 0.85), (30, 1.0)]
VAL_PTS = [(0.5, 0.0), (1.7, 0.3), (2.4, 0.5), (3.0, 0.75), (3.7, 1.0)]  # log10(USD millions): 3M ... 5B


def pct_lens(p):
    return _lin(p, PCT_PTS) if p is not None else 0.0


def val_lens(usd_m):
    if not usd_m or usd_m <= 0:
        return 0.0
    return _lin(math.log10(usd_m), VAL_PTS)


def money(usd_m):
    if usd_m is None:
        return "n/a"
    if usd_m >= 1000:
        return "${:.1f}B".format(usd_m / 1000.0)
    if usd_m >= 1:
        return "${:.0f}M".format(usd_m)
    return "${:.0f}k".format(usd_m * 1000.0)


def to_usd_m(cur, num, unit):
    f = FX.get(cur.strip())
    if f is None:
        return None
    return num * UNIT.get(unit.lower(), 1e-6) * f


def parse_market_cap(lines):
    for l in lines:
        m = re.match(r"Market Cap:\s*([^\d\s]*\s?[A-Za-z$€£¥]*?)\s*([\d.,]+)\s*([kmbt]?)\s*$", l.strip(), re.I)
        if m:
            cur = m.group(1).replace(" ", "")
            try:
                return to_usd_m(cur, float(m.group(2).replace(",", "")), m.group(3)), l.strip()
            except ValueError:
                pass
    return None, None


def section(lines, a, b):
    try:
        i = lines.index(a)
        j = lines.index(b, i + 1)
        return lines[i + 1:j]
    except ValueError:
        return []


def parse_people(sec):
    """Rows are 'Name' then 'Position tenure comp ownership' (+ optional value line). Returns list of dicts."""
    out, i = [], 0
    while i < len(sec) - 1:
        row = sec[i + 1]
        m = re.search(r"(\d+(?:\.\d+)?)%$|no data$", row)
        if m and not re.search(r"%$", sec[i]) and not sec[i].startswith("Name Position"):
            out.append({"name": sec[i], "row": row, "pct": float(m.group(1)) if m.group(1) else None})
            i += 2
        else:
            i += 1
    for p in out:
        t = re.search(r"(less than a year|no data|[\d.]+yrs?)\s+(?:\S+\s)?", p["row"])
        p["position"] = re.split(r"\s+(?:less than a year|no data|[\d.]+yrs?)\b", p["row"])[0]
    return out


def parse_inputs(mgmt_lines, own_lines):
    text = " ".join(mgmt_lines)
    cap, cap_text = parse_market_cap(mgmt_lines) if parse_market_cap(mgmt_lines)[0] else parse_market_cap(own_lines)
    ceo_pct = None
    m = re.search(r"Ceo ownership ([\d.]+)%", text)
    if m:
        ceo_pct = float(m.group(1))
    ten = None
    m = re.search(r"Ceo tenure ([\d.]+)yrs", text)
    if m:
        ten = float(m.group(1))
    elif "Ceo tenure less than a year" in text:
        ten = 0.5
    ceo_name = None
    for k, l in enumerate(mgmt_lines):
        if l == "Chief executive officer" and k > 0:
            ceo_name = mgmt_lines[k - 1]
            break
    ind = None
    for l in own_lines:
        m = re.match(r"Individual Insiders ([\d.]+)%", l)
        if m:
            ind = float(m.group(1))
            break
    lead = parse_people(section(mgmt_lines, "Leadership Team", "Board Members"))
    board = parse_people(section(mgmt_lines, "Board Members", "Ownership"))
    return {"capUsdM": cap, "capText": cap_text, "ceoName": ceo_name, "ceoPct": ceo_pct, "ceoTenure": ten,
            "insiderPct": ind, "leaders": lead, "board": board}


def score(inp):
    cap = inp["capUsdM"]
    notes = []
    # 1 insider stake (30)
    ind = inp["insiderPct"]
    ind_val = ind / 100.0 * cap if (ind is not None and cap) else None
    pl, vl = pct_lens(ind), val_lens(ind_val)
    stake = 30 * (0.7 * max(pl, vl) + 0.3 * min(pl, vl))
    notes.append("Insider stake {:.0f}/30: individual insiders own {} ({}); % lens {:.0%}, money lens {:.0%}".format(
        stake, "{}%".format(ind) if ind is not None else "n/a", money(ind_val), pl, vl))
    # 2 CEO (45)
    ceo = inp["ceoPct"]
    basis = "CEO {}".format(inp["ceoName"] or "")
    if ceo is None:
        cands = [p["pct"] for p in inp["leaders"] if p["pct"] is not None]
        if cands:
            ceo = max(cands)
            basis = "SW has no CEO ownership; largest leadership holder used"
        else:
            basis = "SW has no CEO / leadership ownership data"
    ceo_val = ceo / 100.0 * cap if (ceo is not None and cap) else None
    cp, cv = pct_lens(ceo), val_lens(ceo_val)
    ceo_pts = 45 * (0.6 * max(cp, cv) + 0.4 * min(cp, cv))
    if ceo is None:
        notes.append("CEO alignment 0/45: {}".format(basis.strip()))
    else:
        notes.append("CEO alignment {:.0f}/45: {} owns {}% ({}); % lens {:.0%}, money lens {:.0%}".format(
            ceo_pts, basis.strip(), ceo, money(ceo_val), cp, cv))
    # 3 breadth (15)
    people = inp["leaders"] + inp["board"]
    seen, vals = set(), []
    for p in people:
        if p["name"] in seen:
            continue
        seen.add(p["name"])
        vals.append(val_lens(p["pct"] / 100.0 * cap) if (p["pct"] is not None and cap) else 0.0)
    avg = sum(vals) / len(vals) if vals else 0.0
    breadth = 15 * min(1.0, 2.0 * avg)
    holders = sum(1 for v in vals if v > 0)
    notes.append("Team breadth {:.0f}/15: {} of {} leaders/directors have a stake with data (average money lens {:.0%}, x2 capped)".format(
        breadth, holders, len(vals), avg))
    # 4 founder / tenure (10)
    founder = any(re.search(r"founder", p["position"], re.I) for p in inp["leaders"][:3])
    ten = inp["ceoTenure"] or 0
    ft = 10 if (founder or ten >= 10) else 6 if ten >= 5 else 3 if ten >= 2 else 0
    notes.append("Founder/tenure {}/10: {}CEO tenure {}".format(
        ft, "founder in top management, " if founder else "", "{:g} y".format(inp["ceoTenure"]) if inp["ceoTenure"] is not None else "n/a"))
    total = int(round(stake + ceo_pts + breadth + ft))
    return total, notes, {"stake": round(stake, 1), "ceo": round(ceo_pts, 1), "breadth": round(breadth, 1), "founder": ft}


def build_note(abbrev, inp, total, notes):
    head = "Skin in the Game {}/100 (Simply Wall St Management + Ownership pages)".format(total)
    cap = "Market cap approx {} ({}); stakes valued at market cap x %, FX approximate".format(
        money(inp["capUsdM"]), inp["capText"] or "n/a")
    foot = "Insider buying/selling is a separate metric. Updated {}.".format(time.strftime("%Y-%m-%d", time.gmtime()))
    return "\n".join([head, ""] + notes + ["", cap, foot])


def score_page_lines(abbrev, mgmt_lines, own_lines):
    inp = parse_inputs(mgmt_lines, own_lines)
    total, notes, parts = score(inp)
    return {"abbrevSW": abbrev, "score": total, "parts": parts, "note": build_note(abbrev, inp, total, notes),
            "inputs": {k: inp[k] for k in ("capUsdM", "ceoName", "ceoPct", "ceoTenure", "insiderPct")}}


# ---------------------------------------------------------------------------------------------- runner
def post(webhook, result, sheets):
    payload = {"target": "SKIN", "abbrevSW": result["abbrevSW"], "sheetNames": sheets,
               "data": {"score": result["score"], "note": result["note"], "parts": result["parts"], "inputs": result["inputs"]}}
    for attempt in (1, 2, 3):
        try:
            r = requests.post(webhook, json=payload, timeout=120)
            try:
                body = r.json()
            except Exception:
                body = {"raw": r.text[:200]}
            if body.get("ok") or body.get("reason") not in ("LOCK_TIMEOUT",):
                return body
        except Exception as e:
            body = {"ok": False, "reason": "post_failed:" + type(e).__name__}
        time.sleep(15 * attempt)
    return body


def main():
    import sw_management_collect as c
    abbrevs = c.parse_abbrevs(os.environ.get("ABBREVS", "").strip() or c.DEFAULT_ABBREVS)
    dry = os.environ.get("DRY_RUN", "") == "1"
    webhook = os.environ.get("GAS_WEBHOOK_URL", "")
    sheets = [s.strip() for s in os.environ.get("SHEETS", "Salkku,Moat").split(",") if s.strip()]
    out_dir = os.environ.get("OUT_DIR", "sw_skin_out")
    os.makedirs(out_dir, exist_ok=True)
    if not dry and not webhook:
        print("GAS_WEBHOOK_URL is missing"); sys.exit(1)
    print("SW skin {} | {} stocks | dry={}".format(VERSION, len(abbrevs), dry), flush=True)
    results, browser = [], None
    try:
        for idx, abbrev in enumerate(abbrevs, 1):
            print("[{}/{}] {}".format(idx, len(abbrevs), abbrev), flush=True)
            res = None
            for attempt in (1, 2):
                if browser is None or browser.count >= c.RESTART_EVERY:
                    if browser is not None:
                        browser.close()
                    browser = c.Browser()
                rec = c.collect_stock(browser, abbrev)
                browser.count += 1
                if len(rec["pages"]) == 2 and not rec["errors"]:
                    res = score_page_lines(abbrev, rec["pages"]["management"]["lines"], rec["pages"]["ownership"]["lines"])
                    break
                if attempt == 1:
                    browser.close(); browser = None
                    time.sleep(10)
            if not res:
                print("  FAIL no data", flush=True)
                results.append({"abbrevSW": abbrev, "error": "no data"})
                continue
            print("  score {} | {}".format(res["score"], res["parts"]), flush=True)
            if not dry:
                body = post(webhook, res, sheets)
                res["webhook"] = body
                print("  webhook: {}".format(json.dumps(body)[:300]), flush=True)
            results.append(res)
            with open(os.path.join(out_dir, "sw_skin_results.json"), "w", encoding="utf-8") as fh:
                json.dump(results, fh, ensure_ascii=False, indent=1)
    finally:
        if browser is not None:
            browser.close()
    ok = [r for r in results if "score" in r]
    summary = "## SW skin {}: {} of {} scored\n\n{}\n".format(VERSION, len(ok), len(results),
              "\n".join("- {}: {}".format(r["abbrevSW"], r.get("score", r.get("error"))) for r in results))
    print(summary)
    sf = os.environ.get("GITHUB_STEP_SUMMARY")
    if sf:
        open(sf, "a", encoding="utf-8").write(summary)


if __name__ == "__main__":
    main()
