# Mapping report — sample_C_ambiguous.csv

- Detected format: **long**
- Ambiguous: **YES — stopped for review**

## Target schema
`timestamp`, `building_id`, `steam_kwh` (steam energy in kWh)

## What we found / assumed
- Found outdoor temperature column 'Outdoor Temp (F)' (Fahrenheit -> converting to Celsius).
- Value column 'Usage' has NO unit in its name, so the unit is unknown. Not guessing — steam could be kWh, MMBtu, kBTU, etc. Please rename the column to include the unit (e.g. 'Steam (kWh)') or confirm the unit.

**STOPPED.** Fix the ambiguity above, then re-drop the file.
