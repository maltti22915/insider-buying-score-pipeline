insider_score_scraper.py  v9 -> v10  (4 edits, nothing else changes)
=====================================================================

Why: v88 of fn_22_30 established that .intrinsic-value-history__verdict is a
DIFFERENT widget (Intrinsic Value History) from the one "AS vs usual" needs
(Valuation History headline). So the v9 verdict fallback can never produce a
valid value (the Alibaba run showed exactly that: VALUE_NULL). v10 waits for
the headline only, and also scrolls the lazy Livewire block into view, which
is the leading (UNCONFIRMED) explanation for why it never loads.


EDIT 1 -- imports (top of file)
-------------------------------
Add `import time` next to the other imports:

    import json
    import os
    import re
    import time

    import requests
    from seleniumbase import SB


EDIT 2 -- configuration (replace the "VERSION 9 ADDITION" block)
----------------------------------------------------------------
Replace these lines:

    ALPHASPREAD_PRIMARY_SELECTOR = ALPHASPREAD_HEADLINE_SELECTORS[0]
    ALPHASPREAD_FALLBACK_SELECTOR = ALPHASPREAD_HEADLINE_SELECTORS[1]
    ALPHASPREAD_ACCEPT_VERDICT_FALLBACK = True
    ALPHASPREAD_FALLBACK_AFTER_SECONDS = 25

with:

    ALPHASPREAD_PRIMARY_SELECTOR = ALPHASPREAD_HEADLINE_SELECTORS[0]
    ALPHASPREAD_FALLBACK_SELECTOR = ALPHASPREAD_HEADLINE_SELECTORS[1]
    # VERSION 10: the verdict element is the Intrinsic Value History widget,
    # NOT the Valuation History headline "AS vs usual" needs (fn_22_30 v88).
    # Kept False and no longer used by the wait; only the diagnostics
    # still look at it.
    ALPHASPREAD_ACCEPT_VERDICT_FALLBACK = False
    ALPHASPREAD_FALLBACK_AFTER_SECONDS = 25   # unused as of v10

    # VERSION 10: the block is a lazy Livewire component; scroll it (or the
    # page) toward the viewport this often while waiting.
    ALPHASPREAD_BLOCK_SELECTOR = "[class*='valuation-history-context']"
    ALPHASPREAD_SCROLL_EVERY_SECONDS = 2


EDIT 3 -- replace the WHOLE function wait_for_alphaspread_block
---------------------------------------------------------------
(keep the existing scroll-free scrape_alphaspread_html; it already calls
wait_for_alphaspread_block(sb) and its log line stays correct with the flag
False)

def scroll_alphaspread_block_into_view(sb):
    """
    VERSION 10 ADDITION: nudges the lazy-loaded valuation-history block
    into the viewport. If the block's own element exists (placeholder or
    real), it is scrolled to the centre of the screen; otherwise the page
    is scrolled down by most of a screen. Returns 'block', 'page' or None.
    Fully guarded.
    """
    try:
        return run_js(
            sb,
            "var el = document.querySelector("
            + json.dumps(ALPHASPREAD_BLOCK_SELECTOR)
            + "); if (el) { el.scrollIntoView({block: 'center'});"
            " return 'block'; }"
            " window.scrollBy(0, Math.max(400,"
            " Math.floor(window.innerHeight * 0.8)));"
            " return 'page';",
        )
    except Exception:
        return None


def alphaspread_headline_has_text(sb):
    """VERSION 10 ADDITION: True when the real headline exists AND has text."""
    try:
        if not sb.is_element_present(ALPHASPREAD_PRIMARY_SELECTOR):
            return False

        text = run_js(
            sb,
            "var el = document.querySelector("
            + json.dumps(ALPHASPREAD_PRIMARY_SELECTOR)
            + "); if (!el) { return ''; }"
            " return (el.innerText || el.textContent || '');",
        )
        return isinstance(text, str) and bool(text.strip())
    except Exception:
        return False


