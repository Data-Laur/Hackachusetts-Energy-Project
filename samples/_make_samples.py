"""
_make_samples.py — one-off generator for the bring-your-own-data sample files.

Creates three small CSVs under samples/ that exercise the inbox ingestion hook:
  - sample_A_long_mmbtu.csv : long format, steam in MMBtu, explicit unit in header
  - sample_B_wide_kwh.csv   : wide format (one column per building), kWh
  - sample_C_ambiguous.csv  : long format but the value column is just "Usage"
                              with NO unit -> must be flagged, not guessed

Data is synthetic (a simple temperature-driven steam pattern) so the files stay
tiny and contain no real BDG2 data. Building names use the "Bull" site prefix.

Run:  python samples/_make_samples.py
Units: MMBtu and kWh as noted per file; temperature in degC (not needed here).
"""

import numpy as np
import pandas as pd

RNG = np.random.default_rng(7)
# 3-5 Bull buildings per file.
A_BLDGS = ["Bull_education_Dawn", "Bull_office_Ivan", "Bull_lodging_Pearl"]
B_BLDGS = ["Bull_office_Quinn", "Bull_education_Rosa", "Bull_assembly_Sam", "Bull_office_Tom"]
C_BLDGS = ["Bull_office_Uma", "Bull_education_Vince", "Bull_lodging_Wes"]

# Two weeks of hourly timestamps keeps each file well under 1 MB.
HOURS = pd.date_range("2017-01-02 00:00", periods=24 * 14, freq="h")

MMBTU_PER_KWH = 0.00341214  # 1 kWh = 0.00341214 MMBtu


def synth_kwh(n, base):
    """A simple positive hourly steam series (kWh)."""
    hour = np.arange(n) % 24
    daily = 1 + 0.4 * np.cos((hour - 6) / 24 * 2 * np.pi)  # peak in early morning
    noise = RNG.normal(1, 0.08, n).clip(0.5, 1.5)
    return (base * daily * noise).round(2)


def make_long_mmbtu():
    rows = []
    for b in A_BLDGS:
        kwh = synth_kwh(len(HOURS), base=RNG.uniform(80, 200))
        mmbtu = (kwh * MMBTU_PER_KWH).round(5)
        for t, v in zip(HOURS, mmbtu):
            rows.append({"Date/Time": t.strftime("%Y-%m-%d %H:%M"),
                         "Bldg Name": b, "Steam (MMBtu)": v})
    pd.DataFrame(rows).to_csv("samples/sample_A_long_mmbtu.csv", index=False)


def make_wide_kwh():
    data = {"Reading Time": [t.strftime("%Y-%m-%d %H:%M") for t in HOURS]}
    for b in B_BLDGS:
        data[b] = synth_kwh(len(HOURS), base=RNG.uniform(100, 300))
    pd.DataFrame(data).to_csv("samples/sample_B_wide_kwh.csv", index=False)


def make_ambiguous():
    rows = []
    for b in C_BLDGS:
        kwh = synth_kwh(len(HOURS), base=RNG.uniform(90, 220))
        for t, v in zip(HOURS, kwh):
            # Value column has NO unit in its name on purpose.
            rows.append({"Date/Time": t.strftime("%Y-%m-%d %H:%M"),
                         "Bldg Name": b, "Usage": v})
    pd.DataFrame(rows).to_csv("samples/sample_C_ambiguous.csv", index=False)


if __name__ == "__main__":
    make_long_mmbtu()
    make_wide_kwh()
    make_ambiguous()
    print("Wrote sample_A_long_mmbtu.csv, sample_B_wide_kwh.csv, sample_C_ambiguous.csv")
