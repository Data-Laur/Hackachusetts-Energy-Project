# Heat Check: Project Rules

These rules apply to all work on the Heat Check project.

- **Never use em dashes in user-facing text.** In the report, upload pages,
  README, docs, and any copy a user sees, use commas, colons, or periods instead
  of the em dash character.

- **Keep code simple and commented for a beginner.** Favor plain, explicit code
  over clever abstractions. Comment the *why*, not just the *what*. The person
  running this does not normally write code.
- **Never hardcode numbers in the UI that weren't computed.** Every figure shown
  in the Streamlit app (or returned by the copilot) must come from the computed
  result files. No typed-in totals, dollars, or counts.
- **Always cite data sources.** When data informs a result or appears in docs,
  cite Building Data Genome Project 2 (Miller et al., Sci Data 7, 368, 2020,
  https://doi.org/10.1038/s41597-020-00712-x).
- **Label all units.** Steam in kWh, temperature in °C, money in $, emissions in
  CO2 mass. Every number carries its unit wherever it is shown or logged.
