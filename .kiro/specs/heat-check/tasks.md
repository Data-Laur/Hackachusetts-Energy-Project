# Tasks — Heat Check

MVP first: tasks 1–4 produce a working demo on their own. Do not start stretch
tasks (5–7) until the MVP works and is pushed to GitHub.

## MVP

- [x] 1. Project setup + data pipeline
  - [x] 1.1 Add `Datasets/` and `data/processed/` to `.gitignore`; create
    `requirements.txt` (pinned: pandas, scikit-learn, plotly) and `config.py`
    with thresholds + economic assumptions
    (each constant commented with its source).
  - [x] 1.2 Write `data_pipeline.py`: load the 3 CSVs, filter to `site_id="Hog"`
    and steam=="Yes", melt steam wide→long (`timestamp, building_id, steam`),
    join weather on `site_id + timestamp`.
  - [x] 1.3 Compute per-building quality (% missing, % zeros, longest flatline)
    and set a bad-data flag from `config.py` thresholds.
  - [x] 1.4 Print the summary (count by `primaryspaceusage`, date range, quality
    table) and save `clean_long.csv.gz` + `quality_report.csv`.
  - _How to run:_ `python data_pipeline.py` — read the printed summary; confirm
    ~97 buildings and a 2016–2017 date range.
  - _Requirements: 1_

- [x] 2. Weather-normalized baseline + conformal intervals
  - [x] 2.1 Write `baseline_model.py`: build features (airTemperature, hour,
    is_weekend); one scikit-learn model per good-data building; train 2016.
  - [x] 2.2 Add split conformal 90% intervals (calibration residual quantiles)
    and predict `expected, lower90, upper90` for 2017.
  - [x] 2.3 Compute CV(RMSE) on 2017; mark trustworthy if ≤ 30% (ASHRAE G14).
  - [x] 2.4 Save `predictions.csv.gz` + `model_scores.csv`.
  - _How to run:_ `python baseline_model.py` — check how many buildings are
    trustworthy; spot-check one prediction row.
  - _Requirements: 2_

- [x] 3. Waste detection, ranking, cost/CO2
  - [x] 3.1 Write `waste_detect.py`: flag excess hours (`actual > upper90`), sum
    excess kWh per trustworthy building (Method A — exceedance).
  - [x] 3.2 Add pattern metrics (Method B, all good-data buildings): setback ratio
    compared at similar temperatures + warm-day heating; flag worst quartile.
    Record which method flagged each building.
  - [x] 3.3 Convert excess kWh → dollars and CO2 using `config.py`; rank and save
    `waste_ranking.csv` with verdict per building.
  - _How to run:_ `python waste_detect.py` — open `waste_ranking.csv`; confirm
    top wasters have dollars and CO2 with units.
  - _Requirements: 3_

- [x] 4. Static HTML report (`src/report.py`)
  - [x] 4.1 Write `src/report.py` to build one self-contained `outputs/report.html`
    (Plotly embedded inline). Include headline numbers (total excess kWh, $, CO2),
    each with units, read from the computed files.
  - [x] 4.2 Add the ranked table with a verdict per building ("Wasting heat" /
    "Within expected range" / "Can't judge").
  - [x] 4.3 Add actual-vs-expected charts with the 90% band and highlighted waste
    hours for the top 5 buildings, plus a "What we can't see" section.
  - _How to run:_ `python src/report.py` — open `outputs/report.html` in a browser;
    verify headline numbers, table verdicts, top-5 bands, and the limitations
    section all render.
  - _Requirements: 4_

- [ ] 4.5 MVP checkpoint: commit and push to GitHub before any stretch work.

## Stretch (only after MVP is pushed)

- [ ] 5. Kiro chat copilot rules
  - [ ] 5.1 Create `.kiro/steering/copilot.md`: when asked about results, answer
    ONLY from `outputs/` files or by running `src/` functions; never invent
    numbers; always state the 90% range and model trust level; refuse with a
    reason for any "Can't judge" building.
  - _How to run:_ ask Kiro "which 5 buildings waste the most?" and confirm the
    answer cites the outputs and includes ranges + trust levels.
  - _Requirements: 5_

- [ ] 6. Demo questions
  - [ ] 6.1 Create `demo/questions.md` with 8 test questions and their correct
    answers taken from the `outputs/` files, each numeric answer carrying its 90%
    range and trust level.
  - _Requirements: 6_

- [ ] 7. README
  - [ ] 7.1 Write problem, data source + BDG2 citation, method, results,
    limitations ("what we can't see"), and "How I used Kiro".
  - _Requirements: 7_
