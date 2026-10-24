# Tech Stack & Conventions

## Stack

| Layer            | Technology                                   |
| ---------------- | -------------------------------------------- |
| Data & ML        | Python 3.13, pandas, scikit-learn            |
| Data exchange    | JSON files exported by the Python script     |
| Frontend         | Plain HTML, CSS, JavaScript (no frameworks)  |
| LLM copilot      | One Vercel serverless function               |
| Hosting          | Vercel free tier, auto-deploy from GitHub    |

## Python (data & ML)

- Target **Python 3.13**.
- Use **pandas** for reading and shaping data, **scikit-learn** for the model.
- The script runs **locally** and its job is to produce a **JSON file** the
  frontend can read. Keep the JSON shape simple (plain objects and arrays).
- Keep dependencies listed in `requirements.txt` with pinned versions.
- Work inside the `.venv` virtual environment (already gitignored).

### Running the Python side
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python <your_script>.py   # writes the JSON output
```

## Frontend (HTML / CSS / JavaScript)

- **No frameworks and no build tools.** Just `.html`, `.css`, and `.js` files
  that run directly in the browser.
- Use plain `fetch()` to load the exported JSON.
- Use modern, readable JavaScript (`const`/`let`, `async`/`await`). Avoid clever
  one-liners.
- Keep styling in a separate `.css` file rather than inline where practical.

## LLM copilot (serverless function)

- Exactly **one** Vercel serverless function handles AI requests.
- The browser calls the function; the function calls the AI provider. The API
  key stays on the server and is never sent to the browser.

## Deployment (Vercel)

- Hosted on the **Vercel free tier**.
- Pushing to the connected **GitHub** branch triggers an automatic deploy.
- Keep the project within free-tier limits (watch function count and usage).

## Code style for a beginner

- Prefer simple, explicit code over abstractions.
- **Comment generously.** Explain the purpose of each section and any step that
  isn't obvious. Assume the reader is new to programming.
- Use descriptive names (`energy_by_month`, not `ebm`).
- Small functions with one clear job.
