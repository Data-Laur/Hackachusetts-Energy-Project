# Kiro Log — Heat Check

A running log of significant build steps, decisions, and results.

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
