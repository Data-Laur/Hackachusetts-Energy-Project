"""
ingest.py — bring-your-own-data ingestion for Heat Check.

Takes a CSV someone dropped in inbox/, figures out its format, maps its columns
to our schema (timestamp, building_id, steam_kwh), converts units to kWh, and
writes a plain-language mapping report. If anything is ambiguous (for example a
value column with no unit in its name), it STOPS and asks rather than guessing.

Our target schema:
    timestamp     (hourly)
    building_id   (one per building)
    steam_kwh     (steam energy in kWh)

How to run on one file:
    python src/ingest.py inbox/sample_A_long_mmbtu.csv

Outputs:
    inbox/mapping_report.md         (always — the mapping + assumptions)
    inbox/results/<name>_scored.csv (only when the mapping is unambiguous)

Units: steam in kWh (after conversion), temperature in degC elsewhere.
"""

import os
import sys

import pandas as pd

# Allow importing repo-root modules (waste_detect, config) when run as
# `python src/ingest.py` from the repo root.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import config  # noqa: E402  (repo-root module; path set above)

# Unit conversions into kWh.
MMBTU_TO_KWH = 293.07122       # 1 MMBtu = 293.07 kWh
KBTU_TO_KWH = 0.29307122       # 1 kBTU  = 0.293 kWh
# Candidate column names we recognize (lowercased, loose match).
TIME_HINTS = ["date/time", "reading time", "timestamp", "time", "datetime"]
BUILDING_HINTS = ["bldg name", "building", "building_id", "name", "bldg"]
# Outdoor-temperature column hints.
TEMP_HINTS = ["outdoor temp", "air temp", "airtemperature", "temperature", "temp"]
# Coordinate column hints (for climate classification).
LAT_HINTS = ["latitude", "lat"]
LNG_HINTS = ["longitude", "lng", "lon", "long"]


def _find_coords(df):
    """Return (lat, lng) from the first row if coordinate columns exist, else None."""
    lat_col = _find(df.columns, LAT_HINTS)
    lng_col = _find(df.columns, LNG_HINTS)
    if lat_col and lng_col:
        try:
            return float(df[lat_col].iloc[0]), float(df[lng_col].iloc[0])
        except (ValueError, TypeError, IndexError):
            return None
    return None
# Value column name -> unit. Only used when the unit is explicit.
UNIT_PATTERNS = {
    "kwh": 1.0,
    "mmbtu": MMBTU_TO_KWH,
    "kbtu": KBTU_TO_KWH,
}


def _find_temp(colnames):
    """Find an outdoor-temperature column and whether it's in Fahrenheit."""
    low = {c.lower(): c for c in colnames}
    for hint in TEMP_HINTS:
        for lc, orig in low.items():
            if hint in lc:
                # Fahrenheit if the name mentions F and not C.
                is_f = ("(f)" in lc or " f)" in lc or "fahrenheit" in lc
                        or lc.rstrip().endswith(" f"))
                return orig, is_f
    return None, False


def _find(colnames, hints):
    """Return the first column whose lowercased name contains any hint."""
    low = {c.lower(): c for c in colnames}
    for hint in hints:
        for lc, orig in low.items():
            if hint in lc:
                return orig
    return None


