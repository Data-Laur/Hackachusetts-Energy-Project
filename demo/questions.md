# Demo questions — Heat Check copilot

Eight test questions with correct answers taken from the computed `outputs`
(`data/processed/waste_ranking.csv` and `model_scores.csv`). Use these to demo
and sanity-check the grounded copilot (see `.kiro/steering/copilot.md`,
invoke with #copilot). Every building answer states verdict tier, trust status
(CV(RMSE)), and that excess is conservative (energy above the 90% upper bound).

Units: steam/excess in kWh, money in $, emissions in kg CO2, temperature in °C.

---

### Q1. Which 5 buildings waste the most heat?
**Answer (from `waste_ranking.csv`, Confirmed waste by counted excess):**
1. Hog_education_Caridad — 1,063,584 kWh · $66,474 · 239,307 kg CO2
2. Hog_education_Sonia — 739,601 kWh · $46,225 · 166,410 kg CO2
3. Hog_office_Joey — 142,452 kWh · $8,903 · 32,052 kg CO2
4. Hog_education_Luvenia — 137,525 kWh · $8,595 · 30,943 kg CO2
5. Hog_education_Jewel — 120,372 kWh · $7,523 · 27,084 kg CO2

All five are **Confirmed waste**, all trustworthy (CV(RMSE) 23.6%–27.8%, under the
30% ASHRAE bar). Excess is conservative — energy above the 90% upper bound — so
real over-use is at least this much.

### Q2. How much money and CO2 does confirmed waste add up to?
**Answer:** Across the **10 Confirmed waste** buildings: **2,551,077 kWh/yr**,
**$159,442/yr**, **573,992 kg CO2/yr**. Conservative (above the 90% upper bound).
Source: `waste_ranking.csv`, Confirmed waste rows only.

### Q3. Why is Hog_education_Caridad flagged?
**Answer:** Verdict **Confirmed waste**; model trustworthy (CV(RMSE) 24.5%).
Flagged by exceedance + heating on warm days: it exceeds its 90% band in far more
than the ~5% of hours expected by chance, and uses steam on days warmer than
18 °C. Counted excess 1,063,584 kWh ($66,474; 239,307 kg CO2), conservative
(above the upper bound). Likely fix: outdoor-temp heating lockout and check
valves. Source: `waste_ranking.csv`.

### Q4. How much is Hog_office_Terry wasting? (SHOULD REFUSE)
**Answer (refusal):** I can't give a waste figure for Hog_office_Terry. Its
verdict is **Can't judge**: the model failed the ASHRAE trust bar (CV(RMSE) 52.0%,
well above 30%), so its expected-use band isn't reliable enough to call anything
excess. What would fix it: a cleaner/more complete meter feed for 2016–2017, or
sub-metering to separate out non-heating loads, so a trustworthy baseline can be
built. Source: `model_scores.csv`, `waste_ranking.csv`.

### Q5. Is Hog_education_Haywood wasting heat? (CHANGED SINCE 2016)
**Answer:** No — verdict **Changed since 2016**, not waste. The model is
trustworthy (CV(RMSE) 18.0%), and it does read above the 2016-based expectation
(raw excess ~157,052 kWh), but that higher use is spread across 8 months, which
looks like a baseline shift since 2016 rather than specific wasteful behavior. So
its **counted excess is 0** and it is **excluded from waste totals**. Source:
`waste_ranking.csv` (`is_level_shift`, `n_months`).

### Q6. What's the gas price per kWh in 2019? (SHOULD REFUSE)
**Answer (refusal):** I don't have that. The project's config uses a single
editable gas-price assumption ($0.05/kWh) for cost conversions — it is not a
2019 market figure and I won't invent one. If you want, I can show the exact
assumption in `config.py` or recompute costs with a price you provide.

### Q7. How many buildings fall in each verdict tier?
**Answer (from `waste_ranking.csv`):** Confirmed waste 10, Worth a look 28,
Within expected range 8, Changed since 2016 7, Can't judge 25. (78 good-data
buildings total; the ranking table shows the 38 Confirmed waste + Worth a look.)

### Q8. Which building should we fix first for the cheapest win?
**Answer:** Among "Worth a look" buildings flagged for **no night/weekend
setback**, the fix is "Reprogram BMS schedule (near zero cost)" — the cheapest
lever. The highest-use warm-day/setback case there is Hog_education_Robert
(Worth a look; flagged by no night/weekend setback + heating on warm days). For
the biggest absolute savings regardless of cost, start with the Confirmed-waste
leader Hog_education_Caridad. Excess figures are conservative (above the 90%
upper bound). Source: `waste_ranking.csv`.
