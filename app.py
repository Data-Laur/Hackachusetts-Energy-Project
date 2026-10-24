"""
app.py — small self-hosting web app for the Heat Check upload flow (FastAPI).

Routes:
  GET  /          -> serves the precomputed Hog report (docs/index.html).
                     Does NOT run the pipeline on the server.
  GET  /upload    -> branded upload page + sample download buttons.
  POST /upload    -> accept ONE .csv (<= 5 MB), run the existing ingest logic in
                     a temp folder, show the mapping report (or the ambiguous
                     STOP) and the scored table, then delete the temp files.
  GET  /samples/{name} -> download a sample file.
  GET  /healthz   -> liveness check (used by Docker/Render).

Run locally:
    pip install -r requirements.txt
    uvicorn app:app --reload --port 8000
    # then open http://127.0.0.1:8000/

The container runs: uvicorn app:app --host 0.0.0.0 --port $PORT
"""

import html as _html
import os
import shutil
import tempfile

import pandas as pd
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse

import src.ingest as ingest

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.join(APP_DIR, "docs")
SAMPLES = os.path.join(APP_DIR, "samples")
MAX_BYTES = 5 * 1024 * 1024  # 5 MB upload cap

app = FastAPI(title="Heat Check")

# Shared brand bits so the upload pages match the report.
PAGE_HEAD = """<!DOCTYPE html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Heat Check — Upload your data</title>
<link rel="icon" type="image/svg+xml" href="/assets/logo.svg">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
  :root{--ink:#0B2545;--teal:#0E9F8F;--teal-text:#00796B;--ember:#E4572E;
        --mist:#F4F7FA;--card:#fff;--border:#DCE3EA;--body:#1f2a37;--muted:#51607a;}
  *{box-sizing:border-box} body{margin:0;font-family:Inter,system-ui,sans-serif;
    background:var(--mist);color:var(--body);line-height:1.5}
  header{display:flex;align-items:center;gap:.6rem;background:var(--ink);color:#fff;padding:.7rem 1.25rem}
  header img{width:34px;height:34px} header .wordmark{font-weight:700;font-size:1.15rem}
  header .tagline{color:#AFC0D6;font-size:.8rem;margin-left:.5rem;padding-left:.5rem;border-left:1px solid #33496a}
  main{max-width:900px;margin:0 auto;padding:1.5rem}
  a{color:var(--teal-text)} h1,h2,h3{color:var(--ink)}
  .card{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:20px;margin-bottom:1rem}
  .btn{display:inline-block;background:#0A7C6F;color:#fff;border:none;border-radius:8px;
    padding:.5rem .9rem;font:inherit;font-weight:600;cursor:pointer;text-decoration:none}
  .btn:hover{background:#097063}
  .btn-outline{display:inline-block;background:#fff;color:var(--teal-text);border:1px solid var(--teal);
    border-radius:8px;padding:.5rem .9rem;font-weight:600;text-decoration:none;margin-right:.4rem}
  table{border-collapse:collapse;width:100%;font-size:.9rem;font-variant-numeric:tabular-nums}
  th,td{border-bottom:1px solid var(--border);padding:.45rem .6rem;text-align:left;
    overflow-wrap:anywhere;vertical-align:top}
  th{background:#EAF0F6;color:var(--ink);text-transform:uppercase;font-size:.72rem;letter-spacing:.04em}
  pre.notes{white-space:pre-wrap;background:var(--card);border:1px solid var(--border);
    border-radius:10px;padding:1rem;font-family:inherit}
  .stop{border-left:4px solid var(--ember);padding-left:.8rem}
  @media(max-width:720px){header .tagline{display:none}}
</style></head><body>
<header><img src="/assets/logo.svg" alt=""><span class="wordmark">Heat Check</span>
<span class="tagline">Find which buildings waste heat, and what to fix first.</span></header>
<main>"""
PAGE_FOOT = "</main></body></html>"


def _md_to_html(md):
    """Very small markdown renderer (headings, bold, inline code, lists)."""
    out, in_list = [], False
    for line in md.splitlines():
        t = line.rstrip()
        if t.startswith("### "):
            if in_list: out.append("</ul>"); in_list = False
            out.append(f"<h3>{_html.escape(t[4:])}</h3>")
        elif t.startswith("## "):
            if in_list: out.append("</ul>"); in_list = False
            out.append(f"<h2>{_html.escape(t[3:])}</h2>")
        elif t.startswith("# "):
            if in_list: out.append("</ul>"); in_list = False
            out.append(f"<h1>{_html.escape(t[2:])}</h1>")
        elif t.lstrip().startswith("- "):
            if not in_list: out.append("<ul>"); in_list = True
            out.append(f"<li>{_inline(t.lstrip()[2:])}</li>")
        elif t == "":
            if in_list: out.append("</ul>"); in_list = False
        else:
            if in_list: out.append("</ul>"); in_list = False
            out.append(f"<p>{_inline(t)}</p>")
    if in_list: out.append("</ul>")
    return "\n".join(out)


