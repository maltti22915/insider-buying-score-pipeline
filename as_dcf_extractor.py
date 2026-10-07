"""
============================================================================
as_dcf_extractor.py
============================================================================

PURPOSE
----------------------------------------------------------------------------
Reads AlphaSpread's DCF model for one stock with a real browser and returns it
as a plain dict (ready to be sent as JSON to the Apps Script Web App, target
"ASDCF", where fn_91_03 validates it and fn_91_01 writes it into the "AS JSON"
cell). Written so the SAME function can be called from
provider_json_scraper.py now and, later, from insider_score_scraper.py.

WHAT IT DOES (READ-ONLY)
----------------------------------------------------------------------------
1. Opens https://www.alphaspread.com/security/<abbrevAS>/dcf-valuation
2. Clicks the button "View Calculation", then the tab "Full Model".
3. Reads the Full Model table (every year column, every row, grouped by the
   table's own sections), the modal header (DCF value, valuation gap,
   template) and the right-hand panel of the selected row (growth assumption,
   historical, Wall Street, AlphaSpread bear/base/bull).

SAFETY: the ONLY elements this module ever clicks are "View Calculation" and
"Full Model" (see SAFE_CLICK_LABELS; _click_by_text refuses any other label).
It never clicks Save, Reset, Duplicate, Delete, the +/- buttons, a table cell
or a row. The modal is an editor of saved valuations that needs a login to
save; if a login form appears the run is reported as AsDcfLoginRequired.

BASED ON REAL DATA: the table selectors come from a real saved copy of the
MSCI Full Model (template "via FCFF"): table.dcf-model-table, period headers
th.dcf-model-table__period-header (year + Actual/Forecast), section rows
tr.dcf-model-table__section-row, data rows tr.dcf-model-table__data-row whose
cells carry data-row-key / data-period-key. Row sets differ by template (FCFF:
Revenue, Operating Margin, Operating Income, Taxes, NOPAT, Net CapEx, Free
Cash Flow to Firm, then Valuation rows; Net Income template: Revenue, Net
Margin, Net Income, then Valuation rows), so rows are read generically, never
from a fixed list.

NOT VERIFIED LIVE (only checked against saved HTML and a fake browser):
the page URL, the "View Calculation" and "Full Model" clicks, what a
logged-out browser is allowed to open ("Free Plan: 3 / 3" is shown in the page
header and its meaning is unknown), and innerText of the side panel in a real
browser. Values are the page's own rounded display text ("1.2B", "42.4%").

USAGE
----------------------------------------------------------------------------
    import as_dcf_extractor
    data = as_dcf_extractor.scrape_as_dcf_data(sb, "nasdaq/adsk")
    # then post {"target": "ASDCF", "sheetName": ..., "rowNumber": ...,
    #            "abbrevAS": "nasdaq/adsk", "data": data}

Errors: AsDcfError (generic), AsDcfLoginRequired (a login form appeared).

VERSION: as_dcf_extractor v3
v3 -- Requested directly. REAL CONFIRMED BUG in v1 and v2 (found by reading the
      saved page of a real run, Row 34, nyse/baba, headed browser): every
      browser-side script was sent as the text  "return " + <script>  and each
      script string began with a line break, so the browser saw
          return
          (function () { ... })()
      JavaScript ends a statement at "return" + line break (automatic
      semicolon insertion): it returned nothing and NEVER RAN the function.
      In the headed (classic function-body) mode that raised no error, so the
      old fallback never fired, the click script never ran, and the result
      (None) was read as "button not found" for the whole 45 s wait, although
      the saved page shows the "View Calculation" button present and visible
      in ordinary containers. The same flaw silently disabled the table wait,
      the login check, the extraction, and v2's scroll and probe. In headless
      uc (bare-expression) mode the leading "return" is a SyntaxError, which
      DID trigger the fallback, so that mode worked -- the bug depended on the
      browser mode. The tests used a fake browser that never ran real
      JavaScript, so none of this was visible.
      Fix: _run_js() strips the script, wraps it in JSON.stringify(...), and
      tries BOTH shapes -- "return <expr>;" (function-body mode) and the bare
      expression (CDP/uc mode) -- moving to the second when the first raises
      OR returns nothing. The results are decoded from JSON. The first working
      shape is logged once ("javascript evaluation mode: ...").
      New: _check_js_channel() runs a trivial script right after the page is
      opened and raises JAVASCRIPT_CHANNEL_NOT_WORKING at once when scripts do
      not run or return nothing, so a dead channel can never again look like a
      missing button. Nothing else changes: same clicks (only "View
      Calculation" and "Full Model"), same extraction, same errors.
      Tested with REAL JavaScript (jsdom) in both evaluation modes on the
      saved Row 34 page and on the real MSCI table fragment.
v2 -- Requested directly after the first real run stopped with
v2 -- Requested directly after the first real run stopped with
      VIEW_CALCULATION_NOT_FOUND (page loaded, logged out, no button found):
      * While waiting for "View Calculation" the page is now scrolled a step on
        every poll (wrapping back to the top at the bottom), so lazily rendered
        blocks get a chance to appear.
      * probe_page() prints what is actually on the page straight into the log:
        every button/link/tab whose text, aria-label, title or href mentions
        "calculation", "model" or "dcf" (tag, text, visible?, class, position),
        other elements whose short text mentions "calculation", the visible
        button texts, the headings, any dialog/cookie/consent overlay, whether a
        login form is showing, and how many lazy (Livewire) blocks are still
        unloaded. It runs once after PROBE_AFTER_SECONDS of waiting, and again
        right before every failure (VIEW_CALCULATION_NOT_FOUND,
        FULL_MODEL_TAB_NOT_FOUND, TABLE_NOT_RENDERED). It never clicks anything
        and never raises: a failing probe is logged and the real error still
        propagates. Read-only guarantee (SAFE_CLICK_LABELS) unchanged.
v1 -- first version.
============================================================================
"""
import json
import re
import time
from datetime import datetime, timezone

