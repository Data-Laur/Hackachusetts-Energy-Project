# Heat Check

**Find which buildings waste heat, and what to fix first.**

[![CI](https://github.com/Data-Laur/Hackachusetts-Energy-Project/actions/workflows/ci.yml/badge.svg)](https://github.com/Data-Laur/Hackachusetts-Energy-Project/actions/workflows/ci.yml)

A campus heating copilot that finds where buildings waste heat, proves it with
calibrated uncertainty, and refuses to answer when the evidence is weak.

**Live demo:** https://data-laur.github.io/Hackachusetts-Energy-Project/

---

## The problem (and why it matters)

- Building heating is one of the largest sources of campus greenhouse-gas
  emissions.
- Universities are setting climate targets and need to act on their **biggest
  emitters first** — but it's hard to tell real waste from normal variation.
- Facilities teams are stretched; they need a short, trustworthy list of where to
  look and what to try, not another dashboard of raw meters.

## What Heat Check does

- Learns each building's **expected** hourly steam use from weather and schedule.
- Flags hours that run **above** a calibrated 90% band as excess, and converts it
  to dollars and CO2.
- Sorts buildings into clear verdict tiers and suggests a likely fix.
- **Refuses to guess** when a building's model isn't trustworthy or its data is
  poor ("Can't judge").
- Ships one self-contained, interactive HTML report — no server to run.

## How to run

```bash
# 1. Set up
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. Download the data (Building Data Genome 2) into Datasets/
python scripts/download_data.py

# 3. Run the pipeline (one command per stage)
python data_pipeline.py      # load, clean, quality-check (site "Hog")
python baseline_model.py     # weather-normalized baseline + 90% conformal bands
python waste_detect.py        # exceedance + pattern checks, ranking, $/CO2

# 4. Build the report -> docs/index.html
python src/report.py
```

Open `docs/index.html` in a browser (or view the live demo above).

## Try your own data

Heat Check can ingest a dropped-in meter file:

- Sample files live in `samples/` (long/wide formats, MMBtu/kWh, with weather).
- Drop a CSV into `inbox/` (an agent hook runs the ingester), or run it directly:

```bash
python src/ingest.py samples/sample_A_long_mmbtu.csv
```

It detects the format, maps columns to `timestamp, building_id, steam_kwh`,
converts units (and °F → °C), writes `inbox/mapping_report.md`, and **stops to
ask** if anything is ambiguous (e.g. a value column with no unit). Results go to
`inbox/results/`.

## Method

- **Baseline model:** one scikit-learn model per building predicts expected hourly
  steam from outdoor temperature (plus a 24-hour rolling mean), hour of day,
  weekend, month, and holiday/break. Trained on 2016, tested on 2017.
- **Calibrated uncertainty:** split **conformal** prediction gives a 90% band,
  calibrated separately by season and on each side (errors are skewed).
- **Trust gate:** a model is used only if it meets **ASHRAE Guideline 14**
  (CV(RMSE) ≤ 30%); otherwise the building is "Can't judge".
- **Verdict tiers:** Confirmed waste · Worth a look · Within expected range ·
  Changed since 2016 · Can't judge. Excess is measured **conservatively** as
  energy above the 90% upper bound.
- **Climate-aware:** warm-day flags only apply to cold-climate sites; in warm
  climates steam may serve hot water, reheat, or cooling.

## Results (headline)

For the Hog site (Minneapolis area), across **10 Confirmed-waste** buildings:

- **~2,551,077 kWh/yr** excess steam (conservative — above the 90% upper bound)
- **~$159,442/yr** and **~575,587 kg CO2/yr**
- Top single building: **Hog_education_Caridad** — ~1,063,584 kWh ≈ $66,474 /
  239,971 kg CO2.

Tiers: 10 Confirmed waste · 28 Worth a look · 8 Within expected range ·
7 Changed since 2016 · 25 Can't judge.

## What we can't see

See [`docs/what-we-cant-see.md`](docs/what-we-cant-see.md). In short:

- 2017 covers 80.7% of hours vs 89.5% in-distribution — real year-over-year drift,
  not miscalibration (we don't widen bands to hide it).
- The level-shift rule can miss changes that start partway through a year.
- Steam meters only, one site; no electricity, occupancy, or sub-metering.
- Warm-day flags are most reliable for heating-only steam in cold climates.
- Cost/CO2 use editable assumptions in `config.py`.

## Data

Building Data Genome Project 2 (BDG2).
<https://github.com/buds-lab/building-data-genome-project-2>

> Miller, C., Kathirgamanathan, A., Picchetti, B. et al. The Building Data Genome
> Project 2, energy meter data from the ASHRAE Great Energy Predictor III
> competition. *Sci Data* 7, 368 (2020).
> <https://doi.org/10.1038/s41597-020-00712-x>

Scope: site "Hog", steam meters only. Models trained on 2016; results shown for
2017. Steam in kWh, temperature in °C. Raw data is not committed (see
`.gitignore`).

## MCP setup (fetch server)

```bash
mkdir -p .kiro/settings
cp docs/mcp.example.json .kiro/settings/mcp.json
```

On macOS, if the fetch server fails to connect, replace `uvx` with the full path
from `which uvx` in `.kiro/settings/mcp.json`. The local `mcp.json` is gitignored.

## How I used Kiro

Full build log: [`docs/kiro-log.md`](docs/kiro-log.md). Highlights:

- **Specs.** Built the whole thing from a spec (requirements → design → tasks),
  reordered so an MVP (tasks 1–4) came first and stood alone.
- **Steering.** Project rules (beginner-friendly code, cite sources, label units)
  plus a **manual-inclusion** copilot steering file — manual because its
  answer-only-from-outputs rules apply when asking about results, not to every
  coding turn.
- **Agent hooks.** (1) An `inbox/` hook that ingests any dropped CSV; (2) a hook
  that appends a log row when a spec task is marked complete.
- **MCP.** Used the fetch server to verify assumptions against primary sources.
  It respects robots.txt (so an EIA `/archive/` page was refused — an honest
  finding), and the current EIA page gave the natural-gas factor **52.91
  kg CO2/MMBtu** (→ 0.1805 kg/kWh), which corrected the config.
- **Property-based testing (hypothesis).** Each property ties to a requirement.
  It caught a real **band-ordering bug** (expected > upper90 on ~6k rows from a
  one-sided conformal quantile) that a hand-picked unit test would likely have
  missed, plus a warm-climate edge case that exposed an empty-frame merge bug.
- **Human-in-the-loop catches.** The user caught inflated "Wasting heat" counts
  (led to the five tiers and a level-shift rule), a too-high warm-day share (led
  to the climate-aware gate), and drove the real-data samples and branding.
