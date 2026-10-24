"""
report.py: STAGE 4 of Heat Check.

Builds ONE interactive, self-contained web page at docs/index.html from the
computed results. No server and no Streamlit: the page is plain HTML + CSS +
JavaScript, with Plotly loaded from a CDN (keeps the file small). GitHub Pages
can serve docs/index.html directly.

What the page contains:
  - View 1 "Priorities": headline cards, a sortable ranked table (Confirmed waste
    then Worth a look), filters, CSV export, and a collapsible list of the
    buildings we don't rank.
  - View 2 "Building detail": verdict + model trust, an actual-vs-expected chart
    with the 90% band (worst week by default, with a week picker), an excess
    heatmap (hour-of-day x day-of-week), and monthly actual-vs-expected bars.
  - Method, "What we can't see", and Data (BDG2 citation) sections.

How to run (one command regenerates everything):
    python src/report.py

Inputs:
    data/processed/waste_ranking.csv
    data/processed/predictions.csv.gz
    Datasets/metadata.csv
    docs/what-we-cant-see.md

Output:
    docs/index.html

Units: steam/energy in kWh, money in $, emissions in kg CO2, temperature in °C.
Data source: Building Data Genome Project 2 (Miller et al., Sci Data 7, 368, 2020).
"""

import json
import os
import sys

import numpy as np
import pandas as pd

# Allow running as `python src/report.py` from the repo root: make sure the repo
# root (where config.py lives) is importable.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import config

RANKED_VERDICTS = ["Confirmed waste", "Worth a look"]
# Plain-language fixes keyed by what flagged the building.
FIX_NO_SETBACK = "Reprogram BMS schedule (near zero cost)"
FIX_WARM_DAY = "Outdoor-temp heating lockout, check valves (low cost)"
FIX_EXCEEDANCE = "Investigate controls and steam traps"


def likely_fix(flagged_by):
    """Map the flag reasons to a recommended fix (plain language)."""
    if "no night/weekend setback" in flagged_by:
        return FIX_NO_SETBACK
    if "heating on warm days" in flagged_by:
        return FIX_WARM_DAY
    if "exceedance" in flagged_by:
        return FIX_EXCEEDANCE
    return "Review manually"


def pattern_text(row):
    """Human-readable pattern description from the flags."""
    parts = []
    if row.get("flag_no_setback"):
        parts.append("No night/weekend setback")
    if row.get("flag_warm_day"):
        parts.append("Heating on warm days")
    if "exceedance" in str(row.get("flagged_by", "")):
        parts.append("Uses more than expected")
    return "; ".join(parts) if parts else "-"


# How many weeks to offer in the per-building picker. We keep the worst N weeks
# (most excess) to keep the HTML file small while still letting you explore the
# problem periods. The worst week is shown by default.
WEEKS_TO_KEEP = 12


def worst_week_and_weeks(g):
    """
    Given one building's 2017 predictions, return:
      - a list of the WEEKS_TO_KEEP worst weeks (most excess), newest-first by
        excess, each with hourly series for the chart,
      - the index (within that list) of the worst week.
    Timestamps use a compact 'MM-DD HH:00' label to keep the file small.
    """
    g = g.sort_values("timestamp").copy()
    g["week_start"] = g["timestamp"].dt.to_period("W").dt.start_time
    g["excess"] = (g["actual"] - g["upper90"]).clip(lower=0)

    # Score each week by total excess, then keep the worst ones.
    scored = []
    for wk, wg in g.groupby("week_start"):
        scored.append((float(wg["excess"].sum()), wk, wg))
    scored.sort(key=lambda x: x[0], reverse=True)
    kept = scored[:WEEKS_TO_KEEP]
    # Present them in calendar order so the picker reads naturally.
    kept.sort(key=lambda x: x[1])

    weeks = []
    worst_idx = 0
    best_excess = -1.0
    for i, (tot_excess, wk, wg) in enumerate(kept):
        weeks.append(
            {
                "label": pd.Timestamp(wk).strftime("%Y-%m-%d"),
                # Full ISO datetimes so Plotly renders a real date axis.
                "t": wg["timestamp"].dt.strftime("%Y-%m-%d %H:%M").tolist(),
                "actual": wg["actual"].round(0).tolist(),
                "expected": wg["expected"].round(0).tolist(),
                "lower": wg["lower90"].round(0).tolist(),
                "upper": wg["upper90"].round(0).tolist(),
            }
        )
        if tot_excess > best_excess:
            best_excess = tot_excess
            worst_idx = i
    return weeks, worst_idx


def excess_heatmap(g):
    """
    Build an hour-of-day (0-23) x day-of-week (Mon-Sun) grid of total excess
    (actual above the upper band), in kWh.
    """
    g = g.copy()
    g["excess"] = (g["actual"] - g["upper90"]).clip(lower=0)
    g["hour"] = g["timestamp"].dt.hour
    g["dow"] = g["timestamp"].dt.dayofweek  # 0 = Monday
    grid = (
        g.groupby(["dow", "hour"])["excess"].sum().unstack(fill_value=0.0)
    )
    grid = grid.reindex(index=range(7), columns=range(24), fill_value=0.0)
    return grid.round(1).values.tolist()


def monthly_bars(g):
    """Monthly total actual vs expected (kWh)."""
    g = g.copy()
    g["m"] = g["timestamp"].dt.month
    monthly = g.groupby("m").agg(actual=("actual", "sum"),
                                 expected=("expected", "sum"))
    monthly = monthly.reindex(range(1, 13), fill_value=0.0)
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    return {
        "months": months,
        "actual": monthly["actual"].round(0).tolist(),
        "expected": monthly["expected"].round(0).tolist(),
    }


def other_reason(verdict, row):
    """Plain-language reason a building is NOT ranked."""
    if verdict == "Within expected range":
        return "Model is trustworthy and use is within the expected 90% band."
    if verdict == "Changed since 2016":
        return (f"Higher use spread across {int(row['n_months'])} months: looks "
                "like a baseline change since 2016, not specific waste.")
    if verdict == "Can't judge":
        if not row["trustworthy"]:
            return "Model did not meet the ASHRAE trust bar (CV(RMSE) > 30%) or data too poor."
        return "Not enough evidence to judge."
    return ""


def load_limitations():
    """Read docs/what-we-cant-see.md and return it as rendered HTML (no H1)."""
    path = os.path.join("docs", "what-we-cant-see.md")
    if not os.path.exists(path):
        return "<p>See docs/what-we-cant-see.md.</p>"
    with open(path, encoding="utf-8") as f:
        text = f.read()
    # Drop the first H1 title (the page already has its own <h2>).
    lines = [ln for ln in text.splitlines() if not ln.startswith("# ")]
    return md_to_html("\n".join(lines))


