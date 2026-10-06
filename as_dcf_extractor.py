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

VERSION: as_dcf_extractor v1
============================================================================
"""
import json
import re
import time
from datetime import datetime, timezone

VERSION = "as_dcf_extractor v1"
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


def _run_js(sb, expression):
    """Evaluate an IIFE expression; some uc sessions reject a leading 'return'."""
    try:
        return sb.execute_script("return " + expression)
    except Exception:
        return sb.execute_script(expression)


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


def scrape_as_dcf_data(sb, abbrev_as, page_timeout=45, step_timeout=25, poll_interval=0.5):
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

    # 1. the page's "View Calculation" button
    if not _wait_until(lambda: _click_by_text(sb, "view calculation"), page_timeout, poll_interval):
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
        raise AsDcfError("FULL_MODEL_TAB_NOT_FOUND")

    if state["login"]:
        raise AsDcfLoginRequired("a login form appeared instead of the DCF modal")

    _log("clicked 'Full Model'")

    # 3. wait for the table to be rendered, then read it
    if not _wait_until(lambda: bool(_run_js(sb, _PRESENT_JS)), step_timeout, poll_interval):
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
