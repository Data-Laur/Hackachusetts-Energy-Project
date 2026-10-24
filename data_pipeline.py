"""
data_pipeline.py — STAGE 1 of Heat Check.

What this script does, in plain words:
  1. Loads the three raw data files (building info, steam readings, weather).
  2. Keeps only the one site we care about (Hog) and only buildings that have a
     steam meter.
  3. Reshapes the steam data from "wide" (one column per building) into "long"
     (one row per building per hour) so it's easy to work with.
  4. Joins the weather onto each row by matching site + timestamp.
  5. Checks the quality of each building's data and flags the bad ones.
  6. Prints a human-readable summary and saves two result files for later stages.

How to run:
    python data_pipeline.py

Outputs (written to data/processed/, which is gitignored):
    clean_long.csv.gz    -> the tidy table every later stage reads (gzipped CSV)
    quality_report.csv   -> per-building data-quality scores + bad-data flag

Data source: Building Data Genome Project 2 (BDG2).
  Miller, C., Kathirgamanathan, A., Picchetti, B. et al. Sci Data 7, 368 (2020).
  https://doi.org/10.1038/s41597-020-00712-x
"""

import os

import pandas as pd

import config  # all our settings and thresholds live here


def load_metadata():
    """Load building metadata and keep only Hog buildings that have steam."""
    path = os.path.join(config.DATA_DIR, config.METADATA_FILE)
    meta = pd.read_csv(path)

    # Keep only our site, and only buildings whose steam flag says "Yes".
    is_our_site = meta["site_id"] == config.SITE_ID
    has_steam = meta["steam"] == "Yes"
    meta = meta[is_our_site & has_steam].copy()

    print(f"Metadata: {len(meta)} buildings at site '{config.SITE_ID}' with steam.")
    return meta


def load_steam_long(building_ids):
    """
    Load the wide steam file and reshape it to long format.

    Wide format looks like:
        timestamp, Bldg_A, Bldg_B, Bldg_C, ...
    Long format (what we want) looks like:
        timestamp, building_id, steam
    """
    path = os.path.join(config.DATA_DIR, config.STEAM_FILE)
    steam_wide = pd.read_csv(path, parse_dates=["timestamp"])

    # Only keep the timestamp plus the columns for our 97 buildings. Some
    # buildings in metadata might not have a matching column, so intersect.
    available = [b for b in building_ids if b in steam_wide.columns]
    missing = [b for b in building_ids if b not in steam_wide.columns]
    if missing:
        print(f"Note: {len(missing)} buildings had no steam column and were skipped.")

    steam_wide = steam_wide[["timestamp"] + available]

    # "Melt" turns the many building columns into two columns: name + value.
    steam_long = steam_wide.melt(
        id_vars="timestamp",
        var_name="building_id",
        value_name="steam",  # steam energy in kWh (see config.STEAM_UNIT)
    )
    print(f"Steam: reshaped to long format with {len(steam_long):,} rows.")
    return steam_long


def load_weather():
    """Load weather and keep only our site's rows."""
    path = os.path.join(config.DATA_DIR, config.WEATHER_FILE)
    weather = pd.read_csv(path, parse_dates=["timestamp"])
    weather = weather[weather["site_id"] == config.SITE_ID].copy()
    print(f"Weather: {len(weather):,} hourly rows for site '{config.SITE_ID}'.")
    return weather


def remove_spikes(df):
    """
    Find and remove impossible spikes, per building.

    A spike is any reading above SPIKE_MULTIPLIER times that building's own 99th
    percentile. These are almost always meter glitches (e.g. a reading 50x normal
    for a single hour). We set those readings to missing (NaN) so they don't
    distort the models, and we count how many we removed per building.

    Returns:
        df              with spikes set to NaN in the 'steam' column
        spike_counts    dict of building_id -> number of spikes removed
    """
    df = df.copy()
    spike_counts = {}
    for building_id, group in df.groupby("building_id"):
        steam = group["steam"]
        # 99th percentile of the real (non-missing) readings for this building.
        p99 = steam.quantile(0.99)
        if pd.isna(p99) or p99 <= 0:
            spike_counts[building_id] = 0
            continue
        threshold = config.SPIKE_MULTIPLIER * p99
        is_spike = steam > threshold
        spike_counts[building_id] = int(is_spike.sum())
        # Set the spike readings to missing in the main table.
        df.loc[group.index[is_spike.to_numpy()], "steam"] = float("nan")
    return df, spike_counts


def longest_flatline(values):
    """
    Return the length (in hours) of the longest run where the meter is stuck at
    the same NON-ZERO value.

    Why we ignore zeros: a steam meter legitimately reads 0 for long stretches in
    summer when heating is off. That is real behavior, not a broken sensor. So a
    long run of zeros does NOT count as a flatline. Only a long run of the same
    non-zero reading suggests the meter is stuck.
    """
    longest = 0
    current = 0
    previous = object()  # a value nothing will equal on the first comparison
    for v in values:
        # A run only counts if the value repeats AND it is a real (non-zero)
        # reading. Missing values (NaN) and zeros break/skip the run.
        if pd.notna(v) and v != 0 and v == previous:
            current += 1
        else:
            # Start a fresh potential run only from a real non-zero reading.
            current = 1 if (pd.notna(v) and v != 0) else 0
            previous = v
        if current > longest:
            longest = current
    return longest


