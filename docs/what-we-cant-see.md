# What we can't see (limitations)

Honest limits of the Heat Check analysis. Units: steam in kWh, temperature in °C.

## Warm-day flags are most reliable for heating-only steam in cold climates

Our main site (Hog) is in the Minneapolis area, a cold climate. In warm climates, steam on warm days may serve hot water, reheat, or absorption cooling rather than space heating, so Heat Check does not raise a warm-day waste flag for sites it classifies as warm.

## Year-over-year drift limits accuracy

Our 90% prediction bands cover 80.7% of 2017 hours, but an in-distribution control (calibrate on half the 2016 holdout weeks, test on the other half) covers 89.5%, right on target. That gap means 2017 genuinely behaves differently from 2016 for many buildings (real drift), not that the bands are miscalibrated. We deliberately did not widen the bands to force 90% on 2017, because that would hide the very excess we want to find.

## The level-shift rule can miss mid-year changes

We relabel a building "Changed since 2016" when its excess is spread across 8 or more months (a broad baseline shift rather than specific waste). A change that started partway through 2017 may only touch a few months, so it can slip past this rule and be counted as waste. We trade some of this precision for catching seasonal and behavioral waste.

## We only see steam meters at one site

For site Hog we have steam only: no electricity, chilled water, or occupancy data. A building that looks wasteful on steam might be explained by something we cannot observe, such as a process load or a schedule change.

## "Can't judge" is a real answer

25 buildings have a model that fails the ASHRAE trust bar, or data too poor to model, so we refuse to rank them rather than guess. Their waste, if any, is invisible to the exceedance method; only the pattern checks can still flag them.

## Costs and CO2 are assumptions

Gas price, boiler efficiency, and the emission factor are editable estimates in config.py, not this campus's measured values. Treat dollar and CO2 figures as order-of-magnitude.

## Excess is measured conservatively

We only count energy above the 90% upper band, so reported excess understates total over-use. Real waste is at least this much, and likely more.
