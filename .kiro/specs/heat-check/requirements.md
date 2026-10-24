# Requirements — Heat Check

## Introduction

**Heat Check** is a campus heating copilot. It finds where buildings waste heat,
proves it with calibrated uncertainty (prediction intervals), and **refuses to
answer when the evidence is weak** (bad data or an untrustworthy model).

This is a one-day hackathon build. Code must stay simple, well commented, and
runnable step by step by someone who vibe-codes and doesn't normally write code.

### Scope
- One site only: `site_id = "Hog"` (97 steam-metered buildings).
- Data source: Building Data Genome Project 2 (BDG2),
  https://github.com/buds-lab/building-data-genome-project-2
  - Citation: Miller, C., Kathirgamanathan, A., Picchetti, B. et al. *The Building
    Data Genome Project 2, energy meter data from the ASHRAE Great Energy
    Predictor III competition.* Sci Data 7, 368 (2020).
    https://doi.org/10.1038/s41597-020-00712-x
- Data lives in `./Datasets/` and must **never** be committed (gitignored).

### Units (label everywhere in UI and output)
- `airTemperature`: degrees Celsius (°C).
- Steam meter readings: energy in **kWh per hour** (hourly). NOTE: verify against
  the BDG2 data dictionary before presenting as fact; conversions live in one
  editable config file so a unit fix is a one-line change.
- Timestamps: hourly, local to the site.

## Requirements

### Requirement 1 — Data pipeline
**User story:** As an analyst, I want the three raw files loaded, filtered to the
Hog site, and reshaped into one tidy table, so that every later step has clean,
consistent input.

#### Acceptance Criteria
1. WHEN the pipeline runs THEN it SHALL load `Datasets/metadata.csv`,
   `Datasets/steam_cleaned.csv`, and `Datasets/weather.csv`.
2. WHEN loading THEN it SHALL filter to `site_id = "Hog"` and keep only buildings
   whose metadata marks steam = "Yes".
3. WHEN reshaping THEN it SHALL convert steam from wide (one column per building)
   to long format with columns `timestamp, building_id, steam`.
4. WHEN joining THEN it SHALL join weather on `site_id + timestamp`.
5. WHEN the pipeline finishes THEN it SHALL print a summary: building count by
   `primaryspaceusage`, the overall date range, and a per-building data quality
   report (% missing, % zeros, longest flatline run).
6. WHEN a building has bad data (configurable thresholds for missing/zeros/
   flatlines) THEN it SHALL be flagged and excluded from later rankings.

### Requirement 2 — Weather-normalized baseline + calibrated uncertainty
**User story:** As an analyst, I want an expected hourly steam value per building
with a 90% interval and a trust label, so that I only act on buildings whose
model is good enough.

#### Acceptance Criteria
1. WHEN modeling a building THEN it SHALL predict expected hourly steam from
   outdoor temperature, hour of day, and weekday-vs-weekend.
2. WHEN training THEN it SHALL train on 2016 data and test on 2017 data.
3. WHEN producing intervals THEN it SHALL use split conformal prediction to make
   90% prediction intervals.
4. WHEN evaluating THEN it SHALL compute CV(RMSE) per building on the test year.
5. WHEN CV(RMSE) ≤ 30% (ASHRAE Guideline 14 hourly criterion) THEN the model
   SHALL be marked "trustworthy"; otherwise "not trustworthy".
6. WHEN a model is not trustworthy THEN that building SHALL NOT appear in waste
   rankings and SHALL surface as "Can't judge" in the app.

### Requirement 3 — Waste detection, ranking, and cost/CO2
**User story:** As an analyst, I want wasted-heat hours detected, labeled, ranked,
and translated into dollars and CO2, so that results are actionable.

#### Acceptance Criteria
1. WHEN actual steam exceeds the upper 90% interval bound for an hour THEN that
   hour SHALL be flagged as excess (waste).
2. WHEN labeling patterns THEN it SHALL identify "heating on warm days" (outdoor
   temp > 18 °C with excess) and "no night/weekend setback" (excess concentrated
   in nights/weekends).
3. WHEN ranking THEN it SHALL rank only trustworthy buildings by total excess
   energy (kWh).
4. WHEN converting THEN it SHALL translate excess kWh into dollars and CO2 using a
   single editable config file holding gas price, boiler efficiency, and emission
   factor, each with a source comment.

### Requirement 4 — Static HTML report (MVP demo surface)
**User story:** As a judge or facilities user, I want a single self-contained HTML
report I can open in a browser, so that I can see and trust the findings with no
server or app to run.

#### Acceptance Criteria
1. WHEN `src/report.py` runs THEN it SHALL generate one self-contained
   `outputs/report.html` (Plotly charts embedded in the HTML, no external files).
2. WHEN the report renders THEN it SHALL show headline numbers (e.g. total excess
   kWh, dollars, CO2 across trustworthy buildings), each with its unit.
3. WHEN the report renders THEN it SHALL show a ranked table with a verdict per
   building: "Wasting heat", "Within expected range", or "Can't judge (weak model
   or bad data)".
4. WHEN the report renders THEN it SHALL show actual-vs-expected steam charts with
   the 90% band for the top 5 buildings.
5. WHEN the report renders THEN it SHALL include a "What we can't see" section
   stating the method's limitations.
6. WHEN any number is shown THEN it SHALL come from computed results (never a
   hardcoded figure) and SHALL display its unit.

### Requirement 5 — Kiro chat as grounded copilot (STRETCH)
**User story:** As a user, I want to ask plain-English questions in Kiro chat and
get answers grounded only in computed results.

#### Acceptance Criteria
1. WHEN I ask a question about results THEN Kiro SHALL answer ONLY from files in
   `outputs/` or by running functions in `src/` — never invented numbers. This is
   enforced by `.kiro/steering/copilot.md`.
2. WHEN giving a figure THEN Kiro SHALL state the 90% range and the model trust
   level.
3. WHEN a building is "Can't judge" THEN Kiro SHALL refuse and give the reason.

### Requirement 6 — Demo questions (STRETCH)
**User story:** As a builder, I want a fixed set of questions with known answers to
demo and sanity-check the grounded copilot.

#### Acceptance Criteria
1. WHEN preparing the demo THEN `demo/questions.md` SHALL contain 8 test questions
   with their correct answers derived from the `outputs/` files.
2. WHEN an answer involves a building figure THEN it SHALL include the 90% range
   and trust level, matching what the copilot rules require.

### Requirement 7 — README (STRETCH)
**User story:** As a reader, I want a clear writeup.

#### Acceptance Criteria
1. WHEN written THEN the README SHALL cover: problem, data source + citation,
   method, results, limitations ("what we can't see"), and a "How I used Kiro"
   section.
