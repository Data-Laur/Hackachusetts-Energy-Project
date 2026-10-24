"""
make_monthly_chart.py — quick diagnostic chart (not part of the main pipeline).

Shows monthly TOTAL actual vs expected steam for one or more buildings, so you
can eyeball whether excess is a broad level shift (every month higher) or a
seasonal/behavioral pattern (only some months higher).

How to run:
    python make_monthly_chart.py

Output: outputs/monthly_actual_vs_expected.html  (open in a browser)
Units: steam in kWh.
"""

import os

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

import config

BUILDINGS = ["Hog_education_Caridad", "Hog_education_Sonia"]


def main():
    preds = pd.read_csv(
        os.path.join(config.PROCESSED_DIR, "predictions.csv.gz"),
        parse_dates=["timestamp"],
    )

    fig = make_subplots(
        rows=len(BUILDINGS), cols=1, subplot_titles=BUILDINGS, vertical_spacing=0.12
    )

    for i, bid in enumerate(BUILDINGS, start=1):
        g = preds[preds["building_id"] == bid].copy()
        g["month"] = g["timestamp"].dt.to_period("M").dt.to_timestamp()
        monthly = g.groupby("month").agg(
            actual=("actual", "sum"), expected=("expected", "sum")
        ).reset_index()

        fig.add_trace(
            go.Bar(x=monthly["month"], y=monthly["actual"], name="Actual (kWh)",
                   marker_color="#d1495b", showlegend=(i == 1)),
            row=i, col=1,
        )
        fig.add_trace(
            go.Scatter(x=monthly["month"], y=monthly["expected"],
                       name="Expected (kWh)", mode="lines+markers",
                       line=dict(color="#00798c", width=3),
                       showlegend=(i == 1)),
            row=i, col=1,
        )
        fig.update_yaxes(title_text="Steam (kWh/month)", row=i, col=1)

    fig.update_layout(
        title="Monthly actual vs expected steam (2017) — is the excess a level "
              "shift or seasonal?",
        height=700, barmode="group",
    )

    os.makedirs("outputs", exist_ok=True)
    out = os.path.join("outputs", "monthly_actual_vs_expected.html")
    fig.write_html(out, include_plotlyjs="inline")
    print(f"Saved chart -> {out}")
    # Also print the monthly numbers so the pattern is visible in text.
    for bid in BUILDINGS:
        g = preds[preds["building_id"] == bid].copy()
        g["m"] = g["timestamp"].dt.month
        monthly = g.groupby("m").agg(actual=("actual", "sum"),
                                     expected=("expected", "sum"))
        monthly["excess"] = (monthly["actual"] - monthly["expected"]).round(0)
        print(f"\n{bid} — monthly totals (kWh):")
        print(monthly.round(0).to_string())


if __name__ == "__main__":
    main()
