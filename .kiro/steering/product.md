# Product Overview

The Hackachusetts Energy Project is a small web app for exploring energy data.

## How it works (the big picture)

1. **Data & ML (local, Python):** A Python script reads energy data, analyzes it
   with pandas, trains or runs a scikit-learn model, and **exports the results to
   a JSON file**. This runs on your own computer, not on the server.
2. **Frontend (the website):** Plain HTML, CSS, and JavaScript load that JSON file
   and show the results to visitors. No build step, no frameworks.
3. **LLM copilot:** A single serverless function lets visitors ask questions in
   plain language and get answers from an AI model.
4. **Hosting:** The site lives on Vercel's free tier and redeploys automatically
   whenever changes are pushed to GitHub.

## Who this is for

The person maintaining this project is a beginner who does not normally write
code. Favor clarity over cleverness everywhere: simple logic, plain names, and
comments that explain *why* something is done, not just *what* it does.
