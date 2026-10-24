"""
config.py — All editable assumptions for Heat Check in ONE place.

Why this file exists:
If you want to change a price, a threshold, or an assumption, you change it HERE
and nowhere else. No need to dig through the analysis code.

Every number below has a short comment saying what it is and where it came from.
Units are written next to every value. If you only change this file, the rest of
the pipeline will pick up the new values automatically.
"""

# ---------------------------------------------------------------------------
# SITE + DATA LOCATION
# ---------------------------------------------------------------------------

# We only analyze one site for this project.
SITE_ID = "Hog"  # the campus we're studying (97 steam-metered buildings)

# Where the raw data lives. These files are NOT committed to git (see .gitignore).
DATA_DIR = "Datasets"            # folder holding the three CSV files
METADATA_FILE = "metadata.csv"    # one row per building
STEAM_FILE = "steam_cleaned.csv"  # hourly steam meter readings (wide format)
WEATHER_FILE = "weather.csv"      # hourly weather per site

# Where the pipeline writes its results (also gitignored).
PROCESSED_DIR = "data/processed"

# ---------------------------------------------------------------------------
# UNITS (for labeling everywhere)
# ---------------------------------------------------------------------------

# Steam meter readings are treated as energy in kWh per hour.
# NOTE: VERIFY this against the BDG2 data dictionary before publishing. If it
# turns out to be a different unit, change STEAM_UNIT and the conversion math is
# still driven by the constants below, so the fix stays local.
STEAM_UNIT = "kWh"          # energy per hourly reading
TEMPERATURE_UNIT = "degC"    # airTemperature is in degrees Celsius (BDG2)

# ---------------------------------------------------------------------------
# DATA QUALITY THRESHOLDS (used to flag "bad data" buildings)
# ---------------------------------------------------------------------------
# A building flagged as bad data is excluded from rankings and shown as
# "Can't judge" in the report. These thresholds are judgment calls — tune freely.

MAX_MISSING_FRACTION = 0.10    # exclude if more than 10% of hours are missing
MAX_ZERO_FRACTION = 0.50       # exclude if more than 50% of hours read exactly 0
MAX_FLATLINE_HOURS = 168       # exclude if the meter is stuck flat for 168+ hours
                               # (1 week) — likely a broken/offline sensor

# Spike check: any hourly reading above this multiple of the building's own 99th
# percentile is treated as an impossible spike (bad reading) and set to missing.
SPIKE_MULTIPLIER = 10          # 10x the 99th percentile = spike

# ---------------------------------------------------------------------------
# MODEL TRUST (ASHRAE Guideline 14)
# ---------------------------------------------------------------------------

# ASHRAE Guideline 14 hourly measurement & verification criterion: a model is
# acceptable if CV(RMSE) is 30% or less. We use this as our "trustworthy" cutoff.
# Source: ASHRAE Guideline 14-2014, hourly calibration criteria.
CVRMSE_TRUSTWORTHY_MAX = 0.30  # fraction (0.30 == 30%)

# Prediction interval coverage.
INTERVAL_COVERAGE = 0.90       # 90% split-conformal prediction interval

# Normalized-conformal floor (kWh). The band width scales with the predicted
# load; this floor stops the band from collapsing to near-zero for buildings
# that barely use steam (otherwise normal noise would escape a too-tight band).
NORMALIZE_FLOOR_KWH = 5.0

# ---------------------------------------------------------------------------
# WASTE DETECTION
# ---------------------------------------------------------------------------

WARM_DAY_TEMP_C = 18.0         # outdoor temp above this (degC) = "warm day";
                               # heating during these hours is suspicious

# Rolling-temperature feature: buildings have thermal mass, so recent average
# temperature matters, not just the current hour. We use a 24-hour rolling mean.
TEMP_ROLLING_HOURS = 24

# Academic winter break (no classes) — treated like a holiday for the model.
# Format: (month, day) for start and end, inclusive, spanning the new year.
WINTER_BREAK_START = (12, 20)  # Dec 20
WINTER_BREAK_END = (1, 10)     # Jan 10

