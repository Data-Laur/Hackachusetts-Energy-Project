"""
_make_samples.py — build the bring-your-own-data sample files from REAL data.

Pulls real Bull-site buildings from Datasets/steam_cleaned.csv (BDG2 steam) plus
Bull outdoor temperature from Datasets/weather.csv, over a 4-month window
(Jan–Apr 2017) so an upload has enough data for the pattern checks. Writes three
small CSVs under samples/ in deliberately messy formats:
  - sample_A_long_mmbtu.csv : long; "Date/Time","Bldg Name","Steam (MMBtu)",
                              "Outdoor Temp (F)"
  - sample_B_wide_kwh.csv   : wide; "Reading Time", one kWh column per building,
                              plus "Outdoor Temp (F)"
  - sample_C_ambiguous.csv  : long; value column "Usage" (NO unit) + temp F

The published BDG2 steam values are kWh. For sample A we convert kWh -> MMBtu so
the ingester must convert back. Temperature is stored in Fahrenheit so the
ingester must detect and convert F -> C before the pattern checks.

Run from the repo root:  python samples/_make_samples.py
Note: reads Datasets/ (gitignored); the small sample outputs are committed.
"""

import pandas as pd

KWH_TO_MMBTU = 0.00341214  # 1 kWh = 0.00341214 MMBtu

# 4 months keeps files under ~1 MB and gives the pattern checks enough data.
START = "2017-01-01 00:00:00"
END = "2017-04-30 23:00:00"


def c_to_f(celsius):
    return (celsius * 9 / 5 + 32).round(1)


def pick_buildings(df, n, exclude):
    """Choose n Bull buildings in the window with the fewest missing/zeros."""
    bull = [c for c in df.columns if c.startswith("Bull_") and c not in exclude]
    quality = []
    for b in bull:
        s = df[b]
        score = s.isna().mean() + (s == 0).mean()
        quality.append((score, b))
    quality.sort()
    return [b for _, b in quality[:n]]


def main():
    steam = pd.read_csv("Datasets/steam_cleaned.csv", parse_dates=["timestamp"])
    steam = steam[(steam["timestamp"] >= START) & (steam["timestamp"] <= END)].reset_index(drop=True)

    weather = pd.read_csv("Datasets/weather.csv", parse_dates=["timestamp"])
    weather = weather[weather["site_id"] == "Bull"][["timestamp", "airTemperature"]]
    # Attach temperature to the steam timeline, fill small gaps.
    steam = steam.merge(weather, on="timestamp", how="left")
    steam["airTemperature"] = steam["airTemperature"].ffill().bfill()
    temp_f = c_to_f(steam["airTemperature"])

    used = set()
    a_bldgs = pick_buildings(steam, 3, used); used.update(a_bldgs)
    b_bldgs = pick_buildings(steam, 4, used); used.update(b_bldgs)
    c_bldgs = pick_buildings(steam, 3, used); used.update(c_bldgs)

    ts = steam["timestamp"].dt.strftime("%Y-%m-%d %H:%M")

    # Bull is the Austin, TX campus in BDG2 — include coordinates so the
    # ingester can label the city and classify the climate (warm).
    BULL_LAT, BULL_LNG = 30.27, -97.74

    # --- Sample A: long, MMBtu + Fahrenheit temperature + coordinates ---
    rows = []
    for b in a_bldgs:
        mmbtu = (steam[b] * KWH_TO_MMBTU).round(5)
        for t, v, tf in zip(ts, mmbtu, temp_f):
            rows.append({"Date/Time": t, "Bldg Name": b,
                         "Steam (MMBtu)": v, "Outdoor Temp (F)": tf,
                         "Latitude": BULL_LAT, "Longitude": BULL_LNG})
    pd.DataFrame(rows).to_csv("samples/sample_A_long_mmbtu.csv", index=False)

    # --- Sample B: wide, kWh + Fahrenheit temperature column ---
    wide = {"Reading Time": ts}
    for b in b_bldgs:
        wide[b] = steam[b].round(2)
    wide["Outdoor Temp (F)"] = temp_f
    pd.DataFrame(wide).to_csv("samples/sample_B_wide_kwh.csv", index=False)

    # --- Sample C: long, value column "Usage" (no unit) + temperature ---
    rows = []
    for b in c_bldgs:
        for t, v, tf in zip(ts, steam[b].round(2), temp_f):
            rows.append({"Date/Time": t, "Bldg Name": b,
                         "Usage": v, "Outdoor Temp (F)": tf})
    pd.DataFrame(rows).to_csv("samples/sample_C_ambiguous.csv", index=False)

    print("Built from real Bull data (Jan-Apr 2017):")
    print("  A (MMBtu):", a_bldgs)
    print("  B (kWh)  :", b_bldgs)
    print("  C (Usage):", c_bldgs)


if __name__ == "__main__":
    main()
