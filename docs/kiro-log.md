# Kiro Log — Heat Check

A running log of significant build steps, decisions, and results. This file is
the single merged log (the old root `KIRO_LOG.md` was folded in here in time
order). The detailed prose entries follow the summary table below.

## Summary (time order)

Credits are shown where known. Most steps predate per-step credit tracking, so
they are marked "—".

| Time | What I asked Kiro | Kiro feature | Result | Credits |
| --- | --- | --- | --- | --- |
| 11:07 | Create steering files for stack, beginner style, secret keys | Steering | Made product.md, tech.md, security.md | — |
| — | Build the spec (requirements/design/tasks), MVP first | Spec | Heat Check spec created; tasks reordered MVP-first | — |
| — | Task 1: data pipeline (load, filter Hog, quality) | Spec task + bash | 97 Hog steam buildings; quality report; bad-data flags | — |
| — | Refine quality checks (flatline, heating-season zeros, spikes) | Inline edits | 78 good / 19 flagged; spikes=0 (data pre-cleaned) | — |
| — | Task 2: weather-normalized baseline + conformal 90% band | Spec task | 32/78 trustworthy (ASHRAE CV(RMSE) ≤ 30%) | — |
| — | Task 3: two-method waste detection + ranking | Spec task | Exceedance + pattern metrics; $/CO2 via config | — |
| — | Level-shift check, seasonal conformal, verdict tiers | Inline edits | 5 tiers; "Changed since 2016" excluded from totals | — |
| — | Verdict thresholds, limitations, download script, repo checks | Inline + bash | All 5 tiers populated; scripts/download_data.py; repo public | — |
| — | Task 4: interactive single-file HTML report | Spec task | docs/index.html (3.3 MB, Plotly CDN), 2 views | — |
| — | Report scope fix; Kiro copilot; property-based tests | Steering + tests | copilot.md (manual); PBT caught a real band bug | — |
| — | MCP source verification + bring-your-own-data workflow | MCP + Hooks | config assumptions cited; inbox ingest hook + samples | — |
| — | Merge logs; tasks.md completion hook; MCP recheck; real samples; CI | Hooks + MCP + CI | Single log; CI workflow + badge; real Bull samples | — |

## Entry — Quality, features, and conformal improvements (tasks 1 & 2 rerun)

### What changed
1. **Spike check (stage 1):** flag hourly readings above 10× a building's own
   99th percentile, set them to missing, and report the count per building.
2. **Richer model features (stage 2):** added 24-hour rolling mean outdoor
   temperature, month, and a holiday/academic-break flag (US federal holidays +
   Dec 20–Jan 10). Kept hour, is_weekend, airTemperature.
3. **Better conformal intervals (stage 2):** calibrate on every 5th week sampled
   across all of 2016 (not just the last 20%), using NORMALIZED conformal
   (residual ÷ max(prediction, 1.0 kWh)) so the band narrows at low use.

### Results — before vs after

| Metric | Before | After |
| --- | --- | --- |
| Trustworthy (CV(RMSE) ≤ 30%) | 31 / 78 | 32 / 78 |
| Median CV(RMSE) | 38.8% | 35.8% |
| Overall 90% coverage | 87.5% | 83.6% |
| Coverage — heating season (Oct–Apr) | 85.8% | 87.5% |
| Coverage — summer | 89.9% | 78.2% |

### Notes / honest caveats
- **Spikes removed: 0.** No reading in the BDG2 `steam_cleaned.csv` exceeds 10× a
  building's 99th percentile (highest ratio seen: 2.28×). Expected, since this
  file is already BDG2-cleaned. The check stays as a guard.
- Richer features improved accuracy (median CV(RMSE) −3 pts, +1 trustworthy).
- Normalized conformal **improved heating-season coverage** toward 90% but
  **reduced summer coverage** (bands get very narrow when predicted use is near
  zero). This is a known trade-off; for waste detection it means more summer
  exceedances will fire, which we interpret with care.

