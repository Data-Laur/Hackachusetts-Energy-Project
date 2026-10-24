"""
waste_detect.py — STAGE 3 of Heat Check.

We detect wasted heat TWO independent ways, then combine them into one ranked
table with a plain-English verdict per building.

METHOD A — Exceedance (trustworthy models only)
  For buildings whose model passed the ASHRAE trust bar, we flag every 2017 hour
  where the real meter is ABOVE the top of the 90% band. That means the building
  is using more heat than its own 2016 behavior predicts — new or worsening waste.
  We add up those excess kWh and turn them into dollars and CO2.

METHOD B — Direct pattern metrics (all good-data buildings, no model needed)
  Two physics-style checks that don't need a trustworthy model:
    1. Setback ratio: is the building heating about as hard at night/weekends as
       during occupied weekday hours? We compare at SIMILAR outdoor temperatures
       (temperature bins) so weather doesn't fool us. A ratio near 1 means little
       or no setback — wasteful.
    2. Warm-day heating: total steam used during hours warmer than 18 °C outside.
  Buildings in the worst quartile for either metric get flagged.

A building can be "Can't judge" for Method A (weak model or bad data) but still be
flagged by Method B. The output says which method flagged it.

How to run:
    python waste_detect.py

Inputs:
    data/processed/clean_long.csv.gz   (stage 1)
    data/processed/predictions.csv.gz  (stage 2)
    data/processed/model_scores.csv    (stage 2)

Output:
    data/processed/waste_ranking.csv

Units: steam/energy in kWh, money in $, emissions in kg CO2, temperature in °C.
Data source: Building Data Genome Project 2 (Miller et al., Sci Data 7, 368, 2020).
"""

import os

import numpy as np
import pandas as pd

import config


def load_inputs():
    clean = pd.read_csv(
        os.path.join(config.PROCESSED_DIR, "clean_long.csv.gz"),
        parse_dates=["timestamp"],
    )
    preds = pd.read_csv(
        os.path.join(config.PROCESSED_DIR, "predictions.csv.gz"),
        parse_dates=["timestamp"],
    )
    scores = pd.read_csv(os.path.join(config.PROCESSED_DIR, "model_scores.csv"))
    return clean, preds, scores


# --------------------------------------------------------------------------
# METHOD A — exceedance (needs a trustworthy model)
# --------------------------------------------------------------------------

def exceedance_by_building(preds):
    """
    For each building, sum the excess energy above the 90% upper band in 2017.
    Excess for an hour = actual - upper90 (only when actual > upper90).
    """
    over = preds["actual"] > preds["upper90"]
    excess = (preds["actual"] - preds["upper90"]).where(over, 0.0)
    tmp = preds.assign(excess=excess, is_excess=over.astype(int))
    grouped = tmp.groupby("building_id").agg(
        excess_kwh=("excess", "sum"),
        excess_hours=("is_excess", "sum"),
    )
    return grouped.reset_index()


def level_shift_report(preds):
    """
    Decide, per building, whether its exceedance looks like a LEVEL SHIFT (used
    more steam almost all the time in 2017) rather than specific waste.

    How: among the excess hours, count how many distinct months and how many
    distinct hours-of-day carry a meaningful share of the excess (at least 2% of
    the building's total excess each). If the excess is spread across most months
    AND most hours of the day, it's a broad baseline shift, not a pattern.

    Returns a DataFrame: building_id, n_months, n_hours, is_level_shift.
    """
    over = preds["actual"] > preds["upper90"]
    exc = preds[over].assign(
        excess=preds.loc[over, "actual"] - preds.loc[over, "upper90"]
    )
    rows = []
    for building_id, g in exc.groupby("building_id"):
        total = g["excess"].sum()
        if total <= 0:
            rows.append({"building_id": building_id, "n_months": 0,
                         "n_hours": 0, "is_level_shift": False})
            continue
        by_month = g.groupby(g["timestamp"].dt.month)["excess"].sum() / total
        by_hour = g.groupby(g["timestamp"].dt.hour)["excess"].sum() / total
        # A month/hour "counts" if it carries at least 2% of the excess.
        n_months = int((by_month >= 0.02).sum())
        n_hours = int((by_hour >= 0.02).sum())
        is_level_shift = (
            n_months >= config.LEVELSHIFT_MIN_MONTHS
            and n_hours >= config.LEVELSHIFT_MIN_HOURS
        )
        rows.append({"building_id": building_id, "n_months": n_months,
                     "n_hours": n_hours, "is_level_shift": is_level_shift})
    return pd.DataFrame(rows)


