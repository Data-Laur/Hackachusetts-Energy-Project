"""
baseline_model.py — STAGE 2 of Heat Check.

What this script does, in plain words:
  For each building that passed the data-quality checks, we build a small model
  that predicts how much steam the building SHOULD use in a given hour, based on:
      - the outdoor air temperature (colder usually means more heating),
      - the hour of day (0-23),
      - whether it's a weekend (buildings often use less heat on weekends).

  We then ask: how far off is the real meter from this expectation? To do that
  honestly we also compute a 90% "prediction band" (a range we expect the real
  value to fall inside 90% of the time) using a method called split conformal
  prediction. Finally we score each model and mark it "trustworthy" only if it
  meets the ASHRAE Guideline 14 accuracy bar (CV(RMSE) <= 30%).

How the data is split (important):
  - TRAIN   : most of 2016  -> used to fit the model.
  - CALIBRATE: a slice of 2016 held out from training -> used to size the 90% band.
  - TEST    : all of 2017   -> used to score accuracy and to look for waste later.

How to run:
    python baseline_model.py

Inputs (from stage 1):
    data/processed/clean_long.csv.gz

Outputs (written to data/processed/, gitignored):
    predictions.csv.gz   -> per building per 2017 hour:
                            actual, expected, lower90, upper90
    model_scores.csv     -> per building: CV(RMSE) and a "trustworthy" flag

Units: steam in kWh, temperature in degC (see config.py).
Data source: Building Data Genome Project 2 (Miller et al., Sci Data 7, 368, 2020).
"""

import os

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

import config
from features import FEATURE_COLUMNS, add_model_features


# Floor (kWh) used by normalized conformal so the band doesn't collapse to near
# zero for buildings that barely use steam. Lives in config.py.
NORMALIZE_FLOOR = config.NORMALIZE_FLOOR_KWH


def cvrmse(actual, predicted):
    """
    CV(RMSE) = root-mean-square error divided by the mean of the actual values.

    It expresses the typical error as a fraction of the average load, so you can
    compare across buildings of very different sizes. ASHRAE Guideline 14 uses it
    as an hourly model-quality yardstick.
    """
    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    rmse = np.sqrt(np.mean((actual - predicted) ** 2))
    mean_actual = np.mean(actual)
    if mean_actual == 0:
        return np.nan  # can't form a ratio against a zero mean
    return rmse / mean_actual


def model_one_building(building_df):
    """
    Fit a model for a single building and return its 2017 predictions + score.

    Returns a tuple:
        predictions_df  (timestamp, actual, expected, lower90, upper90)  or None
        cvrmse_value    (float or nan)
    None is returned when there isn't enough data to train and test honestly.
    """
    building_df = add_model_features(building_df)

    # Split by calendar year: 2016 to learn from, 2017 to test on.
    year = building_df["timestamp"].dt.year
    train_all = building_df[year == 2016].dropna(subset=FEATURE_COLUMNS + ["steam"])
    test = building_df[year == 2017].dropna(subset=FEATURE_COLUMNS + ["steam"])

    # Need a reasonable amount of data in both years to be meaningful.
    if len(train_all) < 500 or len(test) < 500:
        return None, np.nan

    # ---- Split 2016 into TRAIN + CALIBRATION for split conformal ----
    # Instead of holding out one block of time (which could all be one season),
    # we hold out EVERY 5TH WEEK spread across all of 2016. That way the
    # calibration set sees winter, spring, summer and fall, so the 90% band is
    # sized from errors across the whole year, not just one stretch.
    week_of_year = train_all["timestamp"].dt.isocalendar().week.astype(int)
    is_calib_week = (week_of_year % 5) == 0
    train = train_all[~is_calib_week]
    calibrate = train_all[is_calib_week]
    if len(calibrate) < 100 or len(train) < 400:
        return None, np.nan

    # ---- Fit the model on TRAIN ----
    model = HistGradientBoostingRegressor(random_state=0)
    model.fit(train[FEATURE_COLUMNS], train["steam"])

    # ---- Size the 90% band on CALIBRATION (SEASONAL normalized conformal) ----
    # "Normalized" conformal divides each error by the size of the prediction
    # (floored so we never divide by ~0), so the band is NARROW at low use and
    # WIDER at high use. We later multiply back by the prediction size.
    #
    # "Seasonal" (a.k.a. Mondrian) conformal computes a SEPARATE 90% quantile for
    # the heating season (Oct–Apr) and for summer, because the model's error
    # behaves very differently between them. Each season then gets its own band
    # width, which keeps coverage near 90% in BOTH seasons instead of averaging.
    # We use a TWO-SIDED band: the real errors are skewed (2017 often runs hotter
    # than 2016), so a symmetric band can't cover 90% honestly. We compute a
    # separate lower-side and upper-side normalized quantile, per season. The
    # SIGNED normalized residual is (actual - predicted) / scale: negative means
    # the building used less than expected, positive means more.
    calib_pred = model.predict(calibrate[FEATURE_COLUMNS])
    calib_scale = np.maximum(calib_pred, NORMALIZE_FLOOR)
    calib_signed = (calibrate["steam"].to_numpy() - calib_pred) / calib_scale
    calib_months = calibrate["timestamp"].dt.month.to_numpy()
    calib_is_heating = np.isin(calib_months, config.HEATING_SEASON_MONTHS)

    # We want a 90% band, so we trim 5% off each side.
    tail = (1.0 - config.INTERVAL_COVERAGE) / 2.0  # 0.05

    def side_quantiles(signed):
        """Return (low, high) normalized quantiles for a 90% two-sided band."""
        if len(signed) < 20:
            return np.nan, np.nan
        return np.quantile(signed, tail), np.quantile(signed, 1.0 - tail)

    lo_h, hi_h = side_quantiles(calib_signed[calib_is_heating])
    lo_s, hi_s = side_quantiles(calib_signed[~calib_is_heating])
    lo_all, hi_all = side_quantiles(calib_signed)
    # Fall back to all-season if a season is too thin.
    if np.isnan(lo_h):
        lo_h, hi_h = lo_all, hi_all
    if np.isnan(lo_s):
        lo_s, hi_s = lo_all, hi_all

    # ---- Predict on TEST (2017) and attach the per-season, two-sided band ----
    expected = model.predict(test[FEATURE_COLUMNS])
    test_months = test["timestamp"].dt.month.to_numpy()
    test_is_heating = np.isin(test_months, config.HEATING_SEASON_MONTHS)
    lo_q = np.where(test_is_heating, lo_h, lo_s)
    hi_q = np.where(test_is_heating, hi_h, hi_s)
    test_scale = np.maximum(expected, NORMALIZE_FLOOR)
    lower = expected + lo_q * test_scale  # lo_q is negative -> lowers the bound
    upper = expected + hi_q * test_scale

    # Steam can't be negative, so clip the point prediction at 0 first.
    expected = np.clip(expected, 0, None)
    # A valid band must ALWAYS bracket the point prediction:
    #     lower <= expected <= upper.
    # The conformal quantiles can be one-signed (e.g. a building that usually
    # overpredicts gives a negative upper quantile), which could otherwise push
    # the upper bound below the prediction. Enforce the ordering explicitly, and
    # clip the lower bound at 0 (steam can't be negative).
    lower = np.minimum(lower, expected)
    upper = np.maximum(upper, expected)
    lower = np.clip(lower, 0, None)

    predictions = pd.DataFrame(
        {
            "timestamp": test["timestamp"].to_numpy(),
            "building_id": test["building_id"].to_numpy(),
            "actual": test["steam"].to_numpy(),
            "expected": expected,
            "lower90": lower,
            "upper90": upper,
        }
    )

    score = cvrmse(test["steam"], expected)
    return predictions, score