def wait_for_alphaspread_block(sb):
    """
    VERSION 10 REWRITE: waits ONLY for .valuation-history-context__headline
    with real text, for up to ALPHASPREAD_WAIT_TIMEOUT_SECONDS. The verdict
    element is never accepted (wrong widget, see fn_22_30 v88).

    While waiting it scrolls the lazy Livewire block into view every
    ALPHASPREAD_SCROLL_EVERY_SECONDS seconds. The log says how long the
    headline took and how many scrolls had happened, which is the evidence
    needed to confirm or reject the "block only loads in the viewport"
    explanation: a headline that appears right after the first scroll
    confirms it; one that never appears despite scrolling rejects it.

    Raises if the headline does not appear in time (the caller already
    catches this and saves diagnostics).
    """
    started = time.monotonic()
    deadline = started + ALPHASPREAD_WAIT_TIMEOUT_SECONDS
    last_scroll_at = None
    scroll_count = 0
    last_scroll_result = None

    while time.monotonic() < deadline:
        if alphaspread_headline_has_text(sb):
            print(
                "✅ Headline appeared after {:.1f}s | scrolls so far: {}"
                " (last scroll target: {})".format(
                    time.monotonic() - started,
                    scroll_count,
                    last_scroll_result,
                )
            )
            return

        now = time.monotonic()
        if (
            last_scroll_at is None
            or now - last_scroll_at >= ALPHASPREAD_SCROLL_EVERY_SECONDS
        ):
            last_scroll_result = scroll_alphaspread_block_into_view(sb)
            last_scroll_at = now
            scroll_count += 1

        sb.sleep(1)

    raise Exception(
        "{} (with text) did not appear within {} seconds | scrolls: {}"
        " (last scroll target: {})".format(
            ALPHASPREAD_PRIMARY_SELECTOR,
            ALPHASPREAD_WAIT_TIMEOUT_SECONDS,
            scroll_count,
            last_scroll_result,
        )
    )


EDIT 4 -- changelog (add at the top of the PURPOSE docstring, above VERSION 9)
-----------------------------------------------------------------------------
VERSION 10 (REQUESTED DIRECTLY, REAL CONFIRMED MISTAKE): removed the v9
verdict fallback. A real Alibaba run (Row 22, nyse/baba) waited 25s, then
accepted .intrinsic-value-history__verdict ("Its valuation is in line with
its history"), and the webhook correctly answered VALUE_NULL: that element
belongs to the Intrinsic Value History widget, not the Valuation History
headline "AS vs usual" is meant to capture (see fn_22_30 v88). The wait now
accepts ONLY .valuation-history-context__headline with non-empty text, for
the full ALPHASPREAD_WAIT_TIMEOUT_SECONDS, and scrolls the lazy Livewire
block into view every ALPHASPREAD_SCROLL_EVERY_SECONDS seconds while
waiting (UNCONFIRMED hypothesis: the block loads on viewport entry). The
log reports how long the headline took and how many scrolls had happened.
No .yml change needed.


HOW TO READ THE NEXT RUN
------------------------
- "Headline appeared after Xs | scrolls so far: 1"  -> scrolling was the
  trigger. Then add the same scroll to the Scrape.do path (fn_22_01 playWithBrowser)
  or simply rely on this scraper.
- Headline appears after many scrolls / at a similar time as before -> scroll
  was not the cause; the block's load is just slow or fails for that stock.
- Timeout with scrolls: 30 and the block selector found ('block') -> the
  block exists but its lazy request never completes; the saved screenshot
  and HTML in diagnostics/ should show whether it is still the loading
  placeholder.
- "looks like interstitial/blocked: True" in the diagnostics is a false
  positive on these pages (it matches the words "consent" and
  "challenge-platform", which normal AlphaSpread pages contain). Optional
  cleanup: drop those two markers from save_alphaspread_diagnostics.
