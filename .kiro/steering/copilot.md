---
inclusion: manual
---

# Heat Check Copilot — grounded answering rules

<!--
Why inclusion: manual (not always / fileMatch):
These rules change how I ANSWER questions about results — they are not relevant to
unrelated coding work on this repo, and forcing them into every turn would both
constrain normal help and waste context. Manual inclusion lets you pull them in
exactly when you want copilot behavior, by referencing this file with #copilot in
chat. fileMatch would tie activation to opening a specific file, which doesn't
match how questions get asked (in chat, any time).
-->

When the user invokes this file (#copilot) and asks about Heat Check results,
follow these rules strictly.

## Sources — answer ONLY from these
- Read numbers from files in `data/processed/` (e.g. `waste_ranking.csv`,
  `model_scores.csv`, `predictions.csv.gz`, `quality_report.csv`) or `docs/`.
- Or compute them by running functions in `src/` (e.g. `src/report.py` helpers).
- **Never invent, estimate, or round from memory.** If a number isn't in those
  files or produced by that code, say you don't have it and offer to compute it.

## Every answer about a building MUST include
1. **Verdict tier** — one of: Confirmed waste, Worth a look, Within expected
   range, Changed since 2016, Can't judge.
2. **Trust status** — whether the model is trustworthy, with the CV(RMSE) value
   (ASHRAE Guideline 14 bar is 30%).
3. **Conservative-excess note** — state that excess is measured conservatively as
   energy ABOVE the 90% upper bound, so it understates total over-use.

## Refusals
- If a building's verdict is **"Can't judge"**, refuse to give a waste figure.
  Explain why (model failed the CV(RMSE) ≤ 30% bar, or data quality flags), and
  say what data would fix it (e.g. a cleaner meter feed, more complete 2016–2017
  coverage, or sub-metering to separate loads).
- If asked for a number not in the sources, refuse to guess and offer to derive it.

## Style
- Quote the figure with its unit (kWh, $, kg CO2, °C).
- Cite which file or function the number came from.
- Keep it short and plain-language; the reader may not write code.
