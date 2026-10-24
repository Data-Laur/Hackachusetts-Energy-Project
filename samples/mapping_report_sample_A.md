# Mapping report — sample_A_long_mmbtu.csv

- Detected format: **long**
- Ambiguous: **no**

## Target schema
`timestamp`, `building_id`, `steam_kwh` (steam energy in kWh)

## What we found / assumed
- Found outdoor temperature column 'Outdoor Temp (F)' (Fahrenheit -> converting to Celsius).
- Detected long format: time='Date/Time', building='Bldg Name', value='Steam (MMBtu)'.
- Unit 'mmbtu' -> multiply by 293.07122 to get kWh.

## Column mapping
- `Date/Time` -> timestamp
- `Bldg Name` -> building_id
- `Steam (MMBtu)` (mmbtu) -> steam_kwh (x 293.07122)

## Result
Scored 3 buildings -> `inbox/results/sample_A_long_mmbtu_scored.csv`.

### What "scored" means here
A dropped-in file has no separate 2016 training year, so the full weather-normalized model usually cannot run. Methods run per building depend on data length:
  - >= 1 week: data-quality check
  - >= ~3 months: pattern checks (setback; warm-day needs weather)
  - >= 12 months + weather: full model + 90% conformal band

Per-building outcome:
  - Pattern checks only: a full model needs 12+ months of data: 3 building(s)

### Weather
This file INCLUDED an outdoor-temperature column ('Outdoor Temp (F)', converted F -> C), so the temperature-based pattern checks (setback + warm-day) ran. `setback_ratio` near/above 1.0 means little night/weekend setback; `warm_day_share_pct` is the share of steam used when warmer than 18 C outside, shown next to `pct_hours_above_18c` for context.

### Climate
Site classified **warm** (Austin, Texas). Warm-day results are labeled "Not reliable in a warm climate: steam may serve hot water, reheat, or cooling" and are NOT counted as a waste flag.