VERSION = "as_dcf_extractor v3"
PROBE_AFTER_SECONDS = 15
MAX_PROBE_MATCHES = 40
DCF_URL_TEMPLATE = "https://www.alphaspread.com/security/{abbrev}/dcf-valuation"
SAFE_CLICK_LABELS = ("view calculation", "full model")


class AsDcfError(Exception):
    pass


class AsDcfLoginRequired(AsDcfError):
    pass


def _log(message):
    print("[{}] {}".format(VERSION, message), flush=True)


# --------------------------------------------------------------------------
# Browser-side scripts. Each is an IIFE returning a primitive or a JSON string.
# --------------------------------------------------------------------------
EXTRACT_JS = r"""
(function () { /*EXTRACT*/
  var norm = function (s) { return String(s == null ? '' : s).replace(/\s+/g, ' ').trim(); };
  var text = function (el) {
    if (!el) { return ''; }
    return norm(el.innerText !== undefined ? el.innerText : el.textContent);
  };
  var table = document.querySelector('table.dcf-model-table');
  if (!table) { return JSON.stringify({ error: 'NO_TABLE' }); }
  var cellsOf = function (tr) {
    return Array.prototype.filter.call(tr.children, function (c) {
      return c.tagName === 'TD' || c.tagName === 'TH';
    });
  };

  var periods = [];
  var headRow = table.querySelector('thead tr');
  if (headRow) {
    cellsOf(headRow).forEach(function (th) {
      if (!th.classList.contains('dcf-model-table__period-header')) { return; }
      var span = th.querySelector('span');
      var small = th.querySelector('small');
      var label = norm(span ? text(span) : text(th));
      periods.push({
        key: '',
        label: label,
        year: parseInt(label, 10) || null,
        kind: norm(small ? text(small) : (th.classList.contains('is-forecast') ? 'Forecast' : 'Actual'))
      });
    });
  }

  var sections = [];
  var current = null;
  var selectedRowKey = '';
  var shapeProblems = 0;

  Array.prototype.forEach.call(table.querySelectorAll('tbody tr'), function (tr) {
    if (tr.classList.contains('dcf-model-table__section-row')) {
      current = { name: text(tr), rows: [] };
      sections.push(current);
      return;
    }
    if (!tr.classList.contains('dcf-model-table__data-row')) { return; }
    var cells = cellsOf(tr);
    if (cells.length < 2) { return; }

    var labelCell = cells[0];
    var strong = labelCell.querySelector('strong');
    var small = labelCell.querySelector('small');
    var summaryEl = labelCell.querySelector('.dcf-model-table__row-summary-value');
    var values = [];
    var rowKey = '';

    for (var i = 1; i < cells.length; i++) {
      var raw = text(cells[i]);
      values.push(raw === '' || raw === '-' ? null : raw);
      if (!rowKey) { rowKey = cells[i].getAttribute('data-row-key') || ''; }
      var pk = cells[i].getAttribute('data-period-key') || '';
      if (pk && periods[i - 1] && !periods[i - 1].key) { periods[i - 1].key = pk; }
    }
    if (values.length !== periods.length) { shapeProblems += 1; }

    var selected = tr.classList.contains('is-selected');
    if (selected && !selectedRowKey) { selectedRowKey = rowKey; }
    if (!current) { current = { name: '', rows: [] }; sections.push(current); }

    current.rows.push({
      key: rowKey,
      label: text(strong),
      description: text(small),
      summary: text(summaryEl) || null,
      selected: selected,
      values: values
    });
  });

  // ---- side panel (inspector) of the selected row ----
  var aside = document.querySelector('aside.dcf-model-table-inspector');
  var lines = [];
  if (aside) {
    var rawText = aside.innerText !== undefined ? aside.innerText : aside.textContent;
    lines = String(rawText || '').split('\n').map(norm).filter(function (l) { return l; });
  }
  var lower = lines.map(function (l) { return l.toLowerCase(); });
  var after = function (heading) {
    var at = lower.indexOf(heading);
    return at >= 0 && at + 1 < lines.length ? lines[at + 1] : null;
  };
  var HEADINGS = ['historical', 'wall street', 'alpha spread'];
  var group = function (heading, labels) {
    var start = lower.indexOf(heading);
    if (start < 0) { return null; }
    var out = {};
    var found = 0;
    var pos = start + 1;
    while (pos < lines.length && HEADINGS.indexOf(lower[pos]) < 0) {
      var at = labels.indexOf(lower[pos]);
      if (at >= 0 && pos + 1 < lines.length) {
        out[labels[at]] = lines[pos + 1];
        found += 1;
        pos += 2;
      } else {
        pos += 1;
      }
    }
    return found ? out : null;
  };
  var inspector = {
    selectedRow: after('selected row'),
    forecastGrowth: after('forecast growth assumption'),
    historical: group('historical', ['3y', '5y']),
    wallStreet: group('wall street', ['low', 'avg', 'high']),
    alphaSpread: group('alpha spread', ['bear', 'base', 'bull']),
    lines: lines.slice(0, 80)
  };

  // ---- modal header ----
  var body = document.body ? text(document.body) : '';
  var mValue = body.match(/DCF VALUE ([0-9][0-9.,]*) ([A-Za-z]{3})/i);
  var mGap = body.match(/(UNDER|OVER)VALUATION ([0-9]+) ?%/i);
  var mTemplate = body.match(/Template via ([A-Za-z][A-Za-z0-9 ]*?) Business Forecast/i);
  var header = {
    dcfValue: mValue ? mValue[1] : null,
    currency: mValue ? mValue[2].toUpperCase() : null,
    gap: mGap ? mGap[1].toLowerCase() + 'valued' : null,
    gapPercent: mGap ? parseInt(mGap[2], 10) : null,
    template: mTemplate ? norm(mTemplate[1]) : null
  };

  return JSON.stringify({
    header: header,
    periods: periods,
    sections: sections,
    selectedRowKey: selectedRowKey,
    inspector: inspector,
    shapeProblems: shapeProblems
  });
})()
"""

