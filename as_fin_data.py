Run xvfb-run -a python as_fin_test.py
as_fin_test v1 | stocks: ['nasdaq/adsk', 'nyse/orcl', 'nyse/uber'] | repeats: 2 | strategies: all
DISCOVERY nasdaq/adsk: switch=clicked changed=True requests=[{"kind":"fetch","url":"https://www.alphaspread.com/livewire-d9d06e2d/update","status":200,"head":"{\"components\":[{\"snapshot\":\"{\\\"data\\\":{\\\"companyId\\\":4626,\\\"statement\\\":\\\"income-s
[nasdaq/adsk] F1_auto rep1: FAIL consistency: FCF=OCF-capex 6/10 (26s)
[nasdaq/adsk] F1_auto rep2: FAIL consistency: FCF=OCF-capex 6/10 (19s)
[nasdaq/adsk] F2_select rep1: FAIL unit:bs:still B/T suffixes (56s)
[nasdaq/adsk] F2_select rep2: FAIL unit:is:still B/T suffixes (13s)
[nasdaq/adsk] F3_click_js rep1: FAIL unit:is:still B/T suffixes (42s)
[nasdaq/adsk] F3_click_js rep2: FAIL blocked:is (105s)
[nasdaq/adsk] F4_click_real rep1: OK FCF=OCF-capex 10/10 (26s)
[nasdaq/adsk] F4_click_real rep2: OK FCF=OCF-capex 10/10 (118s)
[nasdaq/adsk] F5_reload_f2 rep1: OK FCF=OCF-capex 10/10 (22s)
[nasdaq/adsk] F5_reload_f2 rep2: OK FCF=OCF-capex 10/10 (22s)
[nasdaq/adsk] F6_ensure rep1: OK FCF=OCF-capex 10/10 (22s)
[nasdaq/adsk] F6_ensure rep2: OK FCF=OCF-capex 10/10 (22s)
[nasdaq/adsk] R1_requests rep1: FAIL unit:is:HTTP 403 no FY table in the answer (5863 chars) (6s)
[nasdaq/adsk] R1_requests rep2: FAIL unit:is:HTTP 403 no FY table in the answer (5841 chars) (6s)
[nasdaq/adsk] extras solvency rep1: OK {'net_debt': -1200.0, 'int_cov': 23.61, 'de': 0.88, 'altman_z': 3.87, 'bankrupt_pct': None}
[nasdaq/adsk] extras moat rep1: OK Wide
[nasdaq/adsk] extras profitability rep1: OK 15.0
[nasdaq/adsk] extras solvency rep2: OK {'net_debt': -1200.0, 'int_cov': 23.61, 'de': 0.88, 'altman_z': 3.87, 'bankrupt_pct': None}
[nasdaq/adsk] extras moat rep2: OK Wide
[nasdaq/adsk] extras profitability rep2: OK 15.0
DISCOVERY nyse/orcl: switch=clicked changed=True requests=[{"kind":"fetch","url":"https://www.alphaspread.com/livewire-d9d06e2d/update","status":200,"head":"{\"components\":[{\"snapshot\":\"{\\\"data\\\":{\\\"companyId\\\":241,\\\"statement\\\":\\\"income-st
[nyse/orcl] F1_auto rep1: OK FCF=OCF-capex 10/10 (19s)
[nyse/orcl] F1_auto rep2: OK FCF=OCF-capex 10/10 (19s)
[nyse/orcl] F2_select rep1: OK FCF=OCF-capex 10/10 (22s)
[nyse/orcl] F2_select rep2: OK FCF=OCF-capex 10/10 (56s)
[nyse/orcl] F3_click_js rep1: OK FCF=OCF-capex 10/10 (25s)
[nyse/orcl] F3_click_js rep2: OK FCF=OCF-capex 10/10 (25s)
[nyse/orcl] F4_click_real rep1: OK FCF=OCF-capex 10/10 (26s)
[nyse/orcl] F4_click_real rep2: OK FCF=OCF-capex 10/10 (26s)
[nyse/orcl] F5_reload_f2 rep1: OK FCF=OCF-capex 10/10 (22s)
[nyse/orcl] F5_reload_f2 rep2: OK FCF=OCF-capex 10/10 (22s)
[nyse/orcl] F6_ensure rep1: OK FCF=OCF-capex 10/10 (22s)
[nyse/orcl] F6_ensure rep2: OK FCF=OCF-capex 10/10 (22s)
[nyse/orcl] R1_requests rep1: FAIL unit:is:HTTP 403 no FY table in the answer (5814 chars) (6s)
[nyse/orcl] R1_requests rep2: FAIL unit:is:HTTP 403 no FY table in the answer (5814 chars) (6s)
[nyse/orcl] extras solvency rep1: OK {'net_debt': 89100.0, 'int_cov': 5.76, 'de': 1.89, 'altman_z': 1.42, 'bankrupt_pct': None}
[nyse/orcl] extras moat rep1: FAIL None
[nyse/orcl] extras profitability rep1: OK 11.0
[nyse/orcl] extras solvency rep2: OK {'net_debt': 89100.0, 'int_cov': 5.76, 'de': 1.89, 'altman_z': 1.42, 'bankrupt_pct': None}
[nyse/orcl] extras moat rep2: FAIL None
[nyse/orcl] extras profitability rep2: OK 11.0
DISCOVERY nyse/uber: switch=clicked changed=True requests=[{"kind":"fetch","url":"https://www.alphaspread.com/livewire-d9d06e2d/update","status":200,"head":"{\"components\":[{\"snapshot\":\"{\\\"data\\\":{\\\"companyId\\\":1165,\\\"statement\\\":\\\"income-s
[nyse/uber] F1_auto rep1: OK FCF=OCF-capex 8/10 (19s)
[nyse/uber] F1_auto rep2: OK FCF=OCF-capex 8/10 (19s)
[nyse/uber] F2_select rep1: OK FCF=OCF-capex 10/10 (22s)
[nyse/uber] F2_select rep2: OK FCF=OCF-capex 10/10 (22s)
[nyse/uber] F3_click_js rep1: OK FCF=OCF-capex 10/10 (25s)
[nyse/uber] F3_click_js rep2: OK FCF=OCF-capex 10/10 (25s)
[nyse/uber] F4_click_real rep1: FAIL unit:is:real click failed: ElementNotVisibleException (12s)
[nyse/uber] F4_click_real rep2: FAIL unit:is:real click failed: ElementNotVisibleException (46s)
[nyse/uber] F5_reload_f2 rep1: OK FCF=OCF-capex 10/10 (22s)
[nyse/uber] F5_reload_f2 rep2: OK FCF=OCF-capex 10/10 (22s)
[nyse/uber] F6_ensure rep1: OK FCF=OCF-capex 10/10 (22s)
[nyse/uber] F6_ensure rep2: OK FCF=OCF-capex 10/10 (22s)
[nyse/uber] R1_requests rep1: FAIL unit:is:HTTP 403 no FY table in the answer (5814 chars) (6s)
[nyse/uber] R1_requests rep2: FAIL unit:is:HTTP 403 no FY table in the answer (5814 chars) (6s)
[nyse/uber] extras solvency rep1: OK {'net_debt': 5300.0, 'int_cov': 16.79, 'de': 0.39, 'altman_z': 3.13, 'bankrupt_pct': None}
[nyse/uber] extras moat rep1: FAIL None
[nyse/uber] extras profitability rep1: OK 15.0
[nyse/uber] extras solvency rep2: OK {'net_debt': 5300.0, 'int_cov': 16.79, 'de': 0.39, 'altman_z': 3.13, 'bankrupt_pct': None}
[nyse/uber] extras moat rep2: FAIL None
[nyse/uber] extras profitability rep2: OK 15.0

| part | strategy | ok / runs | avg s | Cloudflare hits | failures |
|---|---|---|---|---|---|
| extras | solvency | 6/6 | 6 | 0 |  |
| extras | profitability | 6/6 | 6 | 0 |  |
| extras | moat | 2/6 | 21 | 0 | not parsed: |
| statements | F5_reload_f2 | 6/6 | 22 | 0 |  |
| statements | F6_ensure | 6/6 | 22 | 0 |  |
| statements | F1_auto | 4/6 | 20 | 1 | consistency: FCF=OCF-capex 6/10 |
| statements | F2_select | 4/6 | 32 | 3 | unit:bs; unit:is |
| statements | F3_click_js | 4/6 | 42 | 4 | blocked:is; unit:is |
| statements | F4_click_real | 4/6 | 43 | 3 | unit:is |
| statements | R1_requests | 0/6 | 6 | 0 | unit:is |
