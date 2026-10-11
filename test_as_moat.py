import as_moat as m
html = """<div><h1>Meta Platforms Inc</h1><h2>Wide Economic Moat</h2><div>NO MOAT NARROW WIDE</div>
<p>Meta Platforms Inc possesses a wide economic moat due to its strong network effects and significant intangible assets. These advantages allow it.</p>
<span>Network Effects</span><span>Intangible Assets</span><h3>META PLATFORMS INC COMPETITIVE ADVANTAGES</h3>
<h4>Network Effects</h4><p>x</p><h4>Intangible Assets</h4><script>var a="Narrow Economic Moat"</script></div>"""
r = m.parse_moat(html)
assert r["rating"] == "wide" and r["score"] == 100 and r["advantages"] == ["Network Effects", "Intangible Assets"], r
n = m.parse_moat("<h2>Narrow Economic Moat</h2><p>COMPETITIVE ADVANTAGES</p><h4>Switching Costs</h4>")
assert n["rating"] == "narrow" and n["advantages"] == ["Switching Costs"]
z = m.parse_moat("<h2>No Economic Moat</h2>")
assert z["rating"] == "none" and z["score"] == 15
assert m.parse_moat("<p>nothing</p>")["rating"] is None
print("all moat tests passed")
