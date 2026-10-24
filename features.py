"""
features.py — Shared feature engineering for Heat Check.

Both the model (stage 2) and the pattern metrics (stage 3) need the same notion
of "what kind of hour is this": time of day, weekend, holiday/break, month, and
a smoothed outdoor temperature. Keeping that logic in one place means the model
and the analysis always agree.

Units: temperature in degC.
"""

import pandas as pd

import config


# US federal holidays for 2016 and 2017 (the only two years in the data).
# Listed explicitly so there is no extra dependency and you can see exactly what
# counts as a holiday. Source: US OPM federal holiday calendars for 2016–2017.
US_FEDERAL_HOLIDAYS = {
    # 2016
    "2016-01-01",  # New Year's Day
    "2016-01-18",  # Birthday of Martin Luther King, Jr.
    "2016-02-15",  # Washington's Birthday
    "2016-05-30",  # Memorial Day
    "2016-07-04",  # Independence Day
    "2016-09-05",  # Labor Day
    "2016-10-10",  # Columbus Day
    "2016-11-11",  # Veterans Day
    "2016-11-24",  # Thanksgiving Day
    "2016-12-26",  # Christmas Day (observed)
    # 2017
    "2017-01-02",  # New Year's Day (observed)
    "2017-01-16",  # Birthday of Martin Luther King, Jr.
    "2017-02-20",  # Washington's Birthday
    "2017-05-29",  # Memorial Day
    "2017-07-04",  # Independence Day
    "2017-09-04",  # Labor Day
    "2017-10-09",  # Columbus Day
    "2017-11-10",  # Veterans Day (observed)
    "2017-11-23",  # Thanksgiving Day
    "2017-12-25",  # Christmas Day
}


def _is_winter_break(timestamps):
    """True for dates in the academic winter break (Dec 20 – Jan 10)."""
    month = timestamps.dt.month
    day = timestamps.dt.day
    start_m, start_d = config.WINTER_BREAK_START  # (12, 20)
    end_m, end_d = config.WINTER_BREAK_END         # (1, 10)
    late_december = (month == start_m) & (day >= start_d)
    early_january = (month == end_m) & (day <= end_d)
    return late_december | early_january


def add_model_features(df):
    """
    Add every feature the model uses. Returns a copy of df with new columns:
        hour            : 0-23
        is_weekend      : 1 on Sat/Sun else 0
        month           : 1-12
        is_holiday      : 1 on a US federal holiday OR winter break else 0
        temp_roll24     : 24-hour rolling mean of airTemperature (degC)
    Keeps airTemperature as-is.
    """
    df = df.copy()
    ts = df["timestamp"]

    df["hour"] = ts.dt.hour
    df["is_weekend"] = (ts.dt.dayofweek >= 5).astype(int)
    df["month"] = ts.dt.month

    date_str = ts.dt.strftime("%Y-%m-%d")
    is_fed_holiday = date_str.isin(US_FEDERAL_HOLIDAYS)
    df["is_holiday"] = (is_fed_holiday | _is_winter_break(ts)).astype(int)

    # 24-hour rolling mean outdoor temperature. We sort by time first so the
    # rolling window is chronological. min_periods=1 avoids losing early rows.
    df = df.sort_values("timestamp")
    df["temp_roll24"] = (
        df["airTemperature"].rolling(config.TEMP_ROLLING_HOURS, min_periods=1).mean()
    )
    return df


# The exact columns the model trains on.
FEATURE_COLUMNS = [
    "airTemperature",
    "temp_roll24",
    "hour",
    "is_weekend",
    "month",
    "is_holiday",
]