def md_to_html(md):
    """
    Small, dependency-free Markdown to HTML converter for our docs. Handles:
    ## / ### headings, paragraphs, - bullet lists, **bold**, and `code`.
    Blank lines separate blocks; lines within a paragraph are joined with a
    space so hard-wrapped source flows naturally.
    """
    import html as _html
    import re as _re

    def inline(s):
        s = _html.escape(s)
        s = _re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
        s = _re.sub(r"`(.+?)`", r"<code>\1</code>", s)
        return s

    html_parts, para, in_list = [], [], False

    def flush_para():
        nonlocal para
        if para:
            html_parts.append("<p>" + inline(" ".join(para)) + "</p>")
            para = []

    def close_list():
        nonlocal in_list
        if in_list:
            html_parts.append("</ul>")
            in_list = False

    for raw in md.splitlines():
        line = raw.rstrip()
        if not line.strip():
            flush_para(); close_list(); continue
        if line.startswith("### "):
            flush_para(); close_list()
            html_parts.append("<h3>" + inline(line[4:].strip()) + "</h3>")
        elif line.startswith("## "):
            flush_para(); close_list()
            html_parts.append("<h3>" + inline(line[3:].strip()) + "</h3>")
        elif line.lstrip().startswith("- "):
            flush_para()
            if not in_list:
                html_parts.append("<ul>"); in_list = True
            html_parts.append("<li>" + inline(line.lstrip()[2:].strip()) + "</li>")
        else:
            if in_list:  # a continuation line inside a list item
                html_parts[-1] = html_parts[-1][:-5] + " " + inline(line.strip()) + "</li>"
            else:
                para.append(line.strip())
    flush_para(); close_list()
    return "\n".join(html_parts)


def build_payload():
    ranking = pd.read_csv(os.path.join(config.PROCESSED_DIR, "waste_ranking.csv"))
    preds = pd.read_csv(
        os.path.join(config.PROCESSED_DIR, "predictions.csv.gz"),
        parse_dates=["timestamp"],
    )
    meta = pd.read_csv(os.path.join(config.DATA_DIR, config.METADATA_FILE))
    usage = dict(zip(meta["building_id"], meta["primaryspaceusage"].fillna("Unknown")))

    # ---- Headline cards: Confirmed waste only ----
    confirmed = ranking[ranking["verdict"] == "Confirmed waste"]
    cards = {
        "confirmed_count": int(len(confirmed)),
        "confirmed_kwh": float(confirmed["counted_excess_kwh"].sum()),
        "confirmed_dollars": float(confirmed["excess_dollars"].sum()),
        "confirmed_co2_kg": float(confirmed["excess_co2_kg"].sum()),
        "worth_count": int((ranking["verdict"] == "Worth a look").sum()),
        "cant_judge_count": int((ranking["verdict"] == "Can't judge").sum()),
    }

    # ---- Ranked rows (Confirmed waste then Worth a look, each by excess) ----
    ranked = ranking[ranking["verdict"].isin(RANKED_VERDICTS)].copy()
    ranked["verdict_order"] = ranked["verdict"].map(
        {"Confirmed waste": 0, "Worth a look": 1}
    )
    ranked["sort_excess"] = ranked["counted_excess_kwh"].fillna(0)
    # For "Worth a look" buildings that may not have exceedance energy, fall back
    # to warm-day kWh so the sort is still meaningful.
    ranked["sort_excess"] = ranked["sort_excess"].where(
        ranked["sort_excess"] > 0, ranked["warm_day_kwh"].fillna(0)
    )
    ranked = ranked.sort_values(
        ["verdict_order", "sort_excess"], ascending=[True, False]
    )

    buildings = []
    table_rows = []
    for _, row in ranked.iterrows():
        bid = row["building_id"]
        g = preds[preds["building_id"] == bid]
        if g.empty:
            continue
        weeks, worst_idx = worst_week_and_weeks(g)
        detail = {
            "id": bid,
            "type": usage.get(bid, "Unknown"),
            "verdict": row["verdict"],
            "flagged_by": row["flagged_by"],
            "pattern": pattern_text(row),
            "fix": likely_fix(str(row["flagged_by"])),
            "excess_kwh": round(float(row["counted_excess_kwh"] or 0), 0),
            "excess_dollars": round(float(row["excess_dollars"] or 0), 0),
            "excess_co2_kg": round(float(row["excess_co2_kg"] or 0), 0),
            "cvrmse": (None if pd.isna(row["cvrmse"]) else round(float(row["cvrmse"]) * 100, 1)),
            "trustworthy": bool(row["trustworthy"]),
            "weeks": weeks,
            "worst_week": worst_idx,
            "heatmap": excess_heatmap(g),
            "monthly": monthly_bars(g),
        }
        buildings.append(detail)
        table_rows.append(
            {
                "id": bid, "type": detail["type"], "verdict": detail["verdict"],
                "flagged_by": detail["flagged_by"], "pattern": detail["pattern"],
                "fix": detail["fix"], "cvrmse": detail["cvrmse"],
                "excess_kwh": detail["excess_kwh"],
                "excess_dollars": detail["excess_dollars"],
                "excess_co2_kg": detail["excess_co2_kg"],
            }
        )

    # ---- Not-ranked buildings (collapsible), with reasons ----
    others = []
    other_df = ranking[~ranking["verdict"].isin(RANKED_VERDICTS)]
    for _, row in other_df.sort_values("verdict").iterrows():
        others.append(
            {
                "id": row["building_id"],
                "type": usage.get(row["building_id"], "Unknown"),
                "verdict": row["verdict"],
                "reason": other_reason(row["verdict"], row),
            }
        )

    building_types = sorted({r["type"] for r in table_rows})

    return {
        "cards": cards,
        "table": table_rows,
        "buildings": buildings,
        "others": others,
        "building_types": building_types,
        "ranked_verdicts": RANKED_VERDICTS,
        "assumptions": {
            "gas_price_per_kwh": config.GAS_PRICE_PER_KWH,
            "boiler_efficiency": config.BOILER_EFFICIENCY,
            "emission_factor_kg_per_kwh": config.EMISSION_FACTOR_KG_PER_KWH,
        },
        "limitations": load_limitations(),
    }


def render_html(payload):
    """Build the full HTML document with the payload embedded as JSON."""
    data_json = json.dumps(payload)
    # The upload link. When the FastAPI app serves the report, a relative
    # "/upload" works. For the GitHub Pages copy, set HEATCHECK_UPLOAD_URL to the
    # hosted app URL (e.g. https://heat-check.onrender.com/upload) before running.
    upload_url = os.environ.get("HEATCHECK_UPLOAD_URL", "/upload")
    # The HTML/CSS/JS template. Plotly via CDN keeps this file small.
    return (HTML_TEMPLATE
            .replace("__DATA__", data_json)
            .replace("__UPLOAD_URL__", upload_url))


