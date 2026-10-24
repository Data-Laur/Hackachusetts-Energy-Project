# Design — Heat Check

## Overview

Heat Check is a local Python pipeline that turns raw BDG2 meter + weather data
into a ranked, uncertainty-aware list of heat-wasting buildings, plus a Streamlit
app to explore it and (stretch) an LLM copilot that only speaks in computed facts.

The guiding principle: **prove it or refuse**. Every claim carries an interval and
a trust label; weak evidence yields "Can't judge" rather than a guess.

## Architecture

```
Datasets/ (gitignored raw CSVs)
      │
      ▼
[1] data_pipeline.py ──► data/processed/clean_long.csv.gz  (tidy: timestamp, building_id, steam, airTemperature, ...)
      │                  data/processed/quality_report.csv   (per-building % missing/zeros/flatline + bad-data flag)
      ▼
[2] baseline_model.py ─► data/processed/predictions.csv.gz  (actual, expected, lower90, upper90 per hour)
      │                  data/processed/model_scores.csv      (CV(RMSE), trustworthy flag)
      ▼
[3] waste_detect.py ──► data/processed/waste_ranking.csv      (excess kWh, $, CO2, pattern labels, verdict)
      │                  config.py                             (gas price, boiler efficiency, emission factor — EDITABLE)
      ▼
[4] src/report.py ────► outputs/report.html                   (self-contained Plotly report: headline numbers,
      │                                                         ranked table + verdicts, top-5 actual-vs-expected
      │                                                         charts with 90% band, "What we can't see")
      ▼ (stretch)
[5] Kiro chat is the copilot, governed by .kiro/steering/copilot.md
    (answers only from outputs/ files or by running src/ functions)
[6] demo/questions.md  [7] README.md
```

### Why these choices (beginner-friendly)
- **One script per stage**, each writing a file the next stage reads. You can run
  and inspect each step independently — easy to debug, easy to demo.
- **Flat files between stages** (gzipped CSV) so nothing is hidden in memory and
  you can unzip and open any intermediate file to inspect it. No parquet/pyarrow
  dependency needed.
- **A single `config.py`** for every assumption (prices, factors, thresholds) so
  tuning never means hunting through code.

## Components

### [1] Data pipeline (`data_pipeline.py`)
- Load three CSVs with pandas.
- Filter metadata to `site_id == "Hog"` and steam == "Yes" → list of building_ids.
- Melt steam wide→long: `timestamp, building_id, steam`.
- Join weather on `site_id + timestamp` (metadata gives each building its site).
- Quality metrics per building: % missing, % zeros, longest consecutive flat run.
- Bad-data flag using thresholds in `config.py`.
- Print summary (count by `primaryspaceusage`, date range, quality table).

### [2] Baseline model (`baseline_model.py`)
- Features: `airTemperature`, `hour` (0–23), `is_weekend` (0/1).
- Model: scikit-learn, simple and explainable (e.g. gradient boosting or linear
  with basis features). One model per building.
- Train on 2016, test on 2017.
- **Split conformal intervals (90%):** hold out a calibration slice of 2016, take
  residual quantiles, add/subtract to get `lower90`/`upper90` on 2017.
- **CV(RMSE)** = RMSE / mean(actual) on the test year. Trustworthy if ≤ 30%
  (ASHRAE Guideline 14 hourly M&V criterion).

### [3] Waste detection + economics (`waste_detect.py`)
- Excess hour: `actual > upper90`. Excess energy = `actual - expected` (kWh) summed.
- Pattern labels:
  - "heating on warm days": excess hours where `airTemperature > 18 °C`.
  - "no night/weekend setback": excess concentrated in nights (e.g. 22:00–05:00)
    and weekends.
- Rank trustworthy buildings by total excess kWh.
- Convert via `config.py`: `cost = excess_kWh / boiler_efficiency * gas_price`,
  `co2 = excess_kWh / boiler_efficiency * emission_factor`. Each constant carries
  a source comment.

### [4] Static HTML report (`src/report.py`)
- Generates **one self-contained `outputs/report.html`** using Plotly. Charts are
  embedded in the HTML (e.g. `include_plotlyjs="inline"` / `fig.to_html`) so the
  file opens standalone in a browser with no server.
- Contents:
  - **Headline numbers:** total excess kWh, dollars, and CO2 across trustworthy
    buildings — each labeled with its unit.
  - **Ranked table** with a verdict per building:
    - "Wasting heat" (trustworthy + meaningful excess),
    - "Within expected range" (trustworthy + little/no excess),
    - "Can't judge (weak model or bad data)" (not trustworthy OR bad data).
  - **Top-5 charts:** actual vs expected steam with the 90% band shaded and waste
    hours highlighted, axes labeled with units.
  - **"What we can't see"** section listing method limitations.
- Reads only the computed files — no numbers typed into the report.

### [5] Copilot = Kiro chat (stretch, `.kiro/steering/copilot.md`)
- There is **no app and no server**. Kiro chat is the copilot.
- A steering file `.kiro/steering/copilot.md` constrains answers: respond ONLY
  from files in `outputs/` or by running functions in `src/`; never invent
  numbers; always state the 90% range and model trust level; refuse with a reason
  for any "Can't judge" building.

### [6] Demo questions (stretch, `demo/questions.md`)
- 8 test questions with correct answers derived from the `outputs/` files, each
  numeric answer carrying its 90% range and trust level. Used to demo and
  sanity-check the grounded-copilot behavior.

## Data flow / file layout
```
Datasets/              raw CSVs (gitignored)
data/processed/        pipeline outputs (gitignored)
config.py              all editable assumptions + thresholds
data_pipeline.py       stage 1
baseline_model.py      stage 2
waste_detect.py        stage 3
src/report.py          stage 4 (self-contained HTML report)
outputs/report.html    generated report (gitignored)
.kiro/steering/copilot.md  stage 5 (Kiro-chat copilot rules, stretch)
demo/questions.md      stage 6 (8 demo Q&A, stretch)
requirements.txt       pinned deps
```

## Error handling
- Missing file / wrong path → clear message naming the expected path.
- Building with too little data → flagged bad, excluded, shown as "Can't judge".
- Model fails to fit → caught, building marked not trustworthy.
- Any division (CV(RMSE), cost) guards against divide-by-zero.

## Testing strategy
- Manual smoke test after each stage (inspect the printed summary / output file).
- Spot-check 2–3 buildings end to end against the report charts.
- The 8 demo questions (stretch) double as a sanity check of the numbers.
- No automated test suite unless requested (hackathon scope).

## Security
- No server, no app, no API keys in this build — the copilot is Kiro chat.
- `Datasets/`, `data/processed/`, and `outputs/` are gitignored (data + generated
  artifacts never committed).
- If a provider key is ever added later, load it only from `.env` or environment
  variables, never hardcoded.