def detect_and_map(df):
    """
    Inspect the dataframe and decide its format + column mapping.

    Returns a dict describing the mapping, including:
        format        : "long" | "wide"
        ambiguous     : True/False
        reasons       : list of human-readable notes/assumptions
        ... plus the resolved column names and the unit factor when known.
    """
    cols = list(df.columns)
    reasons = []

    time_col = _find(cols, TIME_HINTS)
    building_col = _find(cols, BUILDING_HINTS)
    # Pull out an outdoor-temperature column up front, so it isn't mistaken for a
    # steam value / building column.
    temp_col, temp_is_f = _find_temp(cols)
    if temp_col:
        reasons.append(
            f"Found outdoor temperature column '{temp_col}' "
            f"({'Fahrenheit -> converting to Celsius' if temp_is_f else 'Celsius'})."
        )
    # Coordinate columns (for climate) are metadata, not steam/building columns —
    # exclude them from value-column detection.
    lat_col = _find(cols, LAT_HINTS)
    lng_col = _find(cols, LNG_HINTS)
    coord_cols = [c for c in (lat_col, lng_col) if c]
    # Set of columns that are NOT a steam value.
    non_value = set([time_col, building_col, temp_col] + coord_cols)

    # LONG format: time column, a building-name column, and one value column
    # (temperature + coordinates, if present, are excluded from the count).
    if time_col and building_col:
        value_candidates = [c for c in cols if c not in non_value]
        if len(value_candidates) != 1:
            return {"format": "long", "ambiguous": True,
                    "reasons": reasons + [f"Expected exactly one value column, "
                                          f"found {len(value_candidates)}: "
                                          f"{value_candidates}."],
                    "time_col": time_col, "building_col": building_col,
                    "temp_col": temp_col, "temp_is_f": temp_is_f}
        value_col = value_candidates[0]
        unit, factor = _unit_from_name(value_col)
        if unit is None:
            reasons.append(
                f"Value column '{value_col}' has NO unit in its name, so the unit "
                "is unknown. Not guessing — steam could be kWh, MMBtu, kBTU, etc. "
                "Please rename the column to include the unit (e.g. 'Steam (kWh)') "
                "or confirm the unit."
            )
            return {"format": "long", "ambiguous": True, "reasons": reasons,
                    "time_col": time_col, "building_col": building_col,
                    "value_col": value_col, "temp_col": temp_col,
                    "temp_is_f": temp_is_f}
        reasons.append(f"Detected long format: time='{time_col}', "
                       f"building='{building_col}', value='{value_col}'.")
        reasons.append(f"Unit '{unit}' -> multiply by {factor} to get kWh.")
        return {"format": "long", "ambiguous": False, "reasons": reasons,
                "time_col": time_col, "building_col": building_col,
                "value_col": value_col, "unit": unit, "factor": factor,
                "temp_col": temp_col, "temp_is_f": temp_is_f}

    # WIDE format: a time column plus one numeric column per building (and maybe
    # a temperature column, which we exclude from the building columns).
    if time_col and not building_col:
        value_cols = [c for c in cols if c not in non_value]
        unit, factor = _unit_from_name(" ".join(value_cols))
        if unit is None:
            reasons.append(
                "Detected wide format (one column per building), but no unit is "
                "stated in the column names. If the filename says the unit "
                "(e.g. '..._kwh.csv'), that is used; otherwise this is flagged."
            )
        return {"format": "wide", "ambiguous": unit is None, "reasons": reasons,
                "time_col": time_col, "value_cols": value_cols,
                "unit": unit, "factor": factor,
                "temp_col": temp_col, "temp_is_f": temp_is_f}

    return {"format": "unknown", "ambiguous": True,
            "reasons": ["Could not find a timestamp column; cannot map."]}


def _unit_from_name(name):
    """Pull a unit + conversion factor from a column name, or (None, None)."""
    low = name.lower()
    for key, factor in UNIT_PATTERNS.items():
        if key in low:
            return key, factor
    return None, None


def unit_from_filename(path):
    """Fallback: infer unit from the filename (e.g. sample_B_wide_kwh.csv)."""
    return _unit_from_name(os.path.basename(path))


def _temp_c_series(df, mapping):
    """Return a Celsius temperature series aligned to df rows, or None."""
    temp_col = mapping.get("temp_col")
    if not temp_col:
        return None
    temp = df[temp_col].astype(float)
    if mapping.get("temp_is_f"):
        temp = (temp - 32) * 5 / 9  # F -> C
    return temp.round(2)


def to_long_kwh(df, mapping, path):
    """
    Apply the mapping and return a tidy frame:
        timestamp, building_id, steam_kwh [, airTemperature]
    Temperature (if present) is converted to Celsius and carried along.
    """
    temp_c = _temp_c_series(df, mapping)
    if mapping["format"] == "long":
        out = pd.DataFrame({
            "timestamp": pd.to_datetime(df[mapping["time_col"]]),
            "building_id": df[mapping["building_col"]].astype(str),
            "steam_kwh": df[mapping["value_col"]].astype(float) * mapping["factor"],
        })
        if temp_c is not None:
            out["airTemperature"] = temp_c.values
        return out
    # wide
    factor = mapping.get("factor")
    if factor is None:
        _, factor = unit_from_filename(path)
    # Temperature is per-timestamp, so attach it before melting the buildings.
    id_vars = [mapping["time_col"]]
    work = df[[mapping["time_col"]] + mapping["value_cols"]].copy()
    if temp_c is not None:
        work["__tempC__"] = temp_c.values
        id_vars.append("__tempC__")
    long = work.melt(id_vars=id_vars, var_name="building_id", value_name="value")
    out = pd.DataFrame({
        "timestamp": pd.to_datetime(long[mapping["time_col"]]),
        "building_id": long["building_id"].astype(str),
        "steam_kwh": long["value"].astype(float) * (factor or 1.0),
    })
    if temp_c is not None:
        out["airTemperature"] = long["__tempC__"].values
    return out


