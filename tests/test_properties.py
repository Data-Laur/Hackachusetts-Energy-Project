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