_CLICK_JS = r"""
(function () { /*CLICK*/
  var want = __LABEL__;
  var norm = function (s) { return String(s == null ? '' : s).replace(/\s+/g, ' ').trim().toLowerCase(); };
  var visible = function (el) {
    var r = el.getClientRects();
    return !!(r && r.length) && window.getComputedStyle(el).visibility !== 'hidden';
  };
  var tiers = ['button, a, [role="button"], [role="tab"]', 'div, span, li'];
  for (var t = 0; t < tiers.length; t++) {
    var nodes = document.querySelectorAll(tiers[t]);
    var best = null;
    for (var i = 0; i < nodes.length; i++) {
      var el = nodes[i];
      var txt = norm(el.innerText !== undefined ? el.innerText : el.textContent);
      var match = (t === 0) ? (txt === want || txt.indexOf(want + ' ') === 0) : (txt === want);
      if (match && visible(el)) { best = el; if (t === 0) { break; } }
    }
    if (best) { best.click(); return true; }
  }
  return false;
})()
"""

_PRESENT_JS = r"""
(function () { /*POLL:TABLE*/
  var rows = document.querySelectorAll('table.dcf-model-table tbody tr.dcf-model-table__data-row');
  var heads = document.querySelectorAll('table.dcf-model-table th.dcf-model-table__period-header');
  return rows.length > 0 && heads.length > 0;
})()
"""

