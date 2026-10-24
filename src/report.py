"""
report.py — STAGE 4 of Heat Check.

Builds ONE interactive, self-contained web page at docs/index.html from the
computed results. No server and no Streamlit: the page is plain HTML + CSS +
JavaScript, with Plotly loaded from a CDN (keeps the file small). GitHub Pages
can serve docs/index.html directly.

What the page contains:
  - View 1 "Triage": headline cards, a ranked table (Confirmed waste then Worth a
    look), filters, and a collapsible list of the buildings we don't rank.
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
    return "; ".join(parts) if parts else "—"


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
                "t": wg["timestamp"].dt.strftime("%m-%d %H:00").tolist(),
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
        return (f"Higher use spread across {int(row['n_months'])} months — looks "
                "like a baseline change since 2016, not specific waste.")
    if verdict == "Can't judge":
        if not row["trustworthy"]:
            return "Model did not meet the ASHRAE trust bar (CV(RMSE) > 30%) or data too poor."
        return "Not enough evidence to judge."
    return ""


def load_limitations():
    """Read docs/what-we-cant-see.md and return it as text (without the H1)."""
    path = os.path.join("docs", "what-we-cant-see.md")
    if not os.path.exists(path):
        return "See docs/what-we-cant-see.md."
    with open(path, encoding="utf-8") as f:
        lines = f.readlines()
    # Drop the first markdown H1 title; keep the rest.
    body = [ln for ln in lines if not ln.startswith("# ")]
    return "".join(body).strip()


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
                "fix": detail["fix"], "excess_kwh": detail["excess_kwh"],
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
    # The HTML/CSS/JS template. Plotly via CDN keeps this file small.
    return HTML_TEMPLATE.replace("__DATA__", data_json)


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
<title>Heat Check — Campus Heating Triage</title>
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
  body { margin: 0; font-family: 'Inter', system-ui, -apple-system, sans-serif;
         color: var(--body-text); background: var(--mist); line-height: 1.5;
         font-feature-settings: "tnum" 1; }  /* tabular figures */
  a { color: var(--teal-text); }
  h2, h3 { color: var(--ink); }
  /* Small uppercase section labels. */
  .eyebrow { text-transform: uppercase; letter-spacing: .06em; font-size: .72rem;
             font-weight: 600; color: var(--muted); margin: 0 0 .35rem; }

  .layout { display: flex; min-height: 100vh; flex-direction: column; }
  /* Top bar with logo + wordmark. */
  header.topbar { display: flex; align-items: center; gap: .6rem; background: var(--ink);
    color: #fff; padding: .7rem 1.25rem; }
  header.topbar img { width: 30px; height: 30px; display: block; }
  header.topbar .wordmark { font-weight: 700; font-size: 1.15rem; letter-spacing: .01em; }
  header.topbar .tagline { color: #AFC0D6; font-size: .8rem; margin-left: .5rem;
    padding-left: .5rem; border-left: 1px solid #33496a; }

  .body { display: flex; flex: 1; }
  nav { width: 220px; background: var(--ink); padding: 1rem .75rem; flex-shrink: 0; }
  nav button { display: block; width: 100%; text-align: left; padding: .55rem .7rem;
    margin-bottom: .25rem; border: 1px solid transparent; border-radius: 8px;
    background: none; font: inherit; font-size: .92rem; cursor: pointer;
    color: #D7E0EC; }
  nav button:hover { background: rgba(255,255,255,.08); color: #fff; }
  nav button[aria-current="true"] { background: #0A7C6F; color: #ffffff;
    font-weight: 600; }  /* darkened teal so white label clears 4.5:1 (5.09:1) */
  nav button:focus-visible { outline: 2px solid #fff; outline-offset: 1px; }

  main { flex: 1; padding: 1.5rem 2rem; max-width: 1120px; }
  h2 { margin-top: 0; }

  .cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px,1fr));
           gap: 1rem; margin-bottom: 1.5rem; }
  .card { background: var(--card); border: 1px solid var(--border); border-radius: 10px;
          padding: 1rem 1.1rem; }
  .card .num { font-size: 1.8rem; font-weight: 700; color: var(--ink);
               font-variant-numeric: tabular-nums; }
  .card .lbl { color: var(--muted); font-size: .85rem; }
  .card small { color: var(--muted); font-size: .72rem; display:block; margin-top:.3rem; }

  table { border-collapse: collapse; width: 100%; font-size: .9rem;
          font-variant-numeric: tabular-nums; }
  th, td { text-align: left; padding: .5rem .6rem; border-bottom: 1px solid var(--border);
           vertical-align: top; }
  /* Right-align numeric columns for dense, readable figures. */
  td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
  th { background: #EAF0F6; color: var(--ink); position: sticky; top: 0;
       text-transform: uppercase; letter-spacing: .04em; font-size: .72rem; }
  tbody tr { cursor: pointer; }
  tbody tr:hover { background: #EEF6F5; }
  tbody tr:focus { outline: 2px solid var(--teal); outline-offset: -2px; }

  /* Badges: small text, so backgrounds use slightly darker shades of the brand
     hues so WHITE text clears 4.5:1 (amber keeps dark text). The palette's base
     hues are still used for larger elements (buttons, charts, accents). */
  .badge { display: inline-block; padding: .15rem .55rem; border-radius: 999px;
           font-size: .74rem; font-weight: 600; color: #fff; white-space: nowrap; }
  .b-confirmed { background: #C7461F; }  /* ember, darkened: 4.86:1 */
  .b-worth { background: var(--amber); color: #3a2b00; }   /* dark text on amber: 6.85:1 */
  .b-within { background: #5F6D7D; }     /* gray, darkened: 5.29:1 */
  .b-changed { background: #5F6D7D; }    /* gray, darkened: 5.29:1 */
  .b-cant { background: #6A4BEF; }       /* violet, darkened: 5.43:1 */

  .filters { display: flex; gap: 1rem; margin-bottom: 1rem; flex-wrap: wrap; align-items:end; }
  .filters label { font-size: .85rem; display:block; color: var(--muted); }
  select, .btn { padding: .4rem .55rem; font: inherit; font-size: .9rem;
                 border: 1px solid var(--border); border-radius: 8px; background:#fff;
                 color: var(--body-text); }
  .btn { cursor: pointer; background: #0A7C6F; color: #fff; border-color: #0A7C6F;
         font-weight: 600; }  /* darkened teal so white label clears 4.5:1 */
  .btn:hover { background: #097063; }
  details { margin-top: 1.5rem; border: 1px solid var(--border); border-radius: 10px;
            padding: .5rem 1rem; background: var(--card); }
  summary { cursor: pointer; font-weight: 600; padding: .3rem 0; color: var(--ink); }
  .chart { width: 100%; height: 380px; margin: 1rem 0; background: var(--card);
           border: 1px solid var(--border); border-radius: 10px; }
  .meta-line { color: var(--muted); margin: .25rem 0 1rem; }
  pre.notes { white-space: pre-wrap; background: var(--card); padding: 1rem;
              border-radius: 10px; border: 1px solid var(--border); font-family: inherit; }
  .back { margin-bottom: 1rem; }
  .sr-only { position:absolute; width:1px; height:1px; overflow:hidden; clip:rect(0 0 0 0); }

  /* Phone layout: stack nav on top, single-column cards, hide the tagline so it
     doesn't crowd the header. */
  @media (max-width: 720px) {
    .body { flex-direction: column; }
    nav { width: 100%; display: flex; flex-wrap: wrap; gap: .25rem; }
    nav button { width: auto; flex: 1 1 auto; text-align: center; }
    main { padding: 1rem; }
    header.topbar .tagline { display: none; }
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
      <button id="nav-triage" aria-current="true" onclick="show('triage')">Triage</button>
      <button id="nav-detail" onclick="show('detail')">Building detail</button>
      <button id="nav-method" onclick="show('method')">Method</button>
      <button id="nav-limits" onclick="show('limits')">What we can't see</button>
      <button id="nav-data" onclick="show('data')">Data</button>
    </nav>
    <main id="main"></main>
  </div>
</div>
<script>
const DATA = __DATA__;
const fmt = n => (n==null? "—" : Number(n).toLocaleString());
const money = n => (n==null? "—" : "$" + Number(n).toLocaleString());
const BADGE = {
  "Confirmed waste":"b-confirmed","Worth a look":"b-worth",
  "Within expected range":"b-within","Changed since 2016":"b-changed","Can't judge":"b-cant"
};
function badge(v){ return `<span class="badge ${BADGE[v]||''}">${v}</span>`; }

let state = { type:"All", verdict:"All", building:null };

function show(view){
  ["triage","detail","method","limits","data"].forEach(v=>{
    const b=document.getElementById("nav-"+v);
    if(b) b.setAttribute("aria-current", v===view ? "true":"false");
  });
  if(view==="triage") renderTriage();
  else if(view==="detail") renderDetail();
  else if(view==="method") renderMethod();
  else if(view==="limits") renderLimits();
  else if(view==="data") renderData();
  window.scrollTo(0,0);
}

function renderTriage(){
  const c = DATA.cards;
  const types = ["All", ...DATA.building_types];
  const verdicts = ["All", ...DATA.ranked_verdicts];
  let rows = DATA.table.filter(r =>
    (state.type==="All"||r.type===state.type) &&
    (state.verdict==="All"||r.verdict===state.verdict));

  const html = `
  <p class="eyebrow">Campus overview</p>
  <h2>Triage</h2>
  <p class="meta-line">Which buildings waste heat, ranked by evidence strength. Click any row for detail.</p>
  <div class="cards">
    <div class="card"><div class="num">${fmt(c.confirmed_count)}</div><div class="lbl">Confirmed waste buildings</div></div>
    <div class="card"><div class="num">${money(Math.round(c.confirmed_dollars))}/yr</div><div class="lbl">Confirmed waste cost</div><small>conservative: energy above the 90% upper bound</small></div>
    <div class="card"><div class="num">${fmt(Math.round(c.confirmed_kwh))}</div><div class="lbl">kWh/yr (Confirmed waste)</div><small>conservative: energy above the 90% upper bound</small></div>
    <div class="card"><div class="num">${fmt(c.worth_count)}</div><div class="lbl">Worth a look</div></div>
    <div class="card"><div class="num">${fmt(c.cant_judge_count)}</div><div class="lbl">Can't judge</div></div>
  </div>
  <div class="filters">
    <div><label for="f-type">Building type</label>
      <select id="f-type" onchange="state.type=this.value; renderTriage()">
        ${types.map(t=>`<option ${t===state.type?'selected':''}>${t}</option>`).join('')}
      </select></div>
    <div><label for="f-verdict">Verdict</label>
      <select id="f-verdict" onchange="state.verdict=this.value; renderTriage()">
        ${verdicts.map(v=>`<option ${v===state.verdict?'selected':''}>${v}</option>`).join('')}
      </select></div>
  </div>
  <table>
    <thead><tr>
      <th scope="col">Building</th><th scope="col">Type</th><th scope="col">Verdict</th>
      <th scope="col">Flagged by</th><th scope="col">Pattern</th><th scope="col">Likely fix</th>
      <th scope="col" class="num">Excess kWh</th><th scope="col" class="num">$/yr</th><th scope="col" class="num">kg CO2/yr</th>
    </tr></thead>
    <tbody>
    ${rows.map(r=>`
      <tr tabindex="0" role="button" onclick="openBuilding('${r.id}')" onkeydown="if(event.key==='Enter')openBuilding('${r.id}')">
        <td>${r.id}</td><td>${r.type}</td><td>${badge(r.verdict)}</td>
        <td>${r.flagged_by}</td><td>${r.pattern}</td><td>${r.fix}</td>
        <td class="num">${fmt(r.excess_kwh)}</td><td class="num">${fmt(r.excess_dollars)}</td><td class="num">${fmt(r.excess_co2_kg)}</td>
      </tr>`).join('')}
    </tbody>
  </table>
  ${rows.length===0?'<p>No buildings match these filters.</p>':''}
  <details>
    <summary>Buildings we don't rank (${DATA.others.length}) — and why</summary>
    <table>
      <thead><tr><th scope="col">Building</th><th scope="col">Type</th><th scope="col">Verdict</th><th scope="col">Reason</th></tr></thead>
      <tbody>
      ${DATA.others.map(o=>`<tr><td>${o.id}</td><td>${o.type}</td><td>${badge(o.verdict)}</td><td>${o.reason}</td></tr>`).join('')}
      </tbody>
    </table>
  </details>`;
  document.getElementById("main").innerHTML = html;
}

function openBuilding(id){ state.building = id; show('detail'); }

function renderDetail(){
  const main = document.getElementById("main");
  if(!state.building) state.building = DATA.buildings.length ? DATA.buildings[0].id : null;
  const b = DATA.buildings.find(x=>x.id===state.building);
  if(!b){ main.innerHTML = "<h2>Building detail</h2><p>No ranked building selected.</p>"; return; }

  const picker = b.weeks.map((w,i)=>`<option value="${i}" ${i===b.worst_week?'selected':''}>${w.label}${i===b.worst_week?' (worst week)':''}</option>`).join('');
  main.innerHTML = `
    <div class="back"><button class="btn" onclick="show('triage')">&larr; Back to triage</button></div>
    <h2>${b.id}</h2>
    <p class="meta-line">${b.type} · ${badge(b.verdict)} ·
      Model trust: ${b.trustworthy?'trustworthy':'not trustworthy'}${b.cvrmse!=null?` (CV(RMSE) ${b.cvrmse}%)`:''} ·
      Likely fix: <strong>${b.fix}</strong></p>
    <div class="filters">
      <div><label for="wk">Week (actual vs expected)</label>
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

const LAYOUT = (title,xt,yt)=>({title:{text:title, font:{color:'#0B2545', size:15}},
  xaxis:{title:xt}, yaxis:{title:yt}, margin:{t:44,r:20,b:50,l:60},
  font:{family:'Inter, system-ui, sans-serif', color:'#1f2a37'},
  paper_bgcolor:'#ffffff', plot_bgcolor:'#ffffff', legend:{orientation:'h'}});

// Brand chart colors, consistent with the verdict palette:
// teal = expected (baseline), ember = actual (over-use / waste).
const C_EXPECTED = '#0E9F8F';   // teal
const C_ACTUAL   = '#E4572E';   // ember
const C_BANDFILL = 'rgba(14,159,143,0.15)';  // teal-tinted 90% band
function drawWeek(id, idx){
  const b = DATA.buildings.find(x=>x.id===id); const w = b.weeks[idx];
  const band = {x:w.t.concat([...w.t].reverse()), y:w.upper.concat([...w.lower].reverse()),
    fill:'toself', fillcolor:C_BANDFILL, line:{color:'rgba(0,0,0,0)'},
    name:'90% band', hoverinfo:'skip'};
  const exp = {x:w.t, y:w.expected, name:'Expected', mode:'lines', line:{color:C_EXPECTED, width:2}};
  const act = {x:w.t, y:w.actual, name:'Actual', mode:'lines', line:{color:C_ACTUAL, width:2}};
  Plotly.newPlot('chart-week', [band,exp,act], LAYOUT('Actual vs expected steam (kWh) — '+w.label,'Time','Steam (kWh)'), {displayModeBar:false, responsive:true});
}
function drawHeat(b){
  const days=['Mon','Tue','Wed','Thu','Fri','Sat','Sun'];
  const hours=[...Array(24).keys()].map(h=>h+':00');
  Plotly.newPlot('chart-heat', [{z:b.heatmap, x:hours, y:days, type:'heatmap',
    colorscale:[[0,'#F4F7FA'],[1,C_ACTUAL]], colorbar:{title:'kWh'}}],
    LAYOUT('Total excess by hour x day','Hour of day','Day of week'), {displayModeBar:false, responsive:true});
}
function drawMonth(b){
  const m=b.monthly;
  const act={x:m.months, y:m.actual, type:'bar', name:'Actual', marker:{color:C_ACTUAL}};
  const exp={x:m.months, y:m.expected, type:'bar', name:'Expected', marker:{color:C_EXPECTED}};
  Plotly.newPlot('chart-month', [act,exp], {...LAYOUT('Monthly actual vs expected (kWh)','Month','Steam (kWh)'), barmode:'group'}, {displayModeBar:false, responsive:true});
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
    other half) the 90% band covers <strong>89.5%</strong> of hours — right on target.
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
    `<h2>What we can't see</h2><pre class="notes">${DATA.limitations.replace(/</g,'&lt;')}</pre>`;
}
function renderData(){
  document.getElementById("main").innerHTML = `
    <h2>Data</h2>
    <p>Source: <strong>Building Data Genome Project 2 (BDG2)</strong> — an open set of
    hourly meter data from non-residential buildings.</p>
    <p><a href="https://github.com/buds-lab/building-data-genome-project-2">github.com/buds-lab/building-data-genome-project-2</a></p>
    <p>Citation: Miller, C., Kathirgamanathan, A., Picchetti, B. et al. The Building
    Data Genome Project 2, energy meter data from the ASHRAE Great Energy Predictor III
    competition. <em>Sci Data</em> 7, 368 (2020).
    <a href="https://doi.org/10.1038/s41597-020-00712-x">doi.org/10.1038/s41597-020-00712-x</a></p>
    <p>Scope: site Hog, steam meters only. Models trained on 2016; all results
    shown are for 2017. Steam in kWh, temperature in C.</p>`;
}
renderTriage();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