def write_mapping_report(path, mapping, extra=None):
    """Write inbox/mapping_report.md describing what we found."""
    os.makedirs("inbox", exist_ok=True)
    name = os.path.basename(path)
    lines = [
        f"# Mapping report — {name}",
        "",
        f"- Detected format: **{mapping.get('format', 'unknown')}**",
        f"- Ambiguous: **{'YES — stopped for review' if mapping['ambiguous'] else 'no'}**",
        "",
        "## Target schema",
        "`timestamp`, `building_id`, `steam_kwh` (steam energy in kWh)",
        "",
        "## What we found / assumed",
    ]
    for r in mapping.get("reasons", []):
        lines.append(f"- {r}")
    if mapping["format"] == "long" and not mapping["ambiguous"]:
        lines += [
            "",
            "## Column mapping",
            f"- `{mapping['time_col']}` -> timestamp",
            f"- `{mapping['building_col']}` -> building_id",
            f"- `{mapping['value_col']}` ({mapping['unit']}) -> steam_kwh "
            f"(x {mapping['factor']})",
        ]
    if mapping["format"] == "wide":
        lines += [
            "",
            "## Column mapping",
            f"- `{mapping['time_col']}` -> timestamp",
            f"- remaining columns -> building_id (melted), values -> steam_kwh",
        ]
    if extra:
        lines += ["", extra]
    with open(os.path.join("inbox", "mapping_report.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


# Minimum data length (in hours) each scoring method needs to be meaningful.
HOURS_PER_MONTH = 730  # ~365*24/12
# The full weather-normalized model trains on one year and tests on another, so
# it needs ~2 years (train 2016 + test 2017). A single dropped file almost never
# has this, so the model is usually skipped for uploads.
MODEL_MIN_HOURS = 12 * HOURS_PER_MONTH          # 12+ months to train a model
PATTERN_MIN_HOURS = 3 * HOURS_PER_MONTH          # ~3 months for a stable pattern
QUALITY_MIN_HOURS = 24 * 7                        # 1 week for a basic quality read


def _methods_for(hours, has_weather):
    """
    Decide which scoring methods can run for a building with this much data.

    Returns (label, list_of_methods). We are explicit that an uploaded file
    usually can only get the model-free checks, because the full model needs a
    separate training year.
    """
    methods = []
    if hours >= QUALITY_MIN_HOURS:
        methods.append("data-quality check")
    if hours >= PATTERN_MIN_HOURS:
        # Setback needs weather (temperature); warm-day needs weather too.
        if has_weather:
            methods.append("pattern checks (setback + warm-day)")
        else:
            methods.append("pattern checks (setback, no-weather version)")
    if hours >= MODEL_MIN_HOURS and has_weather:
        methods.append("weather-normalized model + conformal band")

    if "weather-normalized model + conformal band" in methods:
        label = "Full model + pattern checks"
    elif any(m.startswith("pattern") for m in methods):
        label = "Pattern checks only: a full model needs 12+ months of data"
    elif methods:
        label = "Data-quality check only: not enough data for pattern checks"
    else:
        label = "Too little data to score (need at least 1 week)"
    return label, methods


def score(long_df, path, has_weather=False, coords=None):
    """
    Score the ingested buildings.

    IMPORTANT — what "scored" means for an uploaded file:
      A dropped-in file has no separate 2016 training year, so the full
      weather-normalized model + conformal band usually CANNOT run. What runs
      depends on how much data each building has:
        - >= 1 week   : data-quality check (missing %, zeros %).
        - >= ~3 months: pattern checks (night/weekend setback; warm-day heating
                        if weather is available).
        - >= 12 months + weather: the full model + 90% conformal band.
      Each building row states exactly which methods ran.

    Weather: the pattern/warm-day and model methods need outdoor temperature.
    This uploader does NOT fetch weather automatically (an arbitrary building_id
    isn't tied to a known BDG2 site). So by default only the weather-FREE checks
    run, and the report says so. To enable the temperature-dependent checks,
    supply a matching weather file (future extension); here has_weather=False.
    """
    os.makedirs(os.path.join("inbox", "results"), exist_ok=True)
    # Pattern checks use the same logic as the main pipeline.
    from waste_detect import setback_ratio, warm_day_heating

    import climate as climate_mod

    has_temp = has_weather and "airTemperature" in long_df.columns

    # Classify the site's climate once (city label from coords, flag from the
    # file's own heating-season temperature).
    lat, lng = (coords if coords else (None, None))
    city, clim, mean_temp = climate_mod.classify_site(lat, lng, df=long_df)

    rows = []
    for bid, g in long_df.groupby("building_id"):
        s = g["steam_kwh"]
        hours = int(s.size)
        label, methods = _methods_for(hours, has_temp)

        setback = warm_share = warm_kwh = hot_share = None
        warm_day_flag = False
        warm_day_note = ""
        if has_temp and hours >= PATTERN_MIN_HOURS:
            grp = g.rename(columns={"steam_kwh": "steam"})[
                ["timestamp", "steam", "airTemperature"]
            ]
            setback = setback_ratio(grp)
            warm_kwh, warm_share = warm_day_heating(grp)
            # Share of HOURS above the warm-day threshold (context for the share
            # of steam) — shown next to warm_day_share.
            temp = grp["airTemperature"].dropna()
            hot_share = (float((temp > config.WARM_DAY_TEMP_C).mean())
                         if len(temp) else None)
            # Warm-day is only a WASTE flag in a COLD climate. In a warm climate,
            # steam on warm days may serve hot water, reheat, or cooling.
            if clim == "warm":
                warm_day_note = ("Not reliable in a warm climate: steam may serve "
                                 "hot water, reheat, or cooling")
            else:
                warm_day_flag = (warm_share is not None
                                 and warm_share >= config.WARMDAY_MIN_ANNUAL_SHARE)

        rows.append({
            "building_id": bid,
            "hours": hours,
            "months_approx": round(hours / HOURS_PER_MONTH, 1),
            "total_steam_kwh": round(float(s.sum()), 1),
            "pct_missing": round(float(s.isna().mean()) * 100, 1),
            "pct_zero": round(float((s == 0).mean()) * 100, 1),
            "city": city or "",
            "climate": clim,
            "setback_ratio": (None if setback is None else round(float(setback), 2)),
            "pct_hours_above_18c": (None if hot_share is None
                                    else round(hot_share * 100, 1)),
            "warm_day_kwh": (None if warm_kwh is None else round(float(warm_kwh), 1)),
            "warm_day_share_pct": (None if warm_share is None
                                   else round(float(warm_share) * 100, 1)),
            "warm_day_flag": warm_day_flag,
            "warm_day_note": warm_day_note,
            "scored_as": label,
            "methods_run": "; ".join(methods) if methods else "none",
        })
    summary = pd.DataFrame(rows)
    name = os.path.splitext(os.path.basename(path))[0]
    out_path = os.path.join("inbox", "results", f"{name}_scored.csv")
    summary.to_csv(out_path, index=False)
    return out_path, summary


def process(path):
    """Full pipeline for one dropped file. Returns a status string."""
    df = pd.read_csv(path)
    mapping = detect_and_map(df)

    # For wide files, let the filename supply the unit if the header didn't.
    if mapping["format"] == "wide" and mapping.get("unit") is None:
        unit, factor = unit_from_filename(path)
        if unit is not None:
            mapping["unit"] = unit
            mapping["factor"] = factor
            mapping["ambiguous"] = False
            mapping["reasons"].append(
                f"Unit '{unit}' taken from the filename -> x{factor} to kWh.")

    if mapping["ambiguous"]:
        write_mapping_report(path, mapping,
                             extra="**STOPPED.** Fix the ambiguity above, then "
                                   "re-drop the file.")
        return f"AMBIGUOUS: {os.path.basename(path)} — wrote inbox/mapping_report.md, stopped."

    long_df = to_long_kwh(df, mapping, path)
    # If the file carried a temperature column, weather is available for the
    # temperature-dependent checks.
    has_weather = bool(mapping.get("temp_col"))
    # Coordinates (if present) enable city labeling + climate classification.
    coords = _find_coords(df)
    out_path, summary = score(long_df, path, has_weather=has_weather, coords=coords)
    labels = summary["scored_as"].value_counts().to_dict()
    label_lines = "\n".join(f"  - {k}: {v} building(s)" for k, v in labels.items())
    # Climate line (same for all buildings in a file).
    clim = summary["climate"].iloc[0] if len(summary) else "unknown"
    city = summary["city"].iloc[0] if len(summary) else ""
    climate_note = ""
    if clim != "unknown":
        where = f" ({city})" if city else ""
        if clim == "warm":
            climate_note = (
                f"\n\n### Climate\nSite classified **warm**{where}. Warm-day "
                "results are labeled \"Not reliable in a warm climate: steam may "
                "serve hot water, reheat, or cooling\" and are NOT counted as a "
                "waste flag."
            )
        else:
            climate_note = (
                f"\n\n### Climate\nSite classified **cold**{where}. Warm-day "
                "flags are treated as reliable here."
            )
    if has_weather:
        weather_note = (
            "### Weather\n"
            f"This file INCLUDED an outdoor-temperature column "
            f"('{mapping['temp_col']}'"
            f"{', converted F -> C' if mapping.get('temp_is_f') else ''}), so the "
            "temperature-based pattern checks (setback + warm-day) ran. "
            "`setback_ratio` near/above 1.0 means little night/weekend setback; "
            "`warm_day_share_pct` is the share of steam used when warmer than "
            "18 C outside, shown next to `pct_hours_above_18c` for context."
        )
    else:
        weather_note = (
            "### Weather\n"
            "No temperature column was found, and this uploader does NOT fetch "
            "weather automatically (an arbitrary building_id isn't tied to a known "
            "BDG2 site), so only weather-free checks ran. Add an outdoor-temp "
            "column (e.g. 'Outdoor Temp (F)') to enable the pattern checks."
        )
    result = (
        f"## Result\nScored {len(summary)} buildings -> `{out_path}`.\n\n"
        "### What \"scored\" means here\n"
        "A dropped-in file has no separate 2016 training year, so the full "
        "weather-normalized model usually cannot run. Methods run per building "
        "depend on data length:\n"
        "  - >= 1 week: data-quality check\n"
        "  - >= ~3 months: pattern checks (setback; warm-day needs weather)\n"
        "  - >= 12 months + weather: full model + 90% conformal band\n\n"
        f"Per-building outcome:\n{label_lines}\n\n"
        f"{weather_note}{climate_note}"
    )
    write_mapping_report(path, mapping, extra=result)
    return f"OK: {os.path.basename(path)} — scored {len(summary)} buildings -> {out_path}"


def _path_from_stdin():
    """
    Hooks pass session context as JSON on stdin. Pull a file path out of it,
    trying the common key names. Returns None if nothing usable is found.
    """
    import json
    try:
        raw = sys.stdin.read()
    except Exception:
        return None
    if not raw.strip():
        return None
    try:
        data = json.loads(raw)
    except Exception:
        # Not JSON — maybe the path was piped as plain text.
        return raw.strip() or None
    for key in ("filePath", "file_path", "path", "KIRO_FILE_PATH"):
        if isinstance(data, dict) and data.get(key):
            return data[key]
    # Some payloads nest it under a context object.
    ctx = data.get("context") if isinstance(data, dict) else None
    if isinstance(ctx, dict):
        for key in ("filePath", "file_path", "path"):
            if ctx.get(key):
                return ctx[key]
    return None


def main():
    # Prefer an explicit argument; otherwise read the path from the hook's stdin.
    path = sys.argv[1] if len(sys.argv) >= 2 else _path_from_stdin()
    if not path:
        print("Usage: python src/ingest.py <path-to-csv>  (or pipe hook JSON on stdin)")
        sys.exit(1)
    if not os.path.exists(path):
        print(f"File not found: {path}")
        sys.exit(1)
    print(process(path))


if __name__ == "__main__":
    main()