def money_and_co2(excess_kwh):
    """Convert excess kWh of delivered steam into gas cost ($) and CO2 (kg)."""
    # Delivered steam ÷ boiler efficiency = gas energy that had to be burned.
    gas_kwh = excess_kwh / config.BOILER_EFFICIENCY
    dollars = gas_kwh * config.GAS_PRICE_PER_KWH
    co2_kg = gas_kwh * config.EMISSION_FACTOR_KG_PER_KWH
    return dollars, co2_kg


# --------------------------------------------------------------------------
# METHOD B — direct pattern metrics (any good-data building)
# --------------------------------------------------------------------------

def _period_label(ts):
    """Classify each timestamp as 'night_weekend' or 'occupied' or 'other'."""
    hour = ts.dt.hour
    is_weekend = ts.dt.dayofweek >= 5
    # Night window wraps past midnight (22:00–05:00).
    is_night = (hour >= config.NIGHT_START_HOUR) | (hour < config.NIGHT_END_HOUR)
    night_weekend = is_weekend | is_night
    occupied = (~is_weekend) & (hour >= config.OCCUPIED_START_HOUR) & (
        hour < config.OCCUPIED_END_HOUR
    )
    label = np.where(night_weekend, "night_weekend",
                     np.where(occupied, "occupied", "other"))
    return label


def setback_ratio(group):
    """
    Setback ratio compared at SIMILAR outdoor temperatures.

    We bucket hours into 2 °C-wide temperature bins. Within each bin we take the
    mean steam for night/weekend hours and for occupied hours, then average the
    bin-level ratios. This removes the weather advantage night hours would
    otherwise get (nights are colder), so we're asking: at the same outside
    temperature, does the building back off at night/weekends?

    Ratio ~1.0 = no setback (wasteful). Lower = good setback.
    Returns np.nan if there isn't enough overlapping data.
    """
    g = group.dropna(subset=["steam", "airTemperature"]).copy()
    if len(g) < 500:
        return np.nan
    g["period"] = _period_label(g["timestamp"])
    g = g[g["period"].isin(["night_weekend", "occupied"])]
    # 2 °C temperature bins.
    g["tbin"] = (g["airTemperature"] / 2).round()

    ratios = []
    for _, bin_rows in g.groupby("tbin"):
        night = bin_rows.loc[bin_rows["period"] == "night_weekend", "steam"]
        occ = bin_rows.loc[bin_rows["period"] == "occupied", "steam"]
        # Need enough of both periods and a non-trivial occupied load.
        if len(night) >= 10 and len(occ) >= 10 and occ.mean() > 0:
            ratios.append(night.mean() / occ.mean())
    if not ratios:
        return np.nan
    return float(np.mean(ratios))


def warm_day_heating(group):
    """Total steam (kWh) used during hours warmer than 18 °C outside."""
    g = group.dropna(subset=["steam", "airTemperature"])
    warm = g[g["airTemperature"] > config.WARM_DAY_TEMP_C]
    return float(warm["steam"].sum())


def pattern_metrics(clean):
    """Compute both pattern metrics for every good-data building."""
    good = clean[~clean["bad_data"]]
    rows = []
    for building_id, group in good.groupby("building_id"):
        rows.append(
            {
                "building_id": building_id,
                "setback_ratio": setback_ratio(group),
                "warm_day_kwh": warm_day_heating(group),
            }
        )
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------
# Combine + verdict
# --------------------------------------------------------------------------

