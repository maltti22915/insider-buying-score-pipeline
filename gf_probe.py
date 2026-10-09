# gf_probe.py v1 -- tests which method gets a GuruFocus page past Cloudflare from a GitHub runner.
# Prints one line per method and a final PROBE_SUMMARY JSON line. Needs: pip install curl_cffi seleniumbase
import os, sys, json, time

TICKER = os.environ.get("ABBREV_GF", "NOW")
PROXY = os.environ.get("PROBE_PROXY", "").strip()          # e.g. socks5://127.0.0.1:40000 (WARP)
LABEL = os.environ.get("PROBE_LABEL", "direct")
URL = "https://www.gurufocus.com/term/pe/{}".format(TICKER)
results = {}


def verdict(title, text):
    t = (title or "").lower()
    if "just a moment" in t or "attention required" in t or "cloudflare" in t:
        return "BLOCKED"
    if len(text or "") > 5000 and ("pe ratio" in (text or "").lower() or "p/e" in (text or "").lower()):
        return "OK"
    return "UNCLEAR"


def title_of(html):
    a = html.lower().find("<title>")
    b = html.lower().find("</title>")
    return html[a + 7:b] if a >= 0 and b > a else ""


# A: curl_cffi with a real Chrome TLS fingerprint
try:
    from curl_cffi import requests as cr
    proxies = {"https": PROXY, "http": PROXY} if PROXY else None
    for imp in ("chrome131", "chrome124", "safari17_0"):
        try:
            r = cr.get(URL, impersonate=imp, timeout=45, proxies=proxies)
            v = verdict(title_of(r.text), r.text)
            print("A curl_cffi[{}] http={} len={} -> {}".format(imp, r.status_code, len(r.text), v))
            results["curl_cffi_" + imp] = v
            if v == "OK":
                break
        except Exception as e:
            print("A curl_cffi[{}] error {}".format(imp, type(e).__name__))
            results["curl_cffi_" + imp] = "ERROR"
except Exception as e:
    print("A unavailable", e)

# B: SeleniumBase UC (run under xvfb-run), reconnect + captcha click
try:
    from seleniumbase import SB
    kw = dict(uc=True, headless=False, locale_code="en", test=True)
    if PROXY:
        kw["proxy"] = PROXY.replace("socks5://", "socks5://")
    with SB(**kw) as sb:
        sb.uc_open_with_reconnect(URL, 8)
        v = verdict(sb.get_title(), sb.get_page_source())
        print("B uc_open_with_reconnect -> {} title={!r}".format(v, sb.get_title()))
        results["uc_reconnect"] = v
        if v != "OK":
            for fn in ("uc_gui_click_captcha", "uc_gui_handle_captcha"):
                try:
                    getattr(sb, fn)()
                    sb.sleep(6)
                    v = verdict(sb.get_title(), sb.get_page_source())
                    print("B {} -> {} title={!r}".format(fn, v, sb.get_title()))
                    results["uc_" + fn] = v
                    if v == "OK":
                        break
                except Exception as e:
                    print("B {} error {}".format(fn, type(e).__name__))
except Exception as e:
    print("B error", type(e).__name__, str(e)[:200])
    results["uc_error"] = type(e).__name__

print("PROBE_SUMMARY " + json.dumps({"label": LABEL, "ticker": TICKER, "results": results}))