_LOGIN_JS = r"""
(function () { /*LOGIN*/
  var inputs = document.querySelectorAll('input[type="password"]');
  for (var i = 0; i < inputs.length; i++) {
    var r = inputs[i].getClientRects();
    if (r && r.length) { return true; }
  }
  return false;
})()
"""


_SCROLL_JS = r"""
(function () { /*SCROLL*/
  var height = document.documentElement.scrollHeight || 0;
  var viewport = window.innerHeight || 800;
  var next = (window.scrollY || 0) + 600;
  if (next + viewport >= height - 10) { next = 0; }
  window.scrollTo(0, next);
  return [Math.round(next), height];
})()
"""

PROBE_JS = r"""
(function () { /*PROBE*/
  var norm = function (s) { return String(s == null ? '' : s).replace(/\s+/g, ' ').trim(); };
  var text = function (el) { return norm(el.innerText !== undefined ? el.innerText : el.textContent); };
  var attr = function (el, name) { return norm(el.getAttribute(name) || ''); };
  var visible = function (el) {
    var r = el.getClientRects();
    return !!(r && r.length) && window.getComputedStyle(el).visibility !== 'hidden';
  };
  var top = function (el) {
    try { return Math.round(el.getBoundingClientRect().top + (window.scrollY || 0)); } catch (e) { return null; }
  };
  var pattern = /calculation|model|dcf/i;
  var scrollY = window.scrollY || 0;

  var counts = { buttons: 0, links: 0, visibleInteractive: 0 };
  var matches = [];
  var visibleTexts = [];
  var seen = {};
  var nodes = document.querySelectorAll('button, a, [role="button"], [role="tab"], summary, input[type="button"], input[type="submit"]');

  for (var i = 0; i < nodes.length; i++) {
    var el = nodes[i];
    var tag = el.tagName.toLowerCase();
    if (tag === 'a') { counts.links += 1; } else { counts.buttons += 1; }

    var label = text(el).slice(0, 80) || attr(el, 'value');
    var aria = attr(el, 'aria-label');
    var title = attr(el, 'title');
    var href = tag === 'a' ? attr(el, 'href').slice(0, 100) : '';
    var isVisible = visible(el);

    if (isVisible) {
      counts.visibleInteractive += 1;
      var shortLabel = label.slice(0, 40);
      if (shortLabel && !seen[shortLabel] && visibleTexts.length < 50) {
        seen[shortLabel] = true;
        visibleTexts.push(shortLabel);
      }
    }

    if (matches.length < 40 && (pattern.test(label) || pattern.test(aria) || pattern.test(title) || pattern.test(href))) {
      matches.push({
        tag: tag, text: label, aria: aria, title: title, href: href,
        id: el.id || '', cls: attr(el, 'class').slice(0, 80),
        visible: isVisible, disabled: !!el.disabled, top: top(el)
      });
    }
  }

  var others = [];
  var generic = document.querySelectorAll('div, span, li, p, strong, h1, h2, h3, h4');
  for (var j = 0; j < generic.length && others.length < 15; j++) {
    var g = generic[j];
    var gt = text(g);
    if (gt && gt.length <= 60 && /calculation/i.test(gt)) {
      others.push({ tag: g.tagName.toLowerCase(), text: gt, cls: attr(g, 'class').slice(0, 60), visible: visible(g) });
    }
  }

  var headings = [];
  var hs = document.querySelectorAll('h1, h2, h3');
  for (var k = 0; k < hs.length && headings.length < 12; k++) {
    var ht = text(hs[k]).slice(0, 60);
    if (ht) { headings.push(ht); }
  }

  var lazyPending = 0;
  var wire = document.querySelectorAll('[wire\\:snapshot]');
  for (var w = 0; w < wire.length && w < 300; w++) {
    var snap = wire[w].getAttribute('wire:snapshot') || '';
    if (snap.indexOf('"lazyLoaded":false') >= 0) { lazyPending += 1; }
  }

  var overlays = [];
  var ov = document.querySelectorAll('[role="dialog"], .modal, [class*="cookie"], [class*="consent"]');
  for (var o = 0; o < ov.length && overlays.length < 5; o++) {
    if (visible(ov[o])) { overlays.push({ cls: attr(ov[o], 'class').slice(0, 60), text: text(ov[o]).slice(0, 80) }); }
  }

  var loginForm = false;
  var pw = document.querySelectorAll('input[type="password"]');
  for (var p = 0; p < pw.length; p++) { if (visible(pw[p])) { loginForm = true; } }

  return JSON.stringify({
    url: location.href, title: document.title, readyState: document.readyState,
    scrollY: Math.round(scrollY), scrollHeight: document.documentElement.scrollHeight || 0,
    viewport: window.innerHeight || 0,
    wireComponents: document.querySelectorAll('[wire\\:id]').length, lazyPending: lazyPending,
    counts: counts, matches: matches, others: others, visibleTexts: visibleTexts,
    headings: headings, overlays: overlays, loginForm: loginForm
  });
})()
"""


