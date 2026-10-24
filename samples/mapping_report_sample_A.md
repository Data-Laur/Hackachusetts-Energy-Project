# Mapping report — sample_A_long_mmbtu.csv

- Detected format: **long**
- Ambiguous: **no**

## Target schema
`timestamp`, `building_id`, `steam_kwh` (steam energy in kWh)

## What we found / assumed
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
  - Data-quality check only: not enough data for pattern checks: 3 building(s)

### Weather
The pattern/warm-day and model methods need outdoor temperature. This uploader does NOT fetch weather automatically — an arbitrary building_id isn't tied to a known BDG2 site — so only weather-free checks ran. Supply a matching weather file to enable the temperature-based checks.
