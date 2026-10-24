"""
_make_samples.py — build the bring-your-own-data sample files from REAL data.

Pulls a handful of real Bull-site buildings from Datasets/steam_cleaned.csv (the
BDG2 steam file) and writes three small CSVs under samples/ in deliberately messy
formats, to exercise the inbox ingestion hook:
  - sample_A_long_mmbtu.csv : long, "Date/Time","Bldg Name","Steam (MMBtu)"
  - sample_B_wide_kwh.csv   : wide (one column per building), "Reading Time", kWh
  - sample_C_ambiguous.csv  : long, value column "Usage" with NO unit (flag, don't guess)

The published BDG2 steam values are in kWh. For sample A we convert kWh -> MMBtu
so the ingester has to convert back. We take a short date window and only
buildings with mostly-present, non-zero data so the files are small and useful.

Run from the repo root:  python samples/_make_samples.py
Note: reads Datasets/ (gitignored); the small sample outputs are committed.
"""

import pandas as pd

KWH_TO_MMBTU = 0.00341214  # 1 kWh = 0.00341214 MMBtu

# A two-week window keeps each file well under 1 MB.
START = "2017-01-09 00:00:00"
END = "2017-01-22 23:00:00"


def pick_buildings(df, n, exclude):
    """Choose n Bull buildings in the window with the fewest missing/zeros."""
    bull = [c for c in df.columns if c.startswith("Bull_") and c not in exclude]
    quality = []
    for b in bull:
        s = df[b]
        score = s.isna().mean() + (s == 0).mean()  # lower is cleaner
        quality.append((score, b))
    quality.sort()
    return [b for _, b in quality[:n]]


def main():
    df = pd.read_csv("Datasets/steam_cleaned.csv", parse_dates=["timestamp"])
    df = df[(df["timestamp"] >= START) & (df["timestamp"] <= END)].reset_index(drop=True)

    used = set()
    a_bldgs = pick_buildings(df, 3, used); used.update(a_bldgs)
    b_bldgs = pick_buildings(df, 4, used); used.update(b_bldgs)
    c_bldgs = pick_buildings(df, 3, used); used.update(c_bldgs)

    ts = df["timestamp"].dt.strftime("%Y-%m-%d %H:%M")

    # --- Sample A: long format, steam in MMBtu (converted from the real kWh) ---
    rows = []
    for b in a_bldgs:
        mmbtu = (df[b] * KWH_TO_MMBTU).round(5)
        for t, v in zip(ts, mmbtu):
            rows.append({"Date/Time": t, "Bldg Name": b, "Steam (MMBtu)": v})
    pd.DataFrame(rows).to_csv("samples/sample_A_long_mmbtu.csv", index=False)

    # --- Sample B: wide format, real kWh values, "Reading Time" column ---
    wide = {"Reading Time": ts}
    for b in b_bldgs:
        wide[b] = df[b].round(2)
    pd.DataFrame(wide).to_csv("samples/sample_B_wide_kwh.csv", index=False)

    # --- Sample C: long format, value column "Usage" with NO unit ---
    rows = []
    for b in c_bldgs:
        for t, v in zip(ts, df[b].round(2)):
            rows.append({"Date/Time": t, "Bldg Name": b, "Usage": v})
    pd.DataFrame(rows).to_csv("samples/sample_C_ambiguous.csv", index=False)

    print("Built from real Bull buildings:")
    print("  A (MMBtu):", a_bldgs)
    print("  B (kWh)  :", b_bldgs)
    print("  C (Usage):", c_bldgs)


if __name__ == "__main__":
    main()
