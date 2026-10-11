"""
as_moat.py v1.1 -- reads AlphaSpread's "Economic Moat" page (.../security/<exchange>/<ticker>/qualitative/block/economic-moat).
Pure function, no browser. Visible text of the page (checked on 15 real pages):
  "<Company> <Wide|Narrow|None> Economic Moat No Moat Narrow Wide What is Economic Moat? <reason> <tag> <tag> <Company> Competitive Advantages
   <tag> <explanation> <tag> <explanation> ... View Wide Economic Moat Stocks <list of other companies - ignored>"
parse_moat(html) -> {"rating": "wide|narrow|none|None", "score": 100|60|15|None, "advantages": [...], "reason": str, "warnings": [...]}
Tags seen: Network Effects, Intangible Assets, (High) Switching Costs, Efficient Scale, Low-Cost Production (= Cost Advantage).
AlphaSpread's moat text looks generated, so it is one input next to the financial numbers, never a substitute for them.
"""
import re

TAGS = [("Network Effects", "Network Effects"), ("Intangible Assets", "Intangible Assets"), ("Switching Costs", "Switching Costs"),
        ("Efficient Scale", "Efficient Scale"), ("Low-Cost Production", "Cost Advantage"), ("Cost Advantage", "Cost Advantage")]
SCORES = {"wide": 100.0, "narrow": 60.0, "none": 15.0}


def _text(html):
    h = re.sub(r"(?is)<(script|style|noscript)\b.*?</\1>", " ", html or "")
    h = re.sub(r"<[^>]+>", " ", h)
    h = re.sub(r"&nbsp;", " ", h).replace("&amp;", "&")
    return re.sub(r"\s+", " ", h).strip()


def _tags(segment):
    found = []
    for raw, norm in TAGS:
        if re.search(re.escape(raw), segment) and norm not in found:   # case-sensitive: tags are Title Case, prose is lower case
            found.append(norm)
    return found


def parse_moat(html):
    t = _text(html)
    out = {"rating": None, "score": None, "advantages": [], "reason": "", "warnings": []}
    m = re.search(r"\b(Wide|Narrow|None|No)\s+Economic\s+Moat\s+No\s+Moat\s+Narrow\s+Wide\s+What is Economic Moat\?", t)
    if not m:
        out["warnings"].append("moat header not found")
        return out
    out["rating"] = {"wide": "wide", "narrow": "narrow", "none": "none", "no": "none"}[m.group(1).lower()]
    out["score"] = SCORES[out["rating"]]
    rest = t[m.end():]
    ca = re.search(r"Competitive Advantages", rest)
    head = rest[:ca.start()] if ca else rest[:800]
    body = rest[ca.end():] if ca else ""
    cut = re.search(r"View Wide Economic Moat Stocks", body)
    if cut:
        body = body[:cut.start()]
    last_dot = head.rfind(". ")
    out["reason"] = (head[:last_dot + 1] if last_dot >= 0 else head).strip()[:400]
    tag_zone = head[last_dot + 1:] if last_dot >= 0 else head
    out["advantages"] = _tags(tag_zone + " " + body)
    if not ca:
        out["warnings"].append("'Competitive Advantages' not found")
    if out["rating"] in ("wide", "narrow") and not out["advantages"]:
        out["warnings"].append("rated but no advantage tags found")
    return out
