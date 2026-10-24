# Hackachusetts Energy Project

[![CI](https://github.com/Data-Laur/Hackachusetts-Energy-Project/actions/workflows/ci.yml/badge.svg)](https://github.com/Data-Laur/Hackachusetts-Energy-Project/actions/workflows/ci.yml)

Heat Check: a campus heating copilot that finds where buildings waste heat,
proves it with calibrated uncertainty, and refuses to answer when the evidence is
weak. <!-- Full README is task 7. -->

## MCP setup (fetch server)

To use the fetch MCP server, copy the portable template into your settings:

```bash
mkdir -p .kiro/settings
cp docs/mcp.example.json .kiro/settings/mcp.json
```

On macOS, if the fetch server fails to connect, replace `uvx` with the full path
from `which uvx` (e.g. `/Users/you/.local/bin/uvx`) in `.kiro/settings/mcp.json`.
The local `mcp.json` is gitignored so a machine-specific path never gets
committed.