Units throughout: steam in kWh, temperature in °C.
Data source: Building Data Genome Project 2 (Miller et al., Sci Data 7, 368, 2020,
https://doi.org/10.1038/s41597-020-00712-x).

## Entry — Task 3: two-method waste detection + ranking

### What was built (`waste_detect.py`)
- **Method A — exceedance (trustworthy models only):** sum 2017 hours where
  actual steam > the 90% upper band; convert excess kWh → $ and kg CO2 via
  `config.py`.
- **Method B — pattern metrics (all good-data buildings, no model needed):**
  - setback ratio = night(22–05)/weekend vs occupied-weekday(08–18) steam,
    compared within 2 °C temperature bins (so weather doesn't confound it);
  - warm-day heating = total steam when outdoor temp > 18 °C;
  - flag the worst quartile for each.
- A building can be "Can't judge" for Method A yet still flagged by Method B; the
  `flagged_by` column names the method(s).

### Results
- 78 buildings ranked. Verdicts: 53 "Wasting heat", 25 "Can't judge".
- 32 trustworthy models ranked by exceedance; 21 non-trustworthy good-data
  buildings still flagged by a pattern (e.g. Hog_education_Robert).
- Top waster: Hog_education_Caridad — ~1,112,334 kWh excess ≈ $69,521 and
  ~250,275 kg CO2, flagged by exceedance + heating on warm days.

### Honest caveat
- "Wasting heat" = 53/78 is high because worst-quartile pattern flags guarantee
  ~25% of buildings get a pattern flag by construction, and any flag currently
  yields "Wasting heat". Plan to separate "exceedance-confirmed" from
  "pattern-only" in the report (task 4) so the headline isn't inflated.

Units: excess energy/steam in kWh, money in $, emissions in kg CO2, temp in °C.

## Entry — Level-shift check, seasonal conformal, verdict tiers

### 1. Seasonal (Mondrian) two-sided conformal
Calibrate separate band widths for heating season (Oct–Apr) vs summer, and use
two-sided (asymmetric) quantiles since real errors are skewed (2017 often runs
hotter than 2016).

Coverage before vs after:

| Coverage | Before (symmetric, all-season) | After (two-sided seasonal) |
| --- | --- | --- |
| Overall | 83.6% | 80.7% |
| Heating (Oct–Apr) | 87.5% | 83.5% |
| Summer | 78.2% | 76.8% |

**Key finding:** the 2017 shortfall from 90% is NOT miscalibration. An
in-distribution control (train quantiles on half the 2016 calibration weeks,
test coverage on the other half) gives **89.5%** — right on target. The 2017 gap
is genuine year-over-year distribution shift (the thing Heat Check exists to
find). Forcing 90% by widening bands would hide real excess, so we did not.
This belongs in the report's "What we can't see" section.

### 2. Level-shift check ("Changed since 2016")
For each exceedance-flagged building, measure how the excess spreads across
months and hours-of-day. If it carries meaningful excess in >=8 months AND >=16
hours, it's a broad baseline shift, relabeled "Changed since 2016" and EXCLUDED
from waste totals. 7 buildings reclassified.

- **Hog_education_Caridad -> Confirmed waste** (excess in 6/12 months, spikes in
  Oct–Dec; May/Jun below expected -> seasonal, not a level shift).
- **Hog_education_Sonia -> Confirmed waste** (excess in 6/12 months, big in
  Apr/May + Sep/Oct shoulder seasons; Jan/Feb/Nov below expected).
- Monthly chart: outputs/monthly_actual_vs_expected.html

### 3. Verdict tiers + conservative excess
Excess is measured as **actual minus the 90% UPPER bound** (conservative — only
counts what clears the band). Five tiers:

| Tier | Count |
| --- | --- |
| Confirmed waste | 25 |
| Worth a look | 21 |
| Changed since 2016 | 7 |
| Can't judge | 25 |
| Within expected range | 0 |

New top waster unchanged (Hog_education_Caridad, ~1,063,585 kWh counted excess ≈
$66,474, 239,307 kg CO2). Cathleen/Haywood dropped out of the top 10 as level
shifts.

## Entry — Verdict thresholds, limitations, download script, repo checks

### Verdict thresholds (now credible — all 5 tiers populated)
- **Confirmed waste** requires BOTH (in config.py):
  - `CONFIRMED_MIN_EXCEED_SHARE = 0.10` — >10% of 2017 hours above the upper band
    (vs ~5% expected by chance), AND
  - `CONFIRMED_MIN_EXCESS_SHARE = 0.015` — counted excess ≥ 1.5% of 2017 steam.
    (Set to 1.5% not 5% because excess is measured conservatively as
    actual − upper90, so even chronic over-users rarely clear 5% of annual kWh.
    An in-data distribution check showed only 1 building clears 5% but 12 clear
    the >10%-of-hours bar; 1.5% confirms the clear chronic exceeders.)
- **Worth a look** (pattern): worst quartile AND an absolute floor (in config.py):
  - `SETBACK_RATIO_FLOOR = 0.70` (night/weekend ≥ 70% of occupied at similar temp), or
  - `WARMDAY_MIN_ANNUAL_SHARE = 0.05` (warm-day steam ≥ 5% of annual steam).
- Everything else trustworthy = **Within expected range**.

Counts per tier: Confirmed waste 10, Worth a look 28, Within expected range 8,
Changed since 2016 7, Can't judge 25.

Top waster unchanged: Hog_education_Caridad — 1,063,585 kWh excess ≈ $66,474,
239,307 kg CO2 (Confirmed waste).

### "What we can't see" notes
Added docs/what-we-cant-see.md. Two new points per request: (1) 2017 coverage
80.7% vs 89.5% in-distribution = real year-over-year drift; (2) the level-shift
rule (8+ months) can miss changes that started partway through 2017.

### Repo requirements (hackathon rules)
- `scripts/download_data.py` added: downloads metadata.csv, steam_cleaned.csv,
  weather.csv from the BDG2 LFS media host into Datasets/. Verified working
  (urllib → curl fallback handles the macOS SSL cert issue). Skips files that
  already exist.
- `.kiro/` confirmed at repo root, NOT gitignored (git check-ignore exits 1),
  and tracked in HEAD (specs + steering), already pushed.
- Repo is **public**: https://github.com/Data-Laur/Hackachusetts-Energy-Project
  (HTTP 200 unauthenticated).

## Entry — Task 4: interactive single-file HTML report

### What was built (`src/report.py` -> `docs/index.html`)
One self-contained page (no server, no Streamlit), Plotly via CDN. One command
regenerates it: `python src/report.py` from the repo root.

- **View 1 Triage:** headline cards (Confirmed waste count; $/yr and kWh/yr from
  Confirmed waste only, labeled "conservative: energy above the 90% upper bound";
  Worth a look; Can't judge). Ranked table (Confirmed waste then Worth a look,
  each by excess) with building, type, verdict, flagged by, pattern, likely fix,
  excess kWh/$/kg CO2. Filters by type and verdict. Within expected range /
  Changed since 2016 / Can't judge excluded from the ranking and listed with
  reasons in a collapsible section.
- **Likely-fix mapping:** no setback -> "Reprogram BMS schedule (near zero cost)";
  warm-day -> "Outdoor-temp heating lockout, check valves (low cost)";
  exceedance only -> "Investigate controls and steam traps".
- **View 2 Building detail:** verdict + CV(RMSE)/trust; actual-vs-expected chart
  with 90% band (worst week default + week picker, top 12 worst weeks);
  hour x day-of-week excess heatmap; monthly actual-vs-expected bars.
- **Method / What we can't see / Data** sections, including the 89.5%
  in-distribution vs 80.7% 2017 coverage finding and the BDG2 citation.

### Accessibility
Okabe-Ito colorblind-safe palette, left nav + main layout, keyboard-focusable
table rows, ARIA labels on charts, plain-language labels.

### Size
Trimmed from 15.9 MB to 3.3 MB by keeping only the 12 worst weeks per building
and compact time labels (Plotly stays on the CDN, not in the file).

### GitHub Pages
gh CLI not installed on this machine, so Pages must be enabled via the web UI
(Settings -> Pages -> Source: Deploy from a branch -> main / docs).
Expected URL: https://data-laur.github.io/Hackachusetts-Energy-Project/

## Entry — Report fix, Kiro copilot, property-based testing

### 1. Report Data-section scope line
Changed to: "Scope: site Hog, steam meters only. Models trained on 2016; all
results shown are for 2017. Steam in kWh, temperature in C." Regenerated
docs/index.html via `python src/report.py` (one command).
Kiro feature: inline edit + single-command regeneration.

### 2. Kiro copilot (steering)
Created `.kiro/steering/copilot.md` with **inclusion: manual**. Rationale: these
rules govern how I ANSWER result questions, which is irrelevant to unrelated
coding on the repo; forcing them into every turn would constrain normal help and
waste context. Manual lets you pull them in with #copilot exactly when wanted.
(fileMatch rejected: questions are asked in chat, not tied to opening a file.)
Rules: answer only from data/processed/, docs/, or src/ functions; never invent
numbers; always give verdict tier + trust status (CV(RMSE)) + the conservative-
excess note; refuse "Can't judge" with a reason and the data that would fix it.

Created `demo/questions.md` with 8 Q&A from the outputs, including 2 refusals
(Q4 Hog_office_Terry = Can't judge, CV(RMSE) 52%; Q6 a 2019 gas price we don't
have) and 1 "Changed since 2016" (Q5 Hog_education_Haywood, excess across 8
months -> counted excess 0, excluded from totals).
Kiro feature: steering file (manual inclusion).

### 3. Property-based testing (hypothesis)
Added `tests/test_properties.py` (pytest + hypothesis), each property tied to a
requirement:
- Req 2: lower90 <= expected <= upper90 for every row.
- Req 3: per-hour excess >= 0 and = 0 when actual <= upper band.
- Req 3/4: exactly one verdict tier per building, from the known set.
- Req 3: "Changed since 2016" and "Can't judge" contribute 0 to waste totals.
- Req 3: warm_day_share in [0,1]; setback_ratio >= 0 (NOT bounded by 1 — a
  building with no setback can use MORE at night; documented, not asserted).
- Req 3: money_and_co2 is linear, non-negative, and round-trips kWh<->$<->CO2.

**PBT caught a real bug a unit test would likely have missed:**
`test_band_ordering` failed — 5,990 rows across 37 buildings had
`expected > upper90`. Root cause: the two-sided seasonal conformal upper quantile
can be negative for buildings that systematically overpredict, and we clipped
`expected`/`lower` at 0 but never enforced that the band brackets the point
prediction. A hand-written unit test on one or two sample rows would almost
certainly have picked "normal" rows and passed; hypothesis-style checking over
ALL rows surfaced the near-zero-prediction edge case. Fix in baseline_model.py:
after clipping expected at 0, enforce lower <= expected <= upper explicitly.
Totals barely moved (confirmed-waste 2,554,579 -> 2,551,077 kWh, 0.14%),
confirming it was an edge-case band bug, not a logic error in exceedance.
All 9 properties pass after the fix. Regenerated predictions, ranking, and report.
Kiro feature: test authoring + run-and-diagnose loop.

## Entry — MCP source verification + bring-your-own-data workflow

### 1. MCP (web fetch) — verifying assumptions from primary sources
Intended to add a fetch MCP server at `.kiro/settings/mcp.json`:
```json
{"mcpServers":{"fetch":{"command":"uvx","args":["mcp-server-fetch"],
 "env":{"FASTMCP_LOG_LEVEL":"ERROR"},"disabled":false,"autoApprove":["fetch"]}}}
```
Writing that path is blocked by a workspace permission rule, so the user needs to
add it. I verified the two assumptions against primary sources regardless:

- **Steam unit (BDG2):** CONFIRMED kWh. The BDG2 data paper (Miller et al. 2020,
  Sci Data) Table 4 shows Hog steam was originally `lbsperhour`, and the paper
  states all meter data was converted to kWh. Source:
  https://pmc.ncbi.nlm.nih.gov/articles/PMC7591488/ (Tables 4–5). config.py
  comment updated; no value change.
- **CO2 emission factor:** EIA/EPA list 53.06 kg CO2/MMBtu for natural gas;
  1 MMBtu = 293.07 kWh, so 0.1811 kg CO2/kWh. Updated config from 0.18 ->
  0.1811. Source: https://www.eia.gov/environment/emissions/archive/coefficients.php
- **Boiler efficiency:** NOT an EPA emissions quantity (it's site equipment), so
  it can't be pinned from EPA; left as an editable 0.80 assumption with a note.

Headline change after the 0.18 -> 0.1811 fix: Confirmed-waste CO2 573,992 ->
**577,500 kg/yr** (+0.6%); dollars and verdict tiers unchanged (dollars key off
gas price, not the emission factor). Reran stages 3–4; property tests still pass.

What MCP made possible: letting the agent pull the actual EPA/EIA and BDG2 pages
during the run to check numbers against primary sources, instead of relying on
memorized constants — turning "probably ~0.18" into a cited 0.1811.

### 2. Bring-your-own-data workflow
- **samples/** (synthetic Bull-site data, each < 1 MB):
  - `sample_A_long_mmbtu.csv` — long, "Date/Time","Bldg Name","Steam (MMBtu)"
  - `sample_B_wide_kwh.csv` — wide, "Reading Time" + one kWh column per building
  - `sample_C_ambiguous.csv` — long but value column is "Usage" (no unit)
- **`src/ingest.py`** — detects long vs wide, maps columns to
  timestamp/building_id/steam_kwh, converts MMBtu/kBTU -> kWh, writes
  `inbox/mapping_report.md`, and STOPS on ambiguity instead of guessing;
  otherwise scores buildings to `inbox/results/`.
- **Agent hook** `.kiro/hooks/inbox-ingest.json` — PostFileCreate on
  `inbox/.*\.csv$`, runs the ingester (file path read from the hook's stdin JSON).
- **Tested** by copying A and C into inbox/:
  - A -> long format, MMBtu x293.07 -> kWh, scored 3 buildings.
  - C -> flagged AMBIGUOUS ("Usage" has no unit), stopped for review.
  Saved both reports: `samples/mapping_report_sample_A.md`,
  `samples/mapping_report_sample_C.md`. B also verified (wide, unit from filename).
Kiro features used: MCP (web fetch) and agent hooks.


## Entry — Log merge, task-completion hook, MCP recheck, real samples, CI

### 1. Logs merged
Folded the root `KIRO_LOG.md` into this file (added the time-ordered summary
table at the top, with a Credits column — "—" where credits weren't tracked) and
deleted `KIRO_LOG.md`. One log now: `docs/kiro-log.md`.

### 2. Task-completion hook
Added `.kiro/hooks/log-task-completion.json` (PostFileSave on `tasks.md`) calling
`scripts/log_task_completion.py`. It counts completed top-level tasks and appends
a row here only when the count goes UP (tracked via a small `.task_count` state
file so cosmetic edits don't spam the log). Both this hook and the earlier
`inbox-ingest` hook are in `.kiro/hooks/` and show in the Agent Hooks panel.

### 3. MCP recheck (user fixed the server with a full uvx path)
The user got the fetch MCP server connecting by using the absolute uvx path in
`.kiro/settings/mcp.json`:
`"command": "/Users/laurenchagaris/.local/bin/uvx"` (the bare `uvx` wasn't on the
MCP process PATH). I used the **fetch MCP server** (not built-in fetch) to
re-verify the natural-gas CO2 factor:
- The requested archive URL
  (https://www.eia.gov/environment/emissions/archive/coefficients.php) is under
  `/archive/`, which EIA's robots.txt disallows — the MCP fetch server honors
  robots.txt and refused (built-in fetch earlier did not). Honest finding, not a
  setup failure.
- I fetched the CURRENT EIA page instead
  (https://www.eia.gov/environment/emissions/co2_vol_mass.php, released
  2024-09-18, 2022 data, carbon factors from the EPA GHG Inventory): Natural Gas
  = **52.91 kg CO2/MMBtu**. The older archived page said 53.06.
- Updated config from 0.1811 -> **0.1805 kg CO2/kWh** (52.91 / 293.07122).
  Headline: Confirmed-waste CO2 577,500 -> **575,587 kg/yr**; dollars and tiers
  unchanged. Reran stages 3-4; property tests still pass (9/9).

### 4. Sample files rebuilt from REAL Bull data
`samples/_make_samples.py` now pulls real Bull-site buildings from
`Datasets/steam_cleaned.csv` (a 2-week window, cleanest buildings), still in the
three messy formats (A long MMBtu, B wide kWh, C ambiguous "Usage"), each < 1 MB.

**How the ingester gets weather:** it does NOT fetch weather automatically. An
arbitrary uploaded `building_id` isn't tied to a known BDG2 site, so only the
weather-FREE checks run; the report says to supply a matching weather file to
enable the temperature-based (setback/warm-day) and model methods.

**What "scored" means for an upload** (now stated in the results CSV + report):
a dropped-in file has no separate 2016 training year, so the full
weather-normalized model usually can't run. Per building, by data length:
`>= 1 week` data-quality check; `>= ~3 months` pattern checks; `>= 12 months +
weather` full model + 90% conformal band. The 2-week samples therefore score as
"Data-quality check only: not enough data for pattern checks".

### 5. CI
Added `.github/workflows/ci.yml` (runs on every push + PRs): installs
requirements, runs the ingester on `samples/` (asserts sample C is flagged
AMBIGUOUS), and runs the property-based tests (data-driven ones skip without
Datasets/, pure-function ones always run). Added a CI status badge to
`README.md`.
Kiro features used: agent hooks, MCP (fetch server), and the test/CI loop.


## Entry — Real-results samples (with weather) + portable MCP config

### 1. Samples rebuilt so uploads show real results
`samples/_make_samples.py` now uses 4 months of REAL Bull data (Jan–Apr 2017),
3–4 buildings, and adds an outdoor-temperature column in Fahrenheit
("Outdoor Temp (F)") joined from Bull weather. Each file stays < 1 MB (A 427 KB,
B 126 KB, C 405 KB). Sample C is still ambiguous ("Usage", no steam unit).

Ingester upgrades (`src/ingest.py`):
- Detects an outdoor-temperature column (separately from steam), recognizes
  Fahrenheit from the name, and converts F -> C.
- Carries temperature through long AND wide mapping.
- With temperature + >= ~3 months of data, runs the REAL pattern checks
  (setback ratio + warm-day share) using the same functions as `waste_detect.py`.
- Added repo-root to sys.path so `python src/ingest.py` can import waste_detect.

Results on the new samples (pattern checks now run):
- A: Bull_assembly_Lance setback 0.95 / warm-day 49.0%; Clarice 0.90 / 40.5%;
  Dan 0.98 / 43.5% — all "Pattern checks only" (3.9 months < 12).
- B: Gregory 0.76 / 30.8%; Jeremiah 0.95 / 53.1%; Lettie 0.92 / 48.6%;
  Trevor 0.80 / 46.3%.
- C: still STOPS — detects the temp column but refuses because "Usage" has no
  steam unit.
Property tests still pass (9/9).

### 2. Portable MCP config + README note
The whole `.kiro/settings/` path is write-protected for the agent, so I could not
create the portable file there directly (which also means the user's working
`mcp.json` was never touched). Instead:
- Committed a portable template at `docs/mcp.example.json` using plain `"uvx"`.
- Gitignored `.kiro/settings/mcp.json` (confirmed it was never tracked, so the
  user's absolute uvx path never leaked).
- README note added: copy `docs/mcp.example.json` -> `.kiro/settings/mcp.json`;
  "On macOS, if the fetch server fails to connect, replace uvx with the full path
  from `which uvx`." The user's local full-path config keeps working untouched.