_JS_MODE_LOGGED = {"done": False}


def _run_js(sb, script):
    """
    Runs one browser-side script (an IIFE) and returns its JSON-decoded result.

    sb.execute_script treats its string in one of two ways, depending on the
    browser session: as a FUNCTION BODY (classic Selenium: a result needs a
    "return") or as a bare EXPRESSION (uc/CDP: a leading "return" is a
    SyntaxError). Both shapes are tried, in that order, moving on when the
    first raises OR returns nothing.

    The script is stripped first: the stored scripts begin with a line break,
    and "return" followed by a line break returns nothing in JavaScript
    (automatic semicolon insertion) without ever running the code after it.
    That was the v1/v2 bug. The result is JSON.stringify'd inside the page, so
    any value survives either mode; None means no value came back at all.
    """
    wrapped = "JSON.stringify(" + str(script).strip() + ")"

    last_error = None

    for shape, candidate in (
        ("function-body", "return " + wrapped + ";"),
        ("expression", wrapped),
    ):
        try:
            raw = sb.execute_script(candidate)
        except Exception as error:
            last_error = error
            continue

        if raw is None:
            continue

        if not _JS_MODE_LOGGED["done"]:
            _JS_MODE_LOGGED["done"] = True
            _log("javascript evaluation mode: {}".format(shape))

        if isinstance(raw, str):
            try:
                return json.loads(raw)
            except ValueError:
                return raw

        return raw

    if last_error is not None:
        raise last_error

    return None


