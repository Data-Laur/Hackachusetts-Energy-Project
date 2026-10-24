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

# Unit conversions into kWh.
MMBTU_TO_KWH = 293.07122       # 1 MMBtu = 293.07 kWh
KBTU_TO_KWH = 0.29307122       # 1 kBTU  = 0.293 kWh
# Candidate column names we recognize (lowercased, loose match).
TIME_HINTS = ["date/time", "reading time", "timestamp", "time", "datetime"]
BUILDING_HINTS = ["bldg name", "building", "building_id", "name", "bldg"]
# Value column name -> unit. Only used when the unit is explicit.
UNIT_PATTERNS = {
    "kwh": 1.0,
    "mmbtu": MMBTU_TO_KWH,
    "kbtu": KBTU_TO_KWH,
}


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

    # LONG format: has a time column, a building-name column, and one value column.
    if time_col and building_col:
        value_candidates = [c for c in cols if c not in (time_col, building_col)]
        if len(value_candidates) != 1:
            return {"format": "long", "ambiguous": True,
                    "reasons": [f"Expected exactly one value column, found "
                                f"{len(value_candidates)}: {value_candidates}."],
                    "time_col": time_col, "building_col": building_col}
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
                    "value_col": value_col}
        reasons.append(f"Detected long format: time='{time_col}', "
                       f"building='{building_col}', value='{value_col}'.")
        reasons.append(f"Unit '{unit}' -> multiply by {factor} to get kWh.")
        return {"format": "long", "ambiguous": False, "reasons": reasons,
                "time_col": time_col, "building_col": building_col,
                "value_col": value_col, "unit": unit, "factor": factor}

    # WIDE format: a time column plus one numeric column per building.
    if time_col and not building_col:
        value_cols = [c for c in cols if c != time_col]
        # Unit must come from somewhere; for wide files we look at the filename
        # hint (handled by the caller) — here we assume the header carries it or
        # the caller passed a unit. We check if ANY building col names a unit.
        unit, factor = _unit_from_name(" ".join(value_cols))
        if unit is None:
            reasons.append(
                "Detected wide format (one column per building), but no unit is "
                "stated in the column names. If the filename says the unit "
                "(e.g. '..._kwh.csv'), that is used; otherwise this is flagged."
            )
        return {"format": "wide", "ambiguous": unit is None, "reasons": reasons,
                "time_col": time_col, "value_cols": value_cols,
                "unit": unit, "factor": factor}

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


def to_long_kwh(df, mapping, path):
    """Apply the mapping and return a tidy frame: timestamp, building_id, steam_kwh."""
    if mapping["format"] == "long":
        out = pd.DataFrame({
            "timestamp": pd.to_datetime(df[mapping["time_col"]]),
            "building_id": df[mapping["building_col"]].astype(str),
            "steam_kwh": df[mapping["value_col"]].astype(float) * mapping["factor"],
        })
        return out
    # wide
    factor = mapping.get("factor")
    unit = mapping.get("unit")
    if factor is None:
        # Try the filename as a last resort.
        unit, factor = unit_from_filename(path)
    long = df.melt(id_vars=mapping["time_col"], var_name="building_id",
                   value_name="value")
    out = pd.DataFrame({
        "timestamp": pd.to_datetime(long[mapping["time_col"]]),
        "building_id": long["building_id"].astype(str),
        "steam_kwh": long["value"].astype(float) * (factor or 1.0),
    })
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


def score(long_df, path):
    """
    Score the ingested buildings with a lightweight version of the pipeline's
    quality + warm-day logic (the full model needs 2016 training data, which a
    dropped-in file won't have). We report per-building total steam and a simple
    data-quality note, written to inbox/results/.
    """
    os.makedirs(os.path.join("inbox", "results"), exist_ok=True)
    g = long_df.groupby("building_id")["steam_kwh"]
    summary = pd.DataFrame({
        "total_steam_kwh": g.sum().round(1),
        "hours": g.size(),
        "pct_zero": (g.apply(lambda s: (s == 0).mean()) * 100).round(1),
    }).reset_index()
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
    out_path, summary = score(long_df, path)
    write_mapping_report(
        path, mapping,
        extra=f"## Result\nScored {len(summary)} buildings -> `{out_path}`.")
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