def build_quality_report(df, spike_counts):
    """
    For each building, measure data quality and decide if it is "bad data".

    We measure:
      - % missing (blank readings)
      - % zeros (exactly 0, which can mean "off" or a dead meter)
      - longest flatline run in hours (a stuck meter)
    Then we flag a building as bad if it crosses any threshold in config.py.
    """
    rows = []
    for building_id, group in df.groupby("building_id"):
        steam = group["steam"]
        total = len(steam)

        # % missing is measured over the whole year.
        pct_missing = steam.isna().mean() if total else 1.0

        # % zeros is measured ONLY during the heating season (Oct–Apr), because
        # reading 0 in summer is normal "heating off" behavior, not bad data.
        months = group["timestamp"].dt.month
        in_season = months.isin(config.HEATING_SEASON_MONTHS)
        season_steam = steam[in_season]
        if len(season_steam):
            pct_zeros = (season_steam == 0).mean()
        else:
            pct_zeros = 0.0  # no heating-season data to judge

        # Flatline ignores zero runs (see longest_flatline docstring).
        flat_hours = longest_flatline(steam.tolist())

        # A building is "bad data" if it fails ANY of the quality checks.
        bad_data = (
            pct_missing > config.MAX_MISSING_FRACTION
            or pct_zeros > config.MAX_ZERO_FRACTION
            or flat_hours > config.MAX_FLATLINE_HOURS
        )

        rows.append(
            {
                "building_id": building_id,
                "pct_missing": round(pct_missing * 100, 1),       # whole-year %
                "pct_zeros_heating": round(pct_zeros * 100, 1),   # heating-season %
                "longest_flatline_hours": flat_hours,             # non-zero runs
                "spikes_removed": spike_counts.get(building_id, 0),
                "bad_data": bad_data,
            }
        )

    return pd.DataFrame(rows).sort_values("building_id").reset_index(drop=True)


def print_summary(meta, df, quality):
    """Print a readable summary of what we loaded and found."""
    print("\n" + "=" * 70)
    print("HEAT CHECK — DATA PIPELINE SUMMARY")
    print("=" * 70)

    # Building count by primary space usage (what the building is used for).
    print("\nBuildings by primary space usage:")
    counts = meta["primaryspaceusage"].value_counts()
    for usage, n in counts.items():
        print(f"  {usage:<35} {n}")

    # Date range of the data.
    print("\nDate range:")
    print(f"  {df['timestamp'].min()}  ->  {df['timestamp'].max()}")

    # Data quality overview.
    n_bad = int(quality["bad_data"].sum())
    n_good = len(quality) - n_bad
    print("\nData quality:")
    print(f"  {n_good} buildings OK, {n_bad} flagged as bad data (excluded from "
          f"rankings).")
    print(f"  (Thresholds: missing>{config.MAX_MISSING_FRACTION*100:.0f}%, "
          f"heating-season zeros>{config.MAX_ZERO_FRACTION*100:.0f}%, "
          f"non-zero flatline>{config.MAX_FLATLINE_HOURS}h)")

    if n_bad:
        print("\n  Buildings flagged as bad data:")
        bad = quality[quality["bad_data"]]
        for _, r in bad.iterrows():
            print(f"    {r['building_id']:<35} "
                  f"missing={r['pct_missing']}%  "
                  f"zeros(heating)={r['pct_zeros_heating']}%  "
                  f"flat={r['longest_flatline_hours']}h")

    print("\nAll steam values are in "
          f"{config.STEAM_UNIT}; temperature in {config.TEMPERATURE_UNIT}.")
    print("=" * 70 + "\n")


def main():
    # --- Load the three files -------------------------------------------------
    meta = load_metadata()
    building_ids = meta["building_id"].tolist()
    steam_long = load_steam_long(building_ids)
    weather = load_weather()

    # --- Join weather onto every steam row ------------------------------------
    # Each building belongs to a site; we attach that site, then join weather by
    # matching site_id + timestamp.
    site_lookup = meta[["building_id", "site_id"]]
    df = steam_long.merge(site_lookup, on="building_id", how="left")
    df = df.merge(weather, on=["site_id", "timestamp"], how="left")

    # --- Remove impossible spikes (set them to missing) -----------------------
    df, spike_counts = remove_spikes(df)
    total_spikes = sum(spike_counts.values())
    print(f"Spikes removed (> {config.SPIKE_MULTIPLIER}x the 99th percentile): "
          f"{total_spikes} readings set to missing.")

    # --- Quality report + bad-data flag ---------------------------------------
    quality = build_quality_report(df, spike_counts)

    # Attach the bad-data flag back onto the main table so later stages can use it.
    df = df.merge(quality[["building_id", "bad_data"]], on="building_id", how="left")

    # --- Save results ---------------------------------------------------------
    os.makedirs(config.PROCESSED_DIR, exist_ok=True)
    # We save as gzipped CSV (not parquet) so there's no extra dependency to
    # install and you can unzip + open the file to inspect it if you want.
    clean_path = os.path.join(config.PROCESSED_DIR, "clean_long.csv.gz")
    quality_path = os.path.join(config.PROCESSED_DIR, "quality_report.csv")
    df.to_csv(clean_path, index=False, compression="gzip")
    quality.to_csv(quality_path, index=False)

    # --- Print the human-readable summary -------------------------------------
    print_summary(meta, df, quality)
    print(f"Saved tidy data   -> {clean_path}")
    print(f"Saved quality CSV -> {quality_path}")


if __name__ == "__main__":
    main()