def _check_js_channel(sb, timeout=6, interval=0.5):
    """
    Proves that browser scripts really run and return a value. Without it a
    dead channel is indistinguishable from a missing button (v1/v2 waited 45 s
    and reported VIEW_CALCULATION_NOT_FOUND). Raises AsDcfError
    JAVASCRIPT_CHANNEL_NOT_WORKING when no script result ever comes back.
    """
    problem = {"text": "no result"}

    def attempt():
        try:
            value = _run_js(sb, "(function () { return 20 + 22; })()")
        except Exception as error:
            problem["text"] = "error: {}".format(error)
            return False

        if value == 42:
            return True

        problem["text"] = "got {!r} instead of 42".format(value)
        return False

    if not _wait_until(attempt, timeout, interval):
        raise AsDcfError("JAVASCRIPT_CHANNEL_NOT_WORKING: {}".format(problem["text"]))

    _log("javascript channel check: ok")


def _click_by_text(sb, label):
    """Click one visible control by its text. ONLY the whitelisted labels."""
    wanted = str(label).strip().lower()

    if wanted not in SAFE_CLICK_LABELS:
        raise ValueError("refusing to click non-whitelisted label: {!r}".format(label))

    script = _CLICK_JS.replace("__LABEL__", json.dumps(wanted))
    return bool(_run_js(sb, script))


def _wait_until(check, timeout, interval):
    deadline = time.monotonic() + timeout

    while True:
        if check():
            return True

        if time.monotonic() >= deadline:
            return False

        time.sleep(interval)


def _scroll_step(sb):
    """Scrolls the page one step (wraps to the top at the bottom). Never raises."""
    try:
        _run_js(sb, _SCROLL_JS)
    except Exception:
        pass


def probe_page(sb, reason):
    """
    Prints what is on the page into the log (read-only, never clicks, never
    raises). See the v2 note in the module docstring for what it reports.
    """
    try:
        raw = _run_js(sb, PROBE_JS)
        info = json.loads(raw) if isinstance(raw, str) else raw

        if not isinstance(info, dict):
            _log("🔍 PROBE ({}): the page returned nothing readable".format(reason))
            return

        counts = info.get("counts") or {}
        _log(
            "🔍 PROBE ({}) | url={} | title={!r} | readyState={} | scrollY={} of {} (viewport {})"
            " | buttons={} links={} visible controls={} | wire components={} | lazy blocks still loading={}"
            " | login form showing={}".format(
                reason, info.get("url"), (info.get("title") or "")[:80], info.get("readyState"),
                info.get("scrollY"), info.get("scrollHeight"), info.get("viewport"),
                counts.get("buttons"), counts.get("links"), counts.get("visibleInteractive"),
                info.get("wireComponents"), info.get("lazyPending"), info.get("loginForm"),
            )
        )

        _log("🔍 PROBE headings: {}".format(json.dumps(info.get("headings") or [], ensure_ascii=False)[:500]))

        matches = (info.get("matches") or [])[:MAX_PROBE_MATCHES]
        _log("🔍 PROBE controls mentioning calculation/model/dcf: {}".format(len(matches)))

        for number, item in enumerate(matches, 1):
            _log(
                "🔍   {}. <{}> {!r} | visible={} | disabled={} | aria-label={!r} | title={!r}"
                " | href={!r} | id={!r} | class={!r} | top={}".format(
                    number, item.get("tag"), (item.get("text") or "")[:80], item.get("visible"),
                    item.get("disabled"), (item.get("aria") or "")[:60], (item.get("title") or "")[:60],
                    item.get("href") or "", item.get("id") or "", item.get("cls") or "", item.get("top"),
                )
            )

        for number, item in enumerate((info.get("others") or [])[:15], 1):
            _log(
                "🔍   other element {}. <{}> {!r} | visible={} | class={!r}".format(
                    number, item.get("tag"), (item.get("text") or "")[:60], item.get("visible"), item.get("cls") or "",
                )
            )

        _log("🔍 PROBE visible button/link texts: {}".format(
            json.dumps(info.get("visibleTexts") or [], ensure_ascii=False)[:900]))

        overlays = info.get("overlays") or []

        if overlays:
            _log("🔍 PROBE overlays/dialogs showing: {}".format(json.dumps(overlays, ensure_ascii=False)[:500]))

    except Exception as probe_error:
        _log("⚠️ probe failed (the real error is unaffected): {}".format(probe_error))


