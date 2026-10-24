"""
climate.py — offline city labeling + climate classification for Heat Check.

Given coordinates, we label the nearest city (fully offline, via the
reverse_geocoder package — no API calls) and classify the site's climate as
"cold" or "warm" based on its mean heating-season outdoor temperature.

Why this matters: a warm-day steam flag only makes sense for heating-only steam
in a COLD climate. In a warm climate, steam on warm days may serve hot water,
reheat, or absorption cooling, so it is NOT necessarily waste.

Units: temperature in degC.
"""

import config


def city_label(lat, lng):
    """
    Return a 'City, Region' label for the coordinates, fully offline.
    Returns None if reverse_geocoder isn't available or lookup fails.
    """
    try:
        import reverse_geocoder as rg
    except Exception:
        return None
    try:
        res = rg.search([(float(lat), float(lng))], verbose=False)
        if res:
            r = res[0]
            parts = [r.get("name"), r.get("admin1")]
            return ", ".join(p for p in parts if p)
    except Exception:
        return None
    return None


def climate_flag(mean_heating_temp_c):
    """
    Classify a site as 'warm' or 'cold' from its mean heating-season temperature.
    Cutoff lives in config.CLIMATE_WARM_CUTOFF_C.
    """
    if mean_heating_temp_c is None:
        return "unknown"
    return "warm" if mean_heating_temp_c > config.CLIMATE_WARM_CUTOFF_C else "cold"


def mean_heating_season_temp(df, temp_col="airTemperature", ts_col="timestamp"):
    """
    Mean outdoor temperature over the heating-season months (config), or None if
    there's no usable temperature data.
    """
    if temp_col not in df.columns or ts_col not in df.columns:
        return None
    months = df[ts_col].dt.month
    season = df.loc[months.isin(config.HEATING_SEASON_MONTHS), temp_col].dropna()
    if len(season) == 0:
        return None
    return float(season.mean())


def classify_site(lat=None, lng=None, df=None):
    """
    Convenience: return (city_label, climate_flag, mean_heating_temp_c).
    Uses coordinates for the city label and the dataframe's temperature for the
    climate flag when available.
    """
    label = city_label(lat, lng) if (lat is not None and lng is not None) else None
    mean_temp = mean_heating_season_temp(df) if df is not None else None
    return label, climate_flag(mean_temp), mean_temp