def main():
    clean_path = os.path.join(config.PROCESSED_DIR, "clean_long.csv.gz")
    df = pd.read_csv(clean_path, parse_dates=["timestamp"])

    # Only model buildings that passed the quality checks in stage 1.
    good = df[~df["bad_data"]]
    building_ids = sorted(good["building_id"].unique())
    print(f"Modeling {len(building_ids)} good-data buildings "
          f"(skipping {df['building_id'].nunique() - len(building_ids)} flagged).")

    all_predictions = []
    score_rows = []

    for i, building_id in enumerate(building_ids, start=1):
        building_df = good[good["building_id"] == building_id]
        predictions, score = model_one_building(building_df)

        if predictions is None:
            # Not enough data to model honestly -> treat as not trustworthy.
            score_rows.append(
                {"building_id": building_id, "cvrmse": np.nan,
                 "trustworthy": False}
            )
            continue

        # ASHRAE Guideline 14: trustworthy only if CV(RMSE) <= 30%.
        trustworthy = bool(score <= config.CVRMSE_TRUSTWORTHY_MAX) if pd.notna(score) else False
        score_rows.append(
            {"building_id": building_id, "cvrmse": round(float(score), 4),
             "trustworthy": trustworthy}
        )
        all_predictions.append(predictions)

        if i % 10 == 0:
            print(f"  ...modeled {i}/{len(building_ids)} buildings")

    # ---- Save results ----
    scores = pd.DataFrame(score_rows).sort_values("building_id").reset_index(drop=True)
    predictions_df = pd.concat(all_predictions, ignore_index=True) if all_predictions else pd.DataFrame()

    os.makedirs(config.PROCESSED_DIR, exist_ok=True)
    pred_path = os.path.join(config.PROCESSED_DIR, "predictions.csv.gz")
    scores_path = os.path.join(config.PROCESSED_DIR, "model_scores.csv")
    predictions_df.to_csv(pred_path, index=False, compression="gzip")
    scores.to_csv(scores_path, index=False)

    # ---- Summary ----
    n_trust = int(scores["trustworthy"].sum())
    valid = scores["cvrmse"].dropna()
    print("\n" + "=" * 70)
    print("HEAT CHECK — BASELINE MODEL SUMMARY")
    print("=" * 70)
    print(f"Buildings modeled        : {len(scores)}")
    print(f"Trustworthy (CV(RMSE)<= {config.CVRMSE_TRUSTWORTHY_MAX*100:.0f}%): {n_trust}")
    print(f"Not trustworthy          : {len(scores) - n_trust}")
    if len(valid):
        print(f"CV(RMSE) median          : {valid.median()*100:.1f}%")
        print(f"CV(RMSE) best / worst    : {valid.min()*100:.1f}% / {valid.max()*100:.1f}%")
    print("\nAll steam values in kWh; temperature in degC.")
    print("=" * 70)
    print(f"\nSaved predictions -> {pred_path}")
    print(f"Saved scores      -> {scores_path}")


if __name__ == "__main__":
    main()