def scrape_as_dcf_data(sb, abbrev_as, page_timeout=45, step_timeout=25, poll_interval=0.5, probe_after=PROBE_AFTER_SECONDS):
    """Open the DCF page, open View Calculation -> Full Model, return the data dict."""
    abbrev = str(abbrev_as or "").strip().strip("/")

    if not abbrev:
        raise AsDcfError("EMPTY_ABBREV_AS")

    url = DCF_URL_TEMPLATE.format(abbrev=abbrev)
    _log("opening {}".format(url))

    try:
        sb.uc_open_with_reconnect(url, 6)
    except AttributeError:
        sb.open(url)

    # 0. (v3) make sure browser scripts really run before waiting for anything
    _check_js_channel(sb)

    # 1. the page's "View Calculation" button (scrolling while waiting, v2)
    wait_state = {"started": time.monotonic(), "probed": False}

    def click_view_calculation():
        if _click_by_text(sb, "view calculation"):
            return True

        _scroll_step(sb)

        if (not wait_state["probed"]) and time.monotonic() - wait_state["started"] >= probe_after:
            wait_state["probed"] = True
            probe_page(sb, "still no 'View Calculation' after {}s of waiting and scrolling".format(probe_after))

        return False

    if not _wait_until(click_view_calculation, page_timeout, poll_interval):
        probe_page(sb, "VIEW_CALCULATION_NOT_FOUND")
        raise AsDcfError("VIEW_CALCULATION_NOT_FOUND")

    _log("clicked 'View Calculation'")

    # 2. the modal's "Full Model" tab (or a login form instead)
    state = {"login": False}

    def click_full_model():
        if _run_js(sb, _LOGIN_JS):
            state["login"] = True
            return True
        return _click_by_text(sb, "full model")

    if not _wait_until(click_full_model, step_timeout, poll_interval):
        probe_page(sb, "FULL_MODEL_TAB_NOT_FOUND")
        raise AsDcfError("FULL_MODEL_TAB_NOT_FOUND")

    if state["login"]:
        raise AsDcfLoginRequired("a login form appeared instead of the DCF modal")

    _log("clicked 'Full Model'")

    # 3. wait for the table to be rendered, then read it
    if not _wait_until(lambda: bool(_run_js(sb, _PRESENT_JS)), step_timeout, poll_interval):
        probe_page(sb, "TABLE_NOT_RENDERED")
        raise AsDcfError("TABLE_NOT_RENDERED")

    raw = _run_js(sb, EXTRACT_JS)

    try:
        extracted = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError:
        raise AsDcfError("EXTRACT_NOT_JSON")

    if not isinstance(extracted, dict) or extracted.get("error"):
        raise AsDcfError("EXTRACT_FAILED: {}".format(extracted.get("error") if isinstance(extracted, dict) else raw))

    periods = extracted.get("periods") or []
    sections = extracted.get("sections") or []
    row_count = sum(len(s.get("rows") or []) for s in sections)

    if len(periods) < 5 or row_count < 3:
        raise AsDcfError("TABLE_TOO_SMALL: periods={} rows={}".format(len(periods), row_count))

    if extracted.get("shapeProblems"):
        _log("WARNING: {} row(s) have a different number of cells than periods".format(extracted["shapeProblems"]))

    data = {
        "source": "alphaspread",
        "page": "dcf-valuation",
        "url": url,
        "abbrevAS": abbrev,
        "scrapedAtUtc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "header": extracted.get("header") or {},
        "periods": periods,
        "sections": sections,
        "selectedRowKey": extracted.get("selectedRowKey") or "",
        "inspector": extracted.get("inspector") or {},
    }

    _log("read {} periods, {} sections, {} rows, template={}".format(
        len(periods), len(sections), row_count, (data["header"] or {}).get("template")))

    return data