def _inline(s):
    s = _html.escape(s)
    import re
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"`(.+?)`", r"<code>\1</code>", s)
    return s


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/", response_class=HTMLResponse)
def home():
    """Serve the precomputed Hog report."""
    index = os.path.join(DOCS, "index.html")
    if not os.path.exists(index):
        return HTMLResponse("<p>Report not built yet. Run "
                            "<code>python src/report.py</code>.</p>", status_code=503)
    return FileResponse(index)


@app.get("/assets/{name}")
def asset(name: str):
    """Serve report assets (e.g. the logo) so the branding loads."""
    safe = os.path.basename(name)
    p = os.path.join(DOCS, "assets", safe)
    if not os.path.exists(p):
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(p)


@app.get("/samples/{name}")
def sample(name: str):
    """Download a sample CSV."""
    safe = os.path.basename(name)
    p = os.path.join(SAMPLES, safe)
    if not safe.endswith(".csv") or not os.path.exists(p):
        raise HTTPException(status_code=404, detail="sample not found")
    return FileResponse(p, media_type="text/csv", filename=safe)


@app.get("/upload", response_class=HTMLResponse)
def upload_form():
    return HTMLResponse(PAGE_HEAD + """
      <h1>Upload your data</h1>
      <p>Drop a CSV of hourly steam readings. We detect the format, map columns,
      convert units, and score it — or stop and ask if anything is ambiguous. Your
      file is processed in a temporary folder and deleted right after.</p>
      <div class="card">
        <form action="/upload" method="post" enctype="multipart/form-data">
          <p><input type="file" name="file" accept=".csv" required></p>
          <p><button class="btn" type="submit">Score my file</button></p>
          <p style="color:#51607a;font-size:.85rem">CSV only, up to 5 MB.</p>
        </form>
      </div>
      <div class="card">
        <h3>No data handy? Try a sample</h3>
        <a class="btn-outline" href="/samples/sample_A_long_mmbtu.csv">Download sample A (long, MMBtu)</a>
        <a class="btn-outline" href="/samples/sample_B_wide_kwh.csv">Download sample B (wide, kWh)</a>
        <a class="btn-outline" href="/samples/sample_C_ambiguous.csv">Download sample C (ambiguous)</a>
      </div>
      <p><a href="/">&larr; Back to the report</a></p>
    """ + PAGE_FOOT)


def _results_html(result):
    """Render the mapping report + scored table (or the ambiguous stop)."""
    parts = [PAGE_HEAD, "<h1>Results</h1>"]
    if result["ambiguous"]:
        parts.append('<div class="card stop"><h3>We need your input</h3>'
                     "<p>This file is ambiguous, so we stopped instead of "
                     "guessing. Details below.</p></div>")
    parts.append('<div class="card">' + _md_to_html(result["report_md"]) + "</div>")

    summary = result["summary"]
    if summary is not None and len(summary):
        cols = [c for c in ["building_id", "city", "climate", "scored_as",
                            "setback_ratio", "pct_hours_above_18c",
                            "warm_day_share_pct", "warm_day_flag", "warm_day_note"]
                if c in summary.columns]
        head = "".join(f"<th>{_html.escape(c)}</th>" for c in cols)
        body = ""
        for _, r in summary.iterrows():
            body += "<tr>" + "".join(
                f"<td>{_html.escape(str(r[c]))}</td>" for c in cols) + "</tr>"
        parts.append('<div class="card"><h3>Scored buildings</h3>'
                     f"<table><thead><tr>{head}</tr></thead><tbody>{body}"
                     "</tbody></table></div>")
    parts.append('<p><a href="/upload">&larr; Upload another file</a> · '
                 '<a href="/">Back to the report</a></p>')
    parts.append(PAGE_FOOT)
    return "\n".join(parts)


@app.post("/upload", response_class=HTMLResponse)
async def upload_file(file: UploadFile = File(...)):
    # Basic validation: .csv only, 5 MB cap.
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Please upload a .csv file.")
    data = await file.read()
    if len(data) > MAX_BYTES:
        raise HTTPException(status_code=413, detail="File too large (max 5 MB).")

    tmp = tempfile.mkdtemp(prefix="heatcheck_")
    try:
        safe_name = os.path.basename(file.filename)
        src_path = os.path.join(tmp, safe_name)
        with open(src_path, "wb") as f:
            f.write(data)
        # Validate it parses as CSV before scoring.
        try:
            pd.read_csv(src_path, nrows=5)
        except Exception:
            raise HTTPException(status_code=400, detail="Could not read that as CSV.")
        result = ingest.process(src_path, out_dir=os.path.join(tmp, "out"))
        return HTMLResponse(_results_html(result))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)  # delete temp files after
