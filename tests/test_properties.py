"""
Property-based tests for Heat Check, using hypothesis + pytest.

Each test names the requirement it defends (see .kiro/specs/heat-check/
requirements.md). We test two kinds of properties:

  1. Invariants on the REAL computed outputs in data/processed/ (these describe
     what must always be true of the results the pipeline produced).
  2. Pure-function properties using hypothesis (random inputs) for the
     cost/CO2 conversion and the excess formula.

Run from the repo root:
    python -m pytest tests/test_properties.py -q

If the pipeline outputs are missing, the data-driven tests skip with a message
telling you to run the pipeline first.
"""

import os
import sys

import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import config  # noqa: E402
from waste_detect import money_and_co2  # noqa: E402
from src.ingest import detect_and_map, to_long_kwh  # noqa: E402
import climate as climate_mod  # noqa: E402
from waste_detect import build_ranking  # noqa: E402

PROCESSED = config.PROCESSED_DIR
RANKED_TIERS = {"Confirmed waste", "Worth a look", "Within expected range",
                "Changed since 2016", "Can't judge"}


# ----------------------- fixtures / loaders ---------------------------------

def _require(path):
    if not os.path.exists(path):
        pytest.skip(f"missing {path}; run the pipeline first "
                    "(data_pipeline.py, baseline_model.py, waste_detect.py)")
    return path


@pytest.fixture(scope="module")
def preds():
    p = _require(os.path.join(PROCESSED, "predictions.csv.gz"))
    return pd.read_csv(p, parse_dates=["timestamp"])


@pytest.fixture(scope="module")
def ranking():
    p = _require(os.path.join(PROCESSED, "waste_ranking.csv"))
    return pd.read_csv(p)


# ----------------------- Requirement 2 (bands) ------------------------------

def test_band_ordering(preds):
    """Req 2: lower90 <= expected <= upper90 for every predicted row."""
    # Small tolerance for floating point.
    tol = 1e-6
    assert (preds["lower90"] <= preds["expected"] + tol).all()
    assert (preds["expected"] <= preds["upper90"] + tol).all()


# ----------------------- Requirement 3 (excess) -----------------------------

def test_excess_never_negative_and_zero_below_band(preds):
    """
    Req 3: per-hour excess (actual - upper90, floored at 0) is never negative,
    and is exactly 0 whenever actual <= upper90.
    """
    excess = (preds["actual"] - preds["upper90"]).clip(lower=0)
    assert (excess >= 0).all()
    below = preds["actual"] <= preds["upper90"]
    assert (excess[below] == 0).all()


def test_changed_and_cantjudge_excluded_from_totals(ranking):
    """
    Req 3: 'Changed since 2016' and 'Can't judge' buildings contribute 0 to the
    counted waste totals (they are excluded from rankings/totals).
    """
    excluded = ranking[ranking["verdict"].isin(["Changed since 2016", "Can't judge"])]
    # counted_excess_kwh and the derived $ / CO2 must be 0 (or NaN->treated as 0).
    counted = excluded["counted_excess_kwh"].fillna(0)
    assert (counted == 0).all()
    assert (excluded["excess_dollars"].fillna(0) == 0).all()
    assert (excluded["excess_co2_kg"].fillna(0) == 0).all()


# ----------------------- Requirement 3 (verdict tiers) ----------------------

def test_exactly_one_verdict_per_building(ranking):
    """Req 3/4: every building has exactly one verdict, from the known set."""
    # One row per building.
    assert ranking["building_id"].is_unique
    # Every verdict is one of the five known tiers.
    assert set(ranking["verdict"].unique()).issubset(RANKED_TIERS)
    # No missing verdicts.
    assert ranking["verdict"].notna().all()


# ----------------------- Requirement 3 (metric ranges) ----------------------

def test_warmday_share_in_unit_interval(ranking):
    """Req 3: warm_day_share is a fraction of annual steam, so within [0, 1]."""
    s = ranking["warm_day_share"].dropna()
    assert (s >= 0).all() and (s <= 1 + 1e-9).all()


