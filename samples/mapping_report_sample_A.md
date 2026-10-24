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
