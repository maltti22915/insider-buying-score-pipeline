import as_moat as m
def page(company, rating, reason, tags, details=""):
    return ("<div>Cancel %s %s Economic Moat No Moat Narrow Wide What is Economic Moat? %s %s %s Competitive Advantages %s "
            "View Wide Economic Moat Stocks Wide Economic Moat Companies NVIDIA Wide Apple Wide</div>" % (company, rating, reason, tags, company, details))
r = m.parse_moat(page("Meta Inc", "Wide", "Meta possesses a wide economic moat due to network effects. It stays.", "Network Effects Intangible Assets", "Network Effects Meta benefits. Intangible Assets brand."))
assert r["rating"] == "wide" and r["score"] == 100 and r["advantages"] == ["Network Effects", "Intangible Assets"], r
z = m.parse_moat(page("Alibaba Ltd", "None", "Alibaba lacks an economic moat, leaving it vulnerable.", ""))
assert z["rating"] == "none" and z["score"] == 15 and z["advantages"] == [], z   # list of wide-moat stocks after the page must not count
a = m.parse_moat(page("Amazon", "Wide", "Amazon has a wide moat. Strong.", "Network Effects Low-Cost Production", "Network Effects x Low-Cost Production y"))
assert a["advantages"] == ["Network Effects", "Cost Advantage"], a
n = m.parse_moat(page("UNH", "Narrow", "UNH has a narrow moat, driven by high switching costs and efficient scale.", "High Switching Costs Efficient Scale"))
assert n["rating"] == "narrow" and n["advantages"] == ["Switching Costs", "Efficient Scale"], n
assert m.parse_moat("<p>nothing</p>")["rating"] is None
print("all moat tests passed")