def test_setback_ratio_nonnegative(ranking):
    """
    Req 3: setback_ratio = night/weekend mean ÷ occupied mean at similar temps.
    It is a ratio of non-negative steam means, so it is >= 0. It is NOT bounded
    by 1 (a building with no setback can use MORE at night than when occupied),
    which is exactly why 'no setback' is flagged when the ratio is high. We
    document that here rather than asserting an upper bound of 1.
    """
    s = ranking["setback_ratio"].dropna()
    assert (s >= 0).all()
    # Sanity: ratios should be finite and not absurd.
    assert np.isfinite(s).all()


# ----------------------- Requirement 3 (cost/CO2 conversion) ----------------

@given(kwh=st.floats(min_value=0, max_value=1e9,
                     allow_nan=False, allow_infinity=False))
@settings(max_examples=200)
def test_money_and_co2_linear_and_nonnegative(kwh):
    """
    Req 3: cost and CO2 scale linearly from kWh and are never negative.
    """
    dollars, co2 = money_and_co2(kwh)
    assert dollars >= 0 and co2 >= 0
    # Linearity: double the energy -> double the cost and CO2.
    d2, c2 = money_and_co2(kwh * 2)
    assert d2 == pytest.approx(dollars * 2, rel=1e-9, abs=1e-6)
    assert c2 == pytest.approx(co2 * 2, rel=1e-9, abs=1e-6)


@given(kwh=st.floats(min_value=1e-3, max_value=1e9,
                     allow_nan=False, allow_infinity=False))
@settings(max_examples=200)
def test_money_and_co2_roundtrip(kwh):
    """
    Req 3: the conversion is invertible — from dollars we can recover the kWh
    (and from kWh recover CO2) using the documented config constants. This
    confirms the formulas are consistent and unit-correct.
    """
    dollars, co2 = money_and_co2(kwh)
    # Recover gas kWh from dollars, then delivered kWh, and compare.
    gas_kwh_from_dollars = dollars / config.GAS_PRICE_PER_KWH
    delivered_from_dollars = gas_kwh_from_dollars * config.BOILER_EFFICIENCY
    assert delivered_from_dollars == pytest.approx(kwh, rel=1e-9)
    # CO2 and dollars describe the same gas burn, so their ratio is constant.
    ratio = co2 / dollars
    expected_ratio = (config.EMISSION_FACTOR_KG_PER_KWH / config.GAS_PRICE_PER_KWH)
    assert ratio == pytest.approx(expected_ratio, rel=1e-9)


@given(
    actual=st.floats(min_value=0, max_value=1e7, allow_nan=False, allow_infinity=False),
    upper=st.floats(min_value=0, max_value=1e7, allow_nan=False, allow_infinity=False),
)
@settings(max_examples=200)
def test_excess_formula_properties(actual, upper):
    """
    Req 3: the hourly excess formula max(actual - upper, 0) is non-negative and
    is zero exactly when actual <= upper — for any inputs, not just real data.
    """
    excess = max(actual - upper, 0.0)
    assert excess >= 0
    if actual <= upper:
        assert excess == 0
    else:
        assert excess == pytest.approx(actual - upper)


# ----------------------- Requirement 3 (warm-day uses Celsius) --------------

def _f_to_c(f):
    return (f - 32) * 5.0 / 9.0