def main():
    payload = build_payload()
    html = render_html(payload)
    os.makedirs("docs", exist_ok=True)
    out = os.path.join("docs", "index.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    size_kb = os.path.getsize(out) / 1024
    print(f"Wrote {out} ({size_kb:.0f} KB)")
    print(f"Ranked buildings: {len(payload['table'])} | "
          f"Confirmed waste: {payload['cards']['confirmed_count']} | "
          f"Other: {len(payload['others'])}")
    print("Open it in a browser, or publish docs/ via GitHub Pages.")


# ---------------------------------------------------------------------------
# HTML template. __DATA__ is replaced with the JSON payload at generation time.
# Kept as one string so the whole tool is a single self-contained file.
# ---------------------------------------------------------------------------
HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Heat Check: Campus Heating Priorities</title>
<link rel="icon" type="image/svg+xml" href="assets/logo.svg" />
<link rel="preconnect" href="https://fonts.googleapis.com" />
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet" />
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js" charset="utf-8"></script>
<style>
  :root {
    /* Heat Check brand palette. */
    --ink: #0B2545;        /* top bar, nav, headings */
    --teal: #0E9F8F;       /* buttons, active nav, accents */
    --teal-text: #00796B;  /* teal text + links (meets 4.5:1 on white) */
    --ember: #E4572E;      /* Confirmed waste */
    --amber: #F2A900;      /* Worth a look (dark text) */
    --violet: #7B61FF;     /* Can't judge */
    --gray: #8896A6;       /* Within expected range + Changed since 2016 */
    --mist: #F4F7FA;       /* page background */
    --card: #ffffff;       /* white cards */
    --border: #DCE3EA;     /* 1px card borders */
    --body-text: #1f2a37;  /* body copy (>= 4.5:1 on mist/white) */
    --muted: #51607a;      /* secondary text (>= 4.5:1 on white) */
  }
  * { box-sizing: border-box; }
  /* Minimum 16px everywhere: set the root to 16px and use rem-based sizes that
     never drop below 1rem for text. */
  html { font-size: 16px; }
  body { margin: 0; font-family: 'Inter', system-ui, -apple-system, sans-serif;
         color: var(--body-text); background: var(--mist); line-height: 1.5;
         font-size: 1rem; font-feature-settings: "tnum" 1; }  /* tabular figures */
  a { color: var(--teal-text); }
  h2, h3 { color: var(--ink); }
  /* Uppercase section labels, kept to 16px for the min-size rule. */
  .eyebrow { text-transform: uppercase; letter-spacing: .06em; font-size: 1rem;
             font-weight: 600; color: var(--muted); margin: 0 0 .5rem; }

  .layout { display: flex; min-height: 100vh; flex-direction: column; }
  /* Top bar with logo + wordmark. */
  header.topbar { display: flex; align-items: center; gap: .6rem; background: var(--ink);
    color: #fff; padding: .7rem 1.25rem; }
  header.topbar img { width: 34px; height: 34px; display: block; }
  header.topbar .wordmark { font-weight: 700; font-size: 1.15rem; letter-spacing: .01em; }
  header.topbar .tagline { color: #AFC0D6; font-size: 1rem; margin-left: .5rem;
    padding-left: .5rem; border-left: 1px solid #33496a; }
  /* Hide the tagline earlier if it would crowd the wordmark. */
  @media (max-width: 860px) { header.topbar .tagline { display: none; } }

  .body { display: flex; flex: 1; min-width: 0; }
  nav { width: 200px; background: var(--ink); padding: 1rem .75rem; flex-shrink: 0; }
  nav button { display: block; width: 100%; text-align: left; padding: .55rem .7rem;
    margin-bottom: .25rem; border: none; border-radius: 8px;
    background: none; font: inherit; font-size: 1rem; cursor: pointer;
    color: #D7E0EC; }
  nav button:hover { background: rgba(255,255,255,.08); color: #fff; }
  /* Active nav: solid darker teal only, no outline. */
  nav button[aria-current="true"] { background: #0A7C6F; color: #ffffff;
    font-weight: 600; }
  nav button:focus-visible { outline: 2px solid #fff; outline-offset: 1px; }

  /* min-width:0 lets this flex child shrink so wide tables never force the page
     to scroll sideways. */
  main { flex: 1; min-width: 0; padding: 1.5rem 2rem; max-width: 1120px; }
  h2 { margin-top: 0; }

  /* Even grid, equal-height cards, 16px gaps, 20px padding. */
  .cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px,1fr));
           gap: 16px; margin-bottom: 1.5rem; align-items: stretch; }
  .card { background: var(--card); border: 1px solid var(--border); border-radius: 10px;
          padding: 20px; display: flex; flex-direction: column; min-width: 0; }
  /* Big number scales to fit the card and never touches the edge. */
  .card .num { font-size: clamp(1.1rem, 4.5vw, 1.9rem); font-weight: 700;
               color: var(--ink); font-variant-numeric: tabular-nums;
               line-height: 1.1; overflow-wrap: anywhere; }
  .card .lbl { color: var(--muted); font-size: 1rem; margin-top: .35rem; }
  .card small { color: var(--muted); font-size: 1rem; display:block; margin-top:.4rem;
                line-height: 1.35; }

  .table-wrap { width: 100%; max-width: 100%; }
  table { border-collapse: collapse; width: 100%; table-layout: auto;
          font-size: 1rem; font-variant-numeric: tabular-nums; }
  th, td { text-align: left; padding: .6rem .7rem; border-bottom: 1px solid var(--border);
           vertical-align: top; overflow-wrap: break-word; word-break: normal;
           hyphens: none; }  /* wrap between words, never mid-word */
  /* Sensible per-column minimum widths so content wraps instead of overflowing. */
  .col-priority { min-width: 68px; width: 72px; }
  .col-building { min-width: 120px; }
  .col-verdict  { min-width: 120px; }
  .col-why      { min-width: 130px; }
  .col-fix      { min-width: 130px; }
  .col-dollars  { min-width: 84px; }
  .col-type     { min-width: 100px; }
  .col-kwh      { min-width: 96px; }
  .col-co2      { min-width: 96px; }
  .col-cvrmse   { min-width: 84px; }
  .col-method   { min-width: 150px; }
  .col-fixfull  { min-width: 180px; }
  /* Right-align numeric columns for dense, readable figures. */
  td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
  th { background: #EAF0F6; color: var(--ink);
       text-transform: uppercase; letter-spacing: .04em; font-size: 1rem;
       font-weight: 600; }
  .th-sort { cursor: pointer; user-select: none; white-space: nowrap; }
  .th-sort:hover { background: #E1EAF2; }
  tbody tr { cursor: pointer; }
  tbody tr:hover { background: #EEF6F5; }
  tbody tr:focus { outline: 2px solid var(--teal); outline-offset: -2px; }
  /* Building column: bold short name, smaller type underneath; no mid-word break. */
  .bname { display: block; font-weight: 600; color: var(--ink); overflow-wrap: break-word; }
  .btype { display: block; color: var(--muted); font-size: 1rem; }

  /* Column picker popover. */
  .colpicker { position: relative; display: inline-block; }
  .colpicker .menu { position: absolute; z-index: 20; top: 110%; left: 0;
    background: var(--card); border: 1px solid var(--border); border-radius: 10px;
    padding: .6rem .8rem; box-shadow: 0 6px 20px rgba(11,37,69,.12);
    min-width: 210px; }
  .colpicker .menu label { display: flex; gap: .5rem; align-items: center;
    font-size: .88rem; color: var(--body-text); padding: .2rem 0; cursor: pointer; }
  .colpicker .menu[hidden] { display: none; }

  /* Short "why flagged" tags. Wrap onto multiple lines inside the cell. */
  .tags { display: flex; flex-wrap: wrap; gap: .25rem; max-width: 100%; }
  .tag { display: inline-block; max-width: 100%; background: #EEF2F7; color: var(--ink);
    border: 1px solid var(--border); border-radius: 6px; padding: .1rem .45rem;
    font-size: 1rem; line-height: 1.25; white-space: normal; overflow-wrap: break-word; }

  /* Stacked card view (used below 900px). Hidden by default. */
  .stack { display: none; }
  .stack .srow { background: var(--card); border: 1px solid var(--border);
    border-radius: 10px; padding: 14px 16px; margin-bottom: 10px; cursor: pointer; }
  .stack .srow:focus { outline: 2px solid var(--teal); }
  .stack .srow .sline { display: flex; justify-content: space-between; gap: .75rem;
    padding: .2rem 0; font-size: 1rem; }
  .stack .srow .sline .k { color: var(--muted); }
  .stack .srow .sname { font-weight: 600; color: var(--ink); margin-bottom: .3rem;
    overflow-wrap: anywhere; }

  /* Badges: small text, so backgrounds use slightly darker shades of the brand
     hues so WHITE text clears 4.5:1 (amber keeps dark text). The palette's base
     hues are still used for larger elements (buttons, charts, accents). */
  .badge { display: inline-block; max-width: 100%; padding: .15rem .55rem;
           border-radius: 12px; font-size: 1rem; font-weight: 600; color: #fff;
           line-height: 1.25; white-space: normal; overflow-wrap: break-word; }
  .b-confirmed { background: #C7461F; }  /* ember, darkened: 4.86:1 */
  .b-worth { background: var(--amber); color: #3a2b00; }   /* dark text on amber: 6.85:1 */
  .b-within { background: #5F6D7D; }     /* gray, darkened: 5.29:1 */
  .b-changed { background: #5F6D7D; }    /* gray, darkened: 5.29:1 */
  .b-cant { background: #6A4BEF; }       /* violet, darkened: 5.43:1 */

  .filters { display: flex; gap: 1rem; margin-bottom: 1rem; flex-wrap: wrap; align-items:end; }
  .filters > div { display: flex; flex-direction: column; justify-content: flex-end; }
  .flabel { font-size: 1rem; font-weight: 600; display:block; color: var(--ink);
            margin-bottom: .3rem; }
  /* Controls share one height (40px) and vertical alignment. */
  select, .btn, .btn-outline { height: 40px; font: inherit; font-size: 1rem;
                 border-radius: 8px; }
  select, .btn { padding: 0 .7rem; border: 1px solid var(--border); background:#fff;
                 color: var(--body-text); }
  /* Native select with a custom teal chevron (~14px) and room on the right. */
  select { -webkit-appearance: none; -moz-appearance: none; appearance: none;
    padding-right: 34px;  /* 14px chevron + 12px gap + room */
    background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='14' height='14' viewBox='0 0 24 24' fill='none' stroke='%230E9F8F' stroke-width='3' stroke-linecap='round' stroke-linejoin='round'><polyline points='6 9 12 15 18 9'/></svg>");
    background-repeat: no-repeat; background-position: right 12px center; }
  .btn { cursor: pointer; background: #0A7C6F; color: #fff; border-color: #0A7C6F;
         font-weight: 600; display: inline-flex; align-items: center; }
  .btn:hover { background: #097063; }
  /* Outlined variant: teal border + text on white, with a small icon. */
  .btn-outline { cursor: pointer; background: #fff; color: var(--teal-text);
    border: 1px solid var(--teal); font-weight: 600;
    padding: 0 .8rem; display: inline-flex; align-items: center; gap: .45rem; }
  .btn-outline:hover { background: #F0FBF9; }
  .btn-outline svg { flex-shrink: 0; }
  /* Column checkbox list: checked boxes use the brand teal. */
  .colpicker .menu label { font-size: 1rem; }
  .colpicker .menu input[type="checkbox"] { accent-color: var(--teal); width: 17px;
    height: 17px; }
  details { margin-top: 1.5rem; border: 1px solid var(--border); border-radius: 10px;
            padding: .5rem 1rem; background: var(--card); }
  summary { cursor: pointer; font-weight: 600; padding: .3rem 0; color: var(--ink); }
  .chart { width: 100%; height: 380px; margin: 1rem 0; background: var(--card);
           border: 1px solid var(--border); border-radius: 10px; }
  .meta-line { color: var(--muted); margin: .25rem 0 1rem; }
  pre.notes { white-space: pre-wrap; background: var(--card); padding: 1rem;
              border-radius: 10px; border: 1px solid var(--border); font-family: inherit; }
  /* Rendered prose for doc-driven sections (e.g. "What we can't see"). */
  .prose { max-width: 70ch; }
  .prose h3 { margin: 1.3rem 0 .35rem; }
  .prose p { margin: 0 0 .5rem; }
  .prose strong { color: var(--ink); }
  .back { margin-bottom: 1rem; }
  .sr-only { position:absolute; width:1px; height:1px; overflow:hidden; clip:rect(0 0 0 0); }

  /* The "some columns hidden" note only appears in the narrow-table range. */
  .cols-hidden-note { display: none; color: var(--muted); font-size: 1rem;
    margin: -.25rem 0 .75rem; }

  /* Below ~1300px: auto-hide the optional/wide columns even if selected, so the
     remaining columns have room and nothing overflows. Both the header and its
     cells carry the same col-* class, so they hide together and stay aligned. */
  @media (max-width: 1300px) {
    .col-cvrmse, .col-type, .col-co2, .col-kwh, .col-method, .col-fixfull { display: none; }
    .cols-hidden-note { display: block; }
  }

  /* Below ~1100px: swap the table for stacked cards (no sideways scroll). The
     stacked cards show every selected field, so nothing is lost there. */
  @media (max-width: 1100px) {
    .table-wrap { display: none; }
    .stack { display: block; }
    .cols-hidden-note { display: none; }
  }

  /* Phone layout: nav becomes a top bar, hide the tagline so the header fits. */
  @media (max-width: 720px) {
    .body { flex-direction: column; }
    nav { width: 100%; display: flex; flex-wrap: wrap; gap: .25rem; }
    nav button { width: auto; flex: 1 1 auto; text-align: center; }
    main { padding: 1rem; }
    header.topbar .tagline { display: none; }
    header.topbar { padding: .7rem 1rem; }
  }
</style>
</head>
<body>
<div class="layout">
  <header class="topbar">
    <img src="assets/logo.svg" alt="" />
    <span class="wordmark">Heat Check</span>
    <span class="tagline">Find which buildings waste heat, and what to fix first.</span>
  </header>
  <div class="body">
    <nav aria-label="Main">
      <button id="nav-priorities" aria-current="true" onclick="show('priorities')">Priorities</button>
      <button id="nav-detail" onclick="show('detail')">Building detail</button>
      <button id="nav-method" onclick="show('method')">Method</button>
      <button id="nav-limits" onclick="show('limits')">What we can't see</button>
      <button id="nav-data" onclick="show('data')">Data</button>
      <a id="nav-upload" href="__UPLOAD_URL__" style="display:block;text-decoration:none;">
        <button type="button">Upload your data ↗</button></a>
    </nav>
    <main id="main"></main>
  </div>
</div>
<script>
const DATA = __DATA__;
const fmt = n => (n==null? "-" : Number(n).toLocaleString());
const money = n => (n==null? "-" : "$" + Number(n).toLocaleString());
const BADGE = {
  "Confirmed waste":"b-confirmed","Worth a look":"b-worth",
  "Within expected range":"b-within","Changed since 2016":"b-changed","Can't judge":"b-cant"
};
function badge(v){ return `<span class="badge ${BADGE[v]||''}">${v}</span>`; }
function esc(s){ return String(s==null?'':s).replace(/[&<>"]/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }
function attr(s){ return esc(s).replace(/'/g,'&#39;'); }

// Drop the "Hog_" site prefix from building names (site is already stated).
function shortName(id){ return String(id).replace(/^Hog_/, ''); }
// Just the final name part, e.g. "Hog_education_Caridad" -> "Caridad".
function leafName(id){
  const parts = String(id).split('_');
  return parts[parts.length - 1] || String(id);
}

// Short "why flagged" tags from the flagged_by string.
function whyTags(r){
  const f = (r.flagged_by||'').toLowerCase();
  const tags = [];
  if(f.includes('exceedance')) tags.push('Above expected');
  // \u2011 = non-breaking hyphen so "Warm-day" never splits at the hyphen.
  if(f.includes('warm day') || f.includes('warm-day')) tags.push('Warm\u2011day heating');
  if(f.includes('setback')) tags.push('No setback');
  if(f.includes('level shift')) tags.push('Level shift');
  if(!tags.length) tags.push('-');
  return tags;
}

// Column definitions. "Default" ones show on load; the rest are opt-in.
// `always` columns can't be hidden. VERDICT_ORDER drives the default priority.
const VERDICT_ORDER = { "Confirmed waste":0, "Worth a look":1,
  "Within expected range":2, "Changed since 2016":3, "Can't judge":4 };
const COLUMNS = [
  { key:'priority', label:'Priority', def:true, always:true, num:true },
  { key:'building', label:'Building', def:true,  always:true },
  { key:'verdict',  label:'Verdict',  def:true,  always:true },
  { key:'why',      label:'Why flagged', def:true },
  { key:'fix',      label:'Likely fix', def:true },
  { key:'dollars',  label:'$/yr', def:true, num:true },
  { key:'type',     label:'Type', def:false },
  { key:'kwh',      label:'Excess kWh', def:false, num:true },
  { key:'co2',      label:'kg CO2', def:false, num:true },
  { key:'cvrmse',   label:'CV(RMSE)', def:false, num:true },
  { key:'method',   label:'Flagged by (method)', def:false },
  { key:'fixfull',  label:'Full likely fix', def:false },
];
// Sort value for a column (numeric where possible; strings compared lexically).
function sortVal(r, key){
  switch(key){
    case 'priority': return r._priority;
    case 'building': return leafName(r.id).toLowerCase();
    case 'verdict':  return VERDICT_ORDER[r.verdict] ?? 99;
    case 'why':      return whyTags(r).join(', ').toLowerCase();
    case 'fix':      return shortFix(r.fix).toLowerCase();
    case 'fixfull':  return (r.fix||'').toLowerCase();
    case 'dollars':  return r.excess_dollars ?? -1;
    case 'type':     return (r.type||'').toLowerCase();
    case 'kwh':      return r.excess_kwh ?? -1;
    case 'co2':      return r.excess_co2_kg ?? -1;
    case 'cvrmse':   return r.cvrmse ?? 1e9;
    case 'method':   return (r.flagged_by||'').toLowerCase();
    default: return '';
  }
}
// Plain-text value for CSV export.
function rawVal(r, key){
  switch(key){
    case 'priority': return r._priority;
    case 'building': return leafName(r.id);
    case 'verdict':  return r.verdict;
    case 'why':      return whyTags(r).join('; ');
    case 'fix':      return shortFix(r.fix);
    case 'fixfull':  return r.fix||'';
    case 'dollars':  return r.excess_dollars ?? '';
    case 'type':     return r.type||'';
    case 'kwh':      return r.excess_kwh ?? '';
    case 'co2':      return r.excess_co2_kg ?? '';
    case 'cvrmse':   return (r.cvrmse==null?'':r.cvrmse);
    case 'method':   return r.flagged_by||'';
    default: return '';
  }
}
const COL_STORE_KEY = 'heatcheck.columns.v1';

function loadCols(){
  // Defaults, overridden by a saved choice when storage is available.
  let chosen = COLUMNS.filter(c=>c.def).map(c=>c.key);
  try {
    const raw = localStorage.getItem(COL_STORE_KEY);
    if(raw){ const saved = JSON.parse(raw); if(Array.isArray(saved) && saved.length) chosen = saved; }
  } catch(e){ /* storage blocked, fall back to defaults */ }
  return new Set(chosen);
}
function saveCols(set){
  try { localStorage.setItem(COL_STORE_KEY, JSON.stringify([...set])); }
  catch(e){ /* storage blocked, in-memory only */ }
}

let state = { type:"All", verdict:"All", building:null, cols:null,
              sortKey:"priority", sortDir:1 };
function colSet(){ if(!state.cols) state.cols = loadCols(); return state.cols; }

// Cell value for a column key, as HTML.
function cellHTML(r, key){
  switch(key){
    case 'priority': return r._priority;
    case 'building': return `<span class="bname">${esc(leafName(r.id))}</span>`
                          + `<span class="btype">${esc(r.type)}</span>`;
    case 'verdict':  return badge(r.verdict);
    case 'why':      return `<span class="tags">${whyTags(r).map(t=>`<span class="tag">${esc(t)}</span>`).join('')}</span>`;
    case 'fix':      return `<span title="${attr(r.fix)}">${esc(shortFix(r.fix))}</span>`;
    case 'fixfull':  return esc(r.fix);
    case 'dollars':  return fmt(r.excess_dollars);
    case 'type':     return esc(r.type);
    case 'kwh':      return fmt(r.excess_kwh);
    case 'co2':      return fmt(r.excess_co2_kg);
    case 'cvrmse':   return (r.cvrmse==null?'-':r.cvrmse+'%');
    case 'method':   return esc(r.flagged_by);
    default: return '';
  }
}
// A few-word version of the likely fix (full text shown on hover).
function shortFix(fix){
  if(!fix) return '-';
  const map = {
    'Reprogram BMS schedule (near zero cost)':'BMS schedule',
    'Outdoor-temp heating lockout, check valves (low cost)':'Temp lockout + valves',
    'Investigate controls and steam traps':'Check controls/traps',
  };
  return map[fix] || fix.split(/[(,]/)[0].trim();
}

function show(view){
  ["priorities","detail","method","limits","data"].forEach(v=>{
    const b=document.getElementById("nav-"+v);
    if(b) b.setAttribute("aria-current", v===view ? "true":"false");
  });
  if(view==="priorities") renderPriorities();
  else if(view==="detail") renderDetail();
  else if(view==="method") renderMethod();
  else if(view==="limits") renderLimits();
  else if(view==="data") renderData();
  window.scrollTo(0,0);
}

// Attach the default-order priority number once (1,2,3... in DATA.table order).
DATA.table.forEach((r,i)=>{ r._priority = i+1; });

function sortedFilteredRows(){
  let rows = DATA.table.filter(r =>
    (state.type==="All"||r.type===state.type) &&
    (state.verdict==="All"||r.verdict===state.verdict));
  const k = state.sortKey, dir = state.sortDir;
  rows = rows.slice().sort((a,b)=>{
    const va = sortVal(a,k), vb = sortVal(b,k);
    if(va<vb) return -1*dir; if(va>vb) return 1*dir;
    return (a._priority-b._priority); // stable tiebreak by default order
  });
  return rows;
}

function sortBy(key){
  if(state.sortKey===key){ state.sortDir *= -1; }
  else { state.sortKey = key; state.sortDir = 1; }
  renderPriorities();
}
function sortArrow(key){
  if(state.sortKey!==key) return '';
  return state.sortDir===1 ? ' ▲' : ' ▼';
}

function renderPriorities(){
  const c = DATA.cards;
  const types = ["All", ...DATA.building_types];
  const verdicts = ["All", ...DATA.ranked_verdicts];
  const rows = sortedFilteredRows();

  const cols = colSet();
  const active = COLUMNS.filter(cd => cd.always || cols.has(cd.key));

  const html = `
  <p class="eyebrow">Campus overview</p>
  <h2>Priorities</h2>
  <p class="meta-line">Sorted by evidence strength, then dollars wasted. Click a column header to re-sort.</p>
  <div class="cards">
    <div class="card"><div class="num">${fmt(c.confirmed_count)}</div><div class="lbl">Confirmed waste buildings</div></div>
    <div class="card"><div class="num">${money(Math.round(c.confirmed_dollars))}/yr</div><div class="lbl">$/yr wasted</div><small>conservative: energy above the 90% upper bound</small></div>
    <div class="card"><div class="num">${fmt(Math.round(c.confirmed_kwh))}</div><div class="lbl">kWh/yr wasted</div><small>conservative: energy above the 90% upper bound</small></div>
    <div class="card"><div class="num">${fmt(c.worth_count)}</div><div class="lbl">Worth a look</div></div>
    <div class="card"><div class="num">${fmt(c.cant_judge_count)}</div><div class="lbl">Can't judge</div></div>
  </div>
  <div class="filters">
    <div><label class="flabel" for="f-type">Building type</label>
      <select id="f-type" onchange="state.type=this.value; renderPriorities()">
        ${types.map(t=>`<option ${t===state.type?'selected':''}>${esc(t)}</option>`).join('')}
      </select></div>
    <div><label class="flabel" for="f-verdict">Verdict</label>
      <select id="f-verdict" onchange="state.verdict=this.value; renderPriorities()">
        ${verdicts.map(v=>`<option ${v===state.verdict?'selected':''}>${esc(v)}</option>`).join('')}
      </select></div>
    <div class="colpicker">
      <button class="btn-outline" aria-expanded="false" onclick="toggleColMenu(event)">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="4" y1="6" x2="20" y2="6"/><circle cx="9" cy="6" r="2" fill="#fff"/><line x1="4" y1="12" x2="20" y2="12"/><circle cx="15" cy="12" r="2" fill="#fff"/><line x1="4" y1="18" x2="20" y2="18"/><circle cx="8" cy="18" r="2" fill="#fff"/></svg>
        Customize columns (${active.length} of ${COLUMNS.length})
      </button>
      <div class="menu" id="col-menu" hidden>
        ${COLUMNS.filter(cd=>!cd.always).map(cd=>`
          <label><input type="checkbox" ${cols.has(cd.key)?'checked':''}
            onchange="toggleCol('${cd.key}', this.checked)"> ${esc(cd.label)}</label>`).join('')}
      </div>
    </div>
    <div class="colpicker">
      <button class="btn-outline" onclick="exportCSV()">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v12"/><path d="M7 10l5 5 5-5"/><path d="M5 21h14"/></svg>
        Export CSV
      </button>
    </div>
  </div>

  <p class="cols-hidden-note">Some columns are hidden at this screen width. Widen
  the window, or see the full detail on each building's page.</p>
  <div class="table-wrap">
    <table>
      <thead><tr>
        ${active.map(cd=>`<th scope="col" class="th-sort col-${cd.key} ${cd.num?'num':''}" ${state.sortKey===cd.key?'aria-sort="'+(state.sortDir===1?'ascending':'descending')+'"':''} onclick="sortBy('${cd.key}')">${esc(cd.label)}${sortArrow(cd.key)}</th>`).join('')}
      </tr></thead>
      <tbody>
      ${rows.map(r=>`
        <tr tabindex="0" role="button" onclick="openBuilding('${attr(r.id)}')" onkeydown="if(event.key==='Enter')openBuilding('${attr(r.id)}')">
          ${active.map(cd=>`<td class="col-${cd.key} ${cd.num?'num':''}">${cellHTML(r, cd.key)}</td>`).join('')}
        </tr>`).join('')}
      </tbody>
    </table>
    ${rows.length===0?'<p>No buildings match these filters.</p>':''}
  </div>

  <div class="stack">
    ${rows.length===0?'<p>No buildings match these filters.</p>':''}
    ${rows.map(r=>`
      <div class="srow" tabindex="0" role="button" onclick="openBuilding('${attr(r.id)}')" onkeydown="if(event.key==='Enter')openBuilding('${attr(r.id)}')">
        <div class="sname"><span class="bname">${esc(leafName(r.id))}</span> ${badge(r.verdict)}</div>
        <div class="btype" style="margin-bottom:.3rem">${esc(r.type)}</div>
        ${active.filter(cd=>cd.key!=='building'&&cd.key!=='verdict').map(cd=>`
          <div class="sline"><span class="k">${esc(cd.label)}</span><span>${cellHTML(r, cd.key)}</span></div>`).join('')}
      </div>`).join('')}
  </div>

  <details>
    <summary>Buildings we don't rank (${DATA.others.length}), and why</summary>
    <div class="table-wrap">
      <table>
        <thead><tr><th scope="col">Building</th><th scope="col">Type</th><th scope="col">Verdict</th><th scope="col">Reason</th></tr></thead>
        <tbody>
        ${DATA.others.map(o=>`<tr><td><span class="bname">${esc(leafName(o.id))}</span><span class="btype">${esc(o.type)}</span></td><td>${esc(o.type)}</td><td>${badge(o.verdict)}</td><td>${esc(o.reason)}</td></tr>`).join('')}
        </tbody>
      </table>
    </div>
    <div class="stack">
      ${DATA.others.map(o=>`
        <div class="srow">
          <div class="sname"><span class="bname">${esc(leafName(o.id))}</span> ${badge(o.verdict)}</div>
          <div class="sline"><span class="k">Type</span><span>${esc(o.type)}</span></div>
          <div class="sline"><span class="k">Reason</span><span>${esc(o.reason)}</span></div>
        </div>`).join('')}
    </div>
  </details>`;
  document.getElementById("main").innerHTML = html;
}

function toggleColMenu(ev){
  ev.stopPropagation();
  const m = document.getElementById('col-menu');
  if(m) m.hidden = !m.hidden;
}
function toggleCol(key, on){
  const s = colSet();
  if(on) s.add(key); else s.delete(key);
  saveCols(s);
  renderPriorities();
  // Re-open the menu after re-render so multiple toggles are easy.
  const m = document.getElementById('col-menu'); if(m) m.hidden = false;
}
// Close the column menu when clicking elsewhere.
document.addEventListener('click', e=>{
  const m = document.getElementById('col-menu');
  if(m && !m.hidden && !e.target.closest('.colpicker')) m.hidden = true;
});

// Export the CURRENT view (filters + sort + visible columns) as CSV.
function exportCSV(){
  const cols = colSet();
  const active = COLUMNS.filter(cd => cd.always || cols.has(cd.key));
  const rows = sortedFilteredRows();
  const today = new Date().toISOString().slice(0,10);
  const q = s => {
    const v = String(s==null?'':s);
    return /[",\n]/.test(v) ? '"'+v.replace(/"/g,'""')+'"' : v;
  };
  const lines = [];
  // First line is a comment with date, site, and the conservative-excess note.
  lines.push('# Heat Check priorities, ' + today + ', site Hog. '
    + 'Excess is conservative: energy above the 90% upper bound');
  lines.push(active.map(cd=>q(cd.label)).join(','));
  rows.forEach(r=> lines.push(active.map(cd=>q(rawVal(r, cd.key))).join(',')));
  const blob = new Blob([lines.join('\n')], {type:'text/csv'});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'heat-check-priorities.csv';
  document.body.appendChild(a); a.click();
  document.body.removeChild(a); URL.revokeObjectURL(a.href);
}

function openBuilding(id){ state.building = id; show('detail'); }

function renderDetail(){
  const main = document.getElementById("main");
  if(!state.building) state.building = DATA.buildings.length ? DATA.buildings[0].id : null;
  const b = DATA.buildings.find(x=>x.id===state.building);
  if(!b){ main.innerHTML = "<h2>Building detail</h2><p>No ranked building selected.</p>"; return; }

  const picker = b.weeks.map((w,i)=>`<option value="${i}" ${i===b.worst_week?'selected':''}>${w.label}${i===b.worst_week?' (worst week)':''}</option>`).join('');
  main.innerHTML = `
    <div class="back"><button class="btn" onclick="show('priorities')">&larr; Back to priorities</button></div>
    <h2>${esc(leafName(b.id))}</h2>
    <p class="meta-line">${b.type} · ${badge(b.verdict)} ·
      Model trust: ${b.trustworthy?'trustworthy':'not trustworthy'}${b.cvrmse!=null?` (CV(RMSE) ${b.cvrmse}%)`:''} ·
      Likely fix: <strong>${b.fix}</strong></p>
    <h3>Actual vs expected steam, with 90% band (kWh)</h3>
    <div class="filters">
      <div><label class="flabel" for="wk">Week</label>
        <select id="wk" onchange="drawWeek('${b.id}', this.value)">${picker}</select></div>
    </div>
    <div id="chart-week" class="chart" role="img" aria-label="Actual vs expected steam with 90% band"></div>
    <h3>Excess by hour of day and day of week (kWh)</h3>
    <div id="chart-heat" class="chart" role="img" aria-label="Heatmap of excess steam"></div>
    <h3>Monthly actual vs expected (kWh)</h3>
    <div id="chart-month" class="chart" role="img" aria-label="Monthly actual vs expected bars"></div>`;
  drawWeek(b.id, b.worst_week);
  drawHeat(b);
  drawMonth(b);
}

// Chart colors: actual (over-use) stands out in ember; the expected baseline is
// a soft gray and the 90% band is light gray, so actual reads clearly.
const C_ACTUAL   = '#E4572E';              // ember
const C_EXPECTED = '#B8C2CC';              // soft gray
const C_BANDFILL = 'rgba(184,194,204,0.30)'; // light gray band

// Base layout: no chart title (the section heading covers it), Inter font,
// legend at the top-right above the plot.
function baseLayout(xt, yt){
  return {
    margin:{t:34, r:16, b:52, l:64},
    font:{family:'Inter, system-ui, sans-serif', color:'#1f2a37', size:13},
    paper_bgcolor:'#ffffff', plot_bgcolor:'#ffffff',
    xaxis:{title:xt ? {text:xt, standoff:12} : undefined, automargin:true},
    yaxis:{title:yt ? {text:yt, standoff:8} : undefined, automargin:true},
    legend:{orientation:'h', x:1, xanchor:'right', y:1.12, yanchor:'bottom'},
  };
}

function drawWeek(id, idx){
  const b = DATA.buildings.find(x=>x.id===id); const w = b.weeks[idx];
  const band = {x:w.t.concat([...w.t].reverse()), y:w.upper.concat([...w.lower].reverse()),
    fill:'toself', fillcolor:C_BANDFILL, line:{color:'rgba(0,0,0,0)'},
    name:'90% band', hoverinfo:'skip'};
  const exp = {x:w.t, y:w.expected, name:'Expected', mode:'lines', line:{color:C_EXPECTED, width:2}};
  const act = {x:w.t, y:w.actual, name:'Actual', mode:'lines', line:{color:C_ACTUAL, width:2}};
  const layout = baseLayout(undefined, 'Steam (kWh)');
  // Real date axis: one tick per day, horizontal labels like "Mon Oct 30".
  layout.xaxis = {type:'date', dtick:86400000, tickformat:'%a %b %-d',
    tickangle:0, automargin:true, ticklabelmode:'period'};
  Plotly.newPlot('chart-week', [band,exp,act], layout, {displayModeBar:false, responsive:true});
}
function drawHeat(b){
  const days=['Mon','Tue','Wed','Thu','Fri','Sat','Sun'];
  const hours=[...Array(24).keys()];
  // Label every 3 hours: 12a, 3a, 6a, 9a, 12p, 3p, 6p, 9p.
  const ampm = h => { const p=h<12?'a':'p'; let hr=h%12; if(hr===0)hr=12; return hr+p; };
  const tickvals = [0,3,6,9,12,15,18,21];
  const layout = baseLayout('Hour of day', 'Day of week');
  layout.xaxis = {title:{text:'Hour of day', standoff:14}, tickmode:'array',
    tickvals:tickvals, ticktext:tickvals.map(ampm), tickangle:0, automargin:true};
  layout.margin = {t:20, r:16, b:60, l:64};
  Plotly.newPlot('chart-heat', [{z:b.heatmap, x:hours, y:days, type:'heatmap',
    colorscale:[[0,'#F4F7FA'],[1,C_ACTUAL]], colorbar:{title:'kWh'}}],
    layout, {displayModeBar:false, responsive:true});
}
function drawMonth(b){
  const m=b.monthly;
  const act={x:m.months, y:m.actual, type:'bar', name:'Actual', marker:{color:C_ACTUAL}};
  const exp={x:m.months, y:m.expected, type:'bar', name:'Expected', marker:{color:C_EXPECTED}};
  const layout = baseLayout('Month', 'Steam (kWh)'); layout.barmode='group';
  Plotly.newPlot('chart-month', [act,exp], layout, {displayModeBar:false, responsive:true});
}

function renderMethod(){
  document.getElementById("main").innerHTML = `
    <h2>Method</h2>
    <p>Heat Check runs as a small local pipeline, one step per stage:</p>
    <ol>
      <li><strong>Data pipeline:</strong> load building metadata, hourly steam meters,
      and weather for one site (Hog); clean and quality-check each building (missing,
      zeros in the heating season, stuck meters, spikes).</li>
      <li><strong>Weather-normalized baseline:</strong> for each good building, a
      model predicts expected hourly steam from outdoor temperature (and a 24-hour
      rolling mean), hour of day, weekend, month, and holiday/academic break. Trained
      on 2016, tested on 2017.</li>
      <li><strong>Calibrated uncertainty:</strong> split <em>conformal</em> prediction
      gives a 90% band. We calibrate it separately by season (heating vs summer) and
      on each side, because real errors are skewed. A model is "trustworthy" only if
      it meets ASHRAE Guideline 14 (CV(RMSE) &le; 30%).</li>
      <li><strong>Waste detection:</strong> hours above the band are excess; we also
      run model-free pattern checks (night/weekend setback, warm-day heating).</li>
    </ol>
    <h3>How well the bands hold up</h3>
    <p>On a same-year control (calibrate on half the held-out 2016 weeks, test on the
    other half) the 90% band covers <strong>89.5%</strong> of hours, right on target.
    On 2017 it covers <strong>80.7%</strong>. That gap is real year-over-year change,
    not a miscalibrated band. We deliberately did not widen the bands to force 90% on
    2017, because that would hide the very excess we want to find.</p>
    <h3>Cost and CO2 assumptions (editable)</h3>
    <p>Gas price $${DATA.assumptions.gas_price_per_kwh}/kWh ·
    boiler efficiency ${DATA.assumptions.boiler_efficiency} ·
    emission factor ${DATA.assumptions.emission_factor_kg_per_kwh} kg CO2/kWh.
    Excess is measured conservatively as energy above the 90% upper bound.</p>`;
}
function renderLimits(){
  document.getElementById("main").innerHTML =
    `<p class="eyebrow">Limitations</p><h2>What we can't see</h2>
     <div class="prose">${DATA.limitations}</div>`;
}
function renderData(){
  document.getElementById("main").innerHTML = `
    <h2>Data</h2>
    <p>Source: <strong>Building Data Genome Project 2 (BDG2)</strong>, an open set of
    hourly meter data from non-residential buildings.</p>
    <p><a href="https://github.com/buds-lab/building-data-genome-project-2">github.com/buds-lab/building-data-genome-project-2</a></p>
    <p>Citation: Miller, C., Kathirgamanathan, A., Picchetti, B. et al. The Building
    Data Genome Project 2, energy meter data from the ASHRAE Great Energy Predictor III
    competition. <em>Sci Data</em> 7, 368 (2020).
    <a href="https://doi.org/10.1038/s41597-020-00712-x">doi.org/10.1038/s41597-020-00712-x</a></p>
    <p>Scope: site Hog, steam meters only. Models trained on 2016; all results
    shown are for 2017. Steam in kWh, temperature in C.</p>`;
}
renderPriorities();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
