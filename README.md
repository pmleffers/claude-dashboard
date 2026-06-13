# Claude Dashboard

A local web dashboard for monitoring [Claude Code](https://claude.ai/code) session stats — cost, token usage, cache efficiency, context window fill, and tool usage — parsed directly from Claude's JSONL session logs.

![Dashboard](https://img.shields.io/badge/Flask-3.x-blue) ![Python](https://img.shields.io/badge/Python-3.8%2B-blue)

## Features

- Per-session breakdown: cost, input/output tokens, cache hit rate, context fill %
- Lifetime totals across all sessions
- Tool usage breakdown per session
- Auto-launches on Claude Code start, auto-closes tab on exit

## Requirements

- Python 3.8+
- Flask (`pip install flask`)

## Setup

### 1. Install dependencies

```bash
pip install flask
```

### 2. Run manually

```bash
python app.py
# → http://127.0.0.1:7778
```

### 3. Auto-launch with Claude Code (optional)

Add hooks to `~/.claude/settings.json` so the dashboard opens when Claude starts and closes when it exits:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "fuser 7778/tcp 2>/dev/null || (cd /path/to/claude-dashboard && nohup python app.py > /tmp/cc-dashboard.log 2>&1 & sleep 1 && xdg-open http://127.0.0.1:7778)",
            "async": true
          }
        ]
      }
    ],
    "SessionEnd": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "fuser -k 7778/tcp 2>/dev/null; pkill -f 'python app.py' 2>/dev/null; true"
          }
        ]
      }
    ]
  }
}
```

Replace `/path/to/claude-dashboard` with the actual path to this repo. On macOS, replace `xdg-open` with `open`.

## How it works

Claude Code writes session data as JSONL files under `~/.claude/projects/`. The dashboard reads those files on each request, aggregates token counts and costs per session, and serves them as a single-page app that polls for updates every 5 seconds. When the Flask server stops, the browser tab closes itself automatically.

## Pricing

Costs are calculated using hardcoded per-model rates for the Claude 4.x family. Update `_PRICING` in `app.py` if rates change.