# Occupied weekday hours (used by the setback-ratio pattern metric in stage 3).
OCCUPIED_START_HOUR = 8        # 08:00
OCCUPIED_END_HOUR = 18         # 18:00

# Pattern flagging: a building is flagged if it lands in the worst quartile.
WORST_QUARTILE = 0.75          # 75th percentile cutoff

# --- "Confirmed waste" thresholds (both must be met) ---
# By design ~5% of hours fall above the 90% upper band just by chance. We only
# call it confirmed waste when exceedance is clearly MORE than that noise floor.
CONFIRMED_MIN_EXCEED_SHARE = 0.10  # >10% of 2017 hours above the upper band
# ...and the excess must be material relative to the building's own usage.
# NOTE: excess is measured conservatively (only energy ABOVE the 90% upper band),
# so even chronic over-users rarely clear a few % of annual steam. 1.5% is tuned
# to that conservative measure — it confirms clear chronic exceeders without
# flagging trivial ones.
CONFIRMED_MIN_EXCESS_SHARE = 0.015  # counted excess >= 1.5% of 2017 steam use

# --- "Worth a look" pattern floors (worst quartile AND an absolute floor) ---
# A worst-quartile rank alone isn't enough; the behavior must be real in
# absolute terms, not just relatively worse than a very efficient campus.
SETBACK_RATIO_FLOOR = 0.70     # night/weekend use >= 70% of occupied use
WARMDAY_MIN_ANNUAL_SHARE = 0.05  # warm-day steam >= 5% of the building's annual steam

# Level-shift check. If a building's exceedance is spread fairly evenly across
# the year and the day, that looks like it simply used MORE steam all the time in
# 2017 than 2016 (a baseline shift), rather than a specific wasteful behavior. We
# relabel those "Changed since 2016" and exclude them from waste totals.
# "Spread evenly" is measured by how many months / hours carry a meaningful share
# of the excess.
LEVELSHIFT_MIN_MONTHS = 8      # excess appears in at least this many months (of 12)
LEVELSHIFT_MIN_HOURS = 16      # ...and this many hours-of-day (of 24)

# Night window for the "no night/weekend setback" pattern (local hours).
NIGHT_START_HOUR = 22          # 22:00 (10 PM)
NIGHT_END_HOUR = 5             # 05:00 (5 AM)

# Heating season months (inclusive). Steam heating is normally OFF outside these
# months, so reading 0 in summer is REAL behavior, not a broken meter. We only
# apply the "too many zeros" quality check inside the heating season.
# Oct, Nov, Dec, Jan, Feb, Mar, Apr.
HEATING_SEASON_MONTHS = [10, 11, 12, 1, 2, 3, 4]

# ---------------------------------------------------------------------------
# ECONOMIC + EMISSIONS ASSUMPTIONS (edit to match your campus)
# ---------------------------------------------------------------------------
# These turn "excess kWh" into dollars and CO2. They are ASSUMPTIONS — replace
# with your campus's real figures if you have them. Each carries a source note.

# Natural gas price. US commercial average was roughly $0.05 per kWh of gas
# energy content in recent years (derived from EIA $ per therm figures;
# 1 therm ~= 29.3 kWh). Source: U.S. EIA natural gas prices. Replace with your rate.
GAS_PRICE_PER_KWH = 0.05       # US dollars per kWh of gas input

# Boiler efficiency: how much delivered steam energy you get per unit of gas
# burned. 0.80 (80%) is a common assumption for an older campus boiler.
# Source: typical boiler efficiency range 0.75–0.85. Replace with your value.
BOILER_EFFICIENCY = 0.80       # fraction (delivered steam kWh / gas input kWh)

# CO2 emission factor for natural gas combustion. ~0.18 kg CO2 per kWh of gas.
# Source: U.S. EPA emission factors for natural gas (~53.1 kg CO2 per MMBtu).
EMISSION_FACTOR_KG_PER_KWH = 0.18  # kg CO2 per kWh of gas input