def build_ranking(clean, preds, scores):
    # --- Method A: exceedance for trustworthy buildings ---
    exc = exceedance_by_building(preds)
    exc = exc.merge(scores[["building_id", "cvrmse", "trustworthy"]],
                    on="building_id", how="right")
    exc["excess_kwh"] = exc["excess_kwh"].fillna(0.0)
    exc["excess_hours"] = exc["excess_hours"].fillna(0).astype(int)
    # Only trustworthy models get a real exceedance number; others are "can't judge".
    exc.loc[~exc["trustworthy"], ["excess_kwh", "excess_hours"]] = np.nan

    # --- Level-shift check: is the exceedance a broad 2016->2017 baseline shift? ---
    shift = level_shift_report(preds)
    exc = exc.merge(shift, on="building_id", how="left")
    exc["is_level_shift"] = exc["is_level_shift"].fillna(False)
    # A level shift only "counts" for a trustworthy building that actually exceeds.
    exc["is_level_shift"] = exc["is_level_shift"] & exc["trustworthy"] & (
        exc["excess_kwh"].fillna(0) > 0
    )

    # Confirmed-waste excess EXCLUDES level-shift buildings from the totals.
    exc["counted_excess_kwh"] = exc["excess_kwh"].where(~exc["is_level_shift"], 0.0)
    dollars, co2 = money_and_co2(exc["counted_excess_kwh"])
    exc["excess_dollars"] = dollars
    exc["excess_co2_kg"] = co2

    # --- Method B: pattern metrics for all good-data buildings ---
    pat = pattern_metrics(clean)
    # Worst quartile cutoffs (higher = worse for both metrics).
    setback_cut = pat["setback_ratio"].quantile(config.WORST_QUARTILE)
    warm_cut = pat["warm_day_kwh"].quantile(config.WORST_QUARTILE)
    pat["flag_no_setback"] = pat["setback_ratio"] >= setback_cut
    pat["flag_warm_day"] = pat["warm_day_kwh"] >= warm_cut

    # --- Merge the two methods on building_id ---
    out = pat.merge(exc, on="building_id", how="outer")
    out["trustworthy"] = out["trustworthy"].fillna(False)
    out["is_level_shift"] = out["is_level_shift"].fillna(False)

    def has_exceedance(r):
        """True if a trustworthy model shows real excess that is NOT a level shift."""
        return (r["trustworthy"] and pd.notna(r["excess_kwh"])
                and r["excess_kwh"] > 0 and not r["is_level_shift"])

    def has_pattern(r):
        return bool(r.get("flag_no_setback")) or bool(r.get("flag_warm_day"))

    # --- Which method(s) flagged each building? ---
    def methods_row(r):
        flags = []
        if has_exceedance(r):
            flags.append("exceedance")
        if bool(r.get("flag_no_setback")):
            flags.append("no night/weekend setback")
        if bool(r.get("flag_warm_day")):
            flags.append("heating on warm days")
        if r["is_level_shift"]:
            flags.append("level shift")
        return ", ".join(flags) if flags else "none"

    out["flagged_by"] = out.apply(methods_row, axis=1)

    # --- Verdict tiers (in priority order) ---
    def verdict_row(r):
        # 1. Confirmed waste: trustworthy exceedance that is not a level shift.
        if has_exceedance(r):
            return "Confirmed waste"
        # 2. Changed since 2016: trustworthy exceedance that is a level shift.
        if r["is_level_shift"]:
            return "Changed since 2016"
        # 3. Worth a look: no confirmed exceedance, but a pattern metric flags it.
        if has_pattern(r):
            return "Worth a look"
        # 4. Within expected range: trustworthy and nothing flagged.
        if r["trustworthy"]:
            return "Within expected range"
        # 5. Can't judge: weak model or bad data, and no pattern flag.
        return "Can't judge"

    out["verdict"] = out.apply(verdict_row, axis=1)

    # --- Rank by counted (confirmed) excess first, then warm-day kWh ---
    out["rank_key"] = out["counted_excess_kwh"].fillna(-1)
    out = out.sort_values(
        ["rank_key", "warm_day_kwh"], ascending=[False, False]
    ).drop(columns="rank_key").reset_index(drop=True)
    out.insert(0, "rank", out.index + 1)
    return out


def main():
    clean, preds, scores = load_inputs()
    ranking = build_ranking(clean, preds, scores)

    out_path = os.path.join(config.PROCESSED_DIR, "waste_ranking.csv")
    ranking.to_csv(out_path, index=False)

    # Round for a readable console preview.
    show_cols = ["rank", "building_id", "verdict", "flagged_by",
                 "excess_kwh", "excess_dollars", "excess_co2_kg",
                 "setback_ratio", "warm_day_kwh"]
    preview = ranking[show_cols].head(10).copy()
    for c in ["excess_kwh", "excess_dollars", "excess_co2_kg",
              "setback_ratio", "warm_day_kwh"]:
        preview[c] = preview[c].round(1)

    print("=" * 70)
    print("HEAT CHECK — WASTE RANKING (top 10)")
    print("=" * 70)
    print(preview.to_string(index=False))
    print("\nUnits: excess_kwh=kWh (actual - 90% upper bound, conservative), "
          "excess_dollars=$, excess_co2_kg=kg CO2, warm_day_kwh=kWh; "
          "setback_ratio unitless (1.0 = no setback).")

    print("\nCounts per verdict tier:")
    for tier, n in ranking["verdict"].value_counts().items():
        print(f"  {tier:<22} {n}")

    print(f"\nSaved ranking -> {out_path}")


if __name__ == "__main__":
    main()
