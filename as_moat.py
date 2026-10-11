"""
as_moat.py v1.0 -- reads AlphaSpread's "Economic Moat" page (.../security/<exchange>/<ticker>/qualitative/block/economic-moat).
Pure function, no browser. The page shows a rating (No Moat / Narrow / Wide), a one-paragraph reason and the list of competitive advantages
(network effects, intangible assets, switching costs, cost advantage, efficient scale).
parse_moat(html) -> {"rating": "wide|narrow|none|None", "score": 100|60|15|None, "advantages": [...], "reason": str, "warnings": [...]}
AlphaSpread's moat text looks generated, so it is one input next to the financial numbers, never a substitute for them.
"""
import re

ADVANTAGES = ["Network Effects", "Intangible Assets", "Switching Costs", "Cost Advantage", "Efficient Scale"]
SCORES = {"wide": 100.0, "narrow": 60.0, "none": 15.0}


def _text(html):
    h = re.sub(r"(?is)<(script|style|noscript)\b.*?</\1>", " ", html or "")
    h = re.sub(r"<[^>]+>", " ", h)
    h = re.sub(r"&nbsp;", " ", h)
    return re.sub(r"\s+", " ", h).strip()


def parse_moat(html):
    t = _text(html)
    out = {"rating": None, "score": None, "advantages": [], "reason": "", "warnings": []}
    m = re.search(r"\b(Wide|Narrow|No)\s+(?:Economic\s+)?Moat\b(?!\s+(?:Narrow|Wide))", t, re.I)
    heads = [x for x in re.finditer(r"\b(Wide|Narrow|No)\s+Economic\s+Moat\b", t, re.I)]
    if heads:
        m = heads[0]
    if not m:
        out["warnings"].append("moat rating not found")
        return out
    word = m.group(1).lower()
    out["rating"] = {"wide": "wide", "narrow": "narrow", "no": "none"}[word]
    out["score"] = SCORES[out["rating"]]
    r = re.search(r"possesses (?:a )?(?:wide |narrow )?economic moat[^.]*\.(?:[^.]*\.){0,3}", t, re.I)
    if r:
        out["reason"] = r.group(0)[:400]
    section = t
    cut = re.search(r"COMPETITIVE ADVANTAGES", t)
    if cut:
        section = t[cut.start():]
    found = [a for a in ADVANTAGES if re.search(re.escape(a), section, re.I)]
    if not found:
        found = [a for a in ADVANTAGES if re.search(re.escape(a), t, re.I)]
    out["advantages"] = found
    if len(found) == len(ADVANTAGES):
        out["warnings"].append("all five advantages found: probably a legend, check the HTML")
    return out