@given(
    temps_f=st.lists(
        st.floats(min_value=-40, max_value=120, allow_nan=False, allow_infinity=False),
        min_size=3, max_size=30,
    )
)
@settings(max_examples=150)
def test_warmday_threshold_applied_to_celsius(temps_f):
    """
    Req 3: the 18 C warm-day threshold must be applied to CELSIUS values.

    We feed the ingester a Fahrenheit temperature column (name 'Outdoor Temp (F)')
    and check that:
      1. it detects Fahrenheit and converts to Celsius (F -> C BEFORE any
         threshold), and
      2. the warm-day flag computed from the ingester's airTemperature matches
         the flag computed from the correct Celsius conversion — NOT from the raw
         Fahrenheit numbers (which would wrongly call ~64 F a 'warm day' because
         64 > 18).
    """
    n = len(temps_f)
    times = pd.date_range("2017-01-01", periods=n, freq="h").strftime("%Y-%m-%d %H:%M")
    df = pd.DataFrame({
        "Date/Time": times,
        "Bldg Name": ["B"] * n,
        "Steam (kWh)": [100.0] * n,
        "Outdoor Temp (F)": temps_f,
    })
    mapping = detect_and_map(df)
    assert mapping["temp_col"] == "Outdoor Temp (F)"
    assert mapping["temp_is_f"] is True  # detected as Fahrenheit

    long = to_long_kwh(df, mapping, "unit_test.csv")
    got_c = long["airTemperature"].to_numpy()
    expected_c = np.array([_f_to_c(f) for f in temps_f])
    # Conversion is correct (the ingester rounds airTemperature to 2 decimals,
    # so compare at that tolerance; clearly NOT the identity for F != C).
    assert np.allclose(got_c, expected_c, atol=0.01)

    thr = config.WARM_DAY_TEMP_C
    # Compare warm-day flags using the ingester's (rounded) Celsius values vs the
    # raw Fahrenheit numbers. The flag must reflect Celsius, never raw Fahrenheit.
    warm_from_ingester = got_c > thr
    warm_from_raw_fahrenheit = np.array(temps_f) > thr
    # Where true-Celsius and raw-Fahrenheit disagree (temps between 18 C = 64.4 F
    # and 18 F), the ingester must side with Celsius — i.e. it must NOT equal the
    # raw-Fahrenheit comparison.
    warm_from_true_celsius = expected_c > thr
    disagree = warm_from_true_celsius != warm_from_raw_fahrenheit
    if disagree.any():
        assert not np.array_equal(warm_from_ingester, warm_from_raw_fahrenheit)
        # And on the disagreeing positions, the ingester matches Celsius truth.
        assert np.array_equal(warm_from_ingester[disagree],
                              warm_from_true_celsius[disagree])


# ----------------------- Requirement 3 (warm climate -> no warm-day flag) ---

def _synthetic_site(mean_temp_c, n_buildings=4, hours=24 * 120):
    """
    Build minimal (clean, preds, scores) frames for a site whose outdoor
    temperature averages mean_temp_c over the (heating-season) window, with
    heavy warm-day steam so warm-day WOULD flag if the climate gate were off.
    """
    start = pd.Timestamp("2017-01-01")
    ts = pd.date_range(start, periods=hours, freq="h")
    # Flat temperature at mean_temp_c keeps the heating-season mean exact.
    clean_rows, pred_rows, score_rows = [], [], []
    rng = np.random.default_rng(0)
    for i in range(n_buildings):
        bid = f"B{i}"
        steam = rng.uniform(50, 150, size=hours)  # always-on steam, even when warm
        clean_rows.append(pd.DataFrame({
            "timestamp": ts, "building_id": bid, "steam": steam,
            "airTemperature": float(mean_temp_c), "bad_data": False,
        }))
        # Minimal predictions (not trustworthy -> exceedance path stays empty).
        pred_rows.append(pd.DataFrame({
            "timestamp": ts, "building_id": bid,
            "actual": steam, "expected": steam,
            "lower90": steam - 1, "upper90": steam + 1,
        }))
        score_rows.append({"building_id": bid, "cvrmse": 0.5, "trustworthy": False})
    clean = pd.concat(clean_rows, ignore_index=True)
    preds = pd.concat(pred_rows, ignore_index=True)
    scores = pd.DataFrame(score_rows)
    return clean, preds, scores


@given(mean_temp_c=st.floats(min_value=config.CLIMATE_WARM_CUTOFF_C + 0.5,
                             max_value=35.0, allow_nan=False))
@settings(max_examples=25, deadline=None)
def test_warm_climate_never_gets_warmday_flag(mean_temp_c):
    """
    Req 3 (climate-aware): a site classified as WARM must never receive a
    warm-day waste flag, regardless of how much warm-day steam it uses — in warm
    climates steam may serve hot water, reheat, or cooling.
    """
    # Sanity: this mean really classifies as warm.
    assert climate_mod.climate_flag(mean_temp_c) == "warm"
    clean, preds, scores = _synthetic_site(mean_temp_c)
    ranking = build_ranking(clean, preds, scores)
    assert not ranking["flag_warm_day"].any()
    # And no building is flagged "heating on warm days" in flagged_by.
    assert not ranking["flagged_by"].str.contains("warm day", case=False).any()
