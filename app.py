import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, render_template

app = Flask(__name__)

PROJECTS_DIR   = Path.home() / ".claude" / "projects"
_NAMES_FILE    = Path(__file__).parent / "project_names.json"


def _load_project_names():
    try:
        return json.loads(_NAMES_FILE.read_text())
    except Exception:
        return {}

# (input $/M, output $/M, cache_write $/M, cache_read $/M)
_PRICING = {
    "claude-fable-5":    (10.00, 50.00, 12.50, 1.00),
    "claude-mythos-5":   (10.00, 50.00, 12.50, 1.00),
    "claude-opus-4-8":   ( 5.00, 25.00,  6.25, 0.50),
    "claude-opus-4-7":   ( 5.00, 25.00,  6.25, 0.50),
    "claude-opus-4-6":   ( 5.00, 25.00,  6.25, 0.50),
    "claude-opus-4-5":   ( 5.00, 25.00,  6.25, 0.50),
    "claude-sonnet-4-6": ( 3.00, 15.00,  3.75, 0.30),
    "claude-sonnet-4-5": ( 3.00, 15.00,  3.75, 0.30),
    "claude-haiku-4-5":  ( 1.00,  5.00,  1.25, 0.10),
}

_CONTEXT = {
    "claude-fable-5":    1_000_000,
    "claude-mythos-5":   1_000_000,
    "claude-opus-4-8":   1_000_000,
    "claude-opus-4-7":   1_000_000,
    "claude-opus-4-6":   1_000_000,
    "claude-opus-4-5":   1_000_000,
    "claude-sonnet-4-6": 1_000_000,
    "claude-sonnet-4-5": 1_000_000,
    "claude-haiku-4-5":  200_000,
}

_DEFAULT_PRICING = (3.00, 15.00, 3.75, 0.30)
_DEFAULT_CONTEXT = 200_000


def _duration_seconds(start, end):
    if not start or not end:
        return 0
    try:
        s = datetime.fromisoformat(start.replace("Z", "+00:00"))
        e = datetime.fromisoformat(end.replace("Z", "+00:00"))
        return max(0, (e - s).total_seconds())
    except Exception:
        return 0


def _project_name(cwd, fallback, names=None):
    if names and cwd and cwd in names:
        return names[cwd]
    path = cwd or fallback
    for sep in ("/", "\\"):
        if sep in path:
            return path.rstrip(sep).rsplit(sep, 1)[-1]
    return path


def _lookup(table, model, default):
    if model in table:
        return table[model]
    for k in table:
        if model.startswith(k):
            return table[k]
    return default


def _cost(model, in_tok, out_tok, cw_tok, cr_tok):
    p = _lookup(_PRICING, model, _DEFAULT_PRICING)
    M = 1_000_000
    return (
        in_tok  * p[0] / M +
        out_tok * p[1] / M +
        cw_tok  * p[2] / M +
        cr_tok  * p[3] / M
    )


def get_stats():
    sessions     = {}
    project_names = _load_project_names()

    if not PROJECTS_DIR.exists():
        return {
            "sessions": [],
            "totals": {"cost": 0, "sessions": 0, "output_tokens": 0, "cache_hit_rate": 0},
        }

    for jsonl_path in PROJECTS_DIR.glob("*/*.jsonl"):
        try:
            text = jsonl_path.read_text(errors="replace")
        except Exception:
            continue

        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue

            if obj.get("type") != "assistant":
                continue

            msg = obj.get("message", {})
            usage = msg.get("usage")
            if not usage:
                continue

            sid = obj.get("sessionId")
            if not sid:
                continue

            model = msg.get("model", "unknown")
            ts    = obj.get("timestamp", "")
            cwd   = obj.get("cwd", "")

            in_tok  = int(usage.get("input_tokens", 0) or 0)
            out_tok = int(usage.get("output_tokens", 0) or 0)
            cw_tok  = int(usage.get("cache_creation_input_tokens", 0) or 0)
            cr_tok  = int(usage.get("cache_read_input_tokens", 0) or 0)
            total_input = in_tok + cw_tok + cr_tok

            cost = _cost(model, in_tok, out_tok, cw_tok, cr_tok)

            tools = defaultdict(int)
            for item in msg.get("content") or []:
                if isinstance(item, dict) and item.get("type") == "tool_use":
                    tools[item.get("name", "?")] += 1

            if sid not in sessions:
                sessions[sid] = {
                    "project":             jsonl_path.parent.name,
                    "cwd":                 cwd,
                    "model":               model,
                    "start":               ts,
                    "end":                 ts,
                    "messages":            0,
                    "input_tokens":        0,
                    "output_tokens":       0,
                    "cache_write_tokens":  0,
                    "cache_read_tokens":   0,
                    "cost":                0.0,
                    "tools":               defaultdict(int),
                    "last_context_size":   total_input,
                    "context_window":      _lookup(_CONTEXT, model, _DEFAULT_CONTEXT),
                }

            s = sessions[sid]

            if ts:
                if not s["start"] or ts < s["start"]:
                    s["start"] = ts
                if ts > s["end"]:
                    s["end"]               = ts
                    s["last_context_size"] = total_input
                    s["model"]             = model
                    s["context_window"]    = _lookup(_CONTEXT, model, _DEFAULT_CONTEXT)

            s["messages"]           += 1
            s["input_tokens"]       += in_tok
            s["output_tokens"]      += out_tok
            s["cache_write_tokens"] += cw_tok
            s["cache_read_tokens"]  += cr_tok
            s["cost"]               += cost

            for t, c in tools.items():
                s["tools"][t] += c

    result = []
    for sid, s in sessions.items():
        total_cached = s["cache_write_tokens"] + s["cache_read_tokens"]
        total_in     = s["input_tokens"] + total_cached
        cache_rate   = (s["cache_read_tokens"] / total_in * 100) if total_in > 0 else 0
        ctx_pct      = (s["last_context_size"] / s["context_window"] * 100) if s["context_window"] > 0 else 0

        result.append({
            "id":                  sid,
            "project":             s["project"],
            "cwd":                 s["cwd"],
            "model":               s["model"],
            "start":               s["start"],
            "end":                 s["end"],
            "messages":            s["messages"],
            "input_tokens":        s["input_tokens"],
            "output_tokens":       s["output_tokens"],
            "cache_write_tokens":  s["cache_write_tokens"],
            "cache_read_tokens":   s["cache_read_tokens"],
            "cache_hit_rate":      round(cache_rate, 1),
            "cost":                round(s["cost"], 4),
            "tools":               dict(s["tools"]),
            "last_context_size":   s["last_context_size"],
            "context_window":      s["context_window"],
            "context_pct":         round(min(ctx_pct, 100), 1),
        })

    result.sort(key=lambda s: s["end"] or "", reverse=True)

    total_cost = sum(s["cost"] for s in result)
    total_out  = sum(s["output_tokens"] for s in result)
    all_input  = sum(s["input_tokens"] + s["cache_write_tokens"] + s["cache_read_tokens"] for s in result)
    all_cr     = sum(s["cache_read_tokens"] for s in result)
    overall_cr = (all_cr / all_input * 100) if all_input > 0 else 0

    projects = {}
    for s in result:
        key = s["cwd"] or s["project"]
        if key not in projects:
            projects[key] = {
                "name":        _project_name(s["cwd"], s["project"], project_names),
                "path":        key,
                "sessions":    0,
                "cost":        0.0,
                "duration":    0.0,
                "last_active": "",
            }
        p = projects[key]
        p["sessions"] += 1
        p["cost"]     += s["cost"]
        p["duration"] += _duration_seconds(s["start"], s["end"])
        if not p["last_active"] or (s["end"] and s["end"] > p["last_active"]):
            p["last_active"] = s["end"]

    projects_list = sorted(
        [{"name": p["name"], "path": p["path"], "sessions": p["sessions"],
          "cost": round(p["cost"], 4), "duration": round(p["duration"]),
          "last_active": p["last_active"]}
         for p in projects.values()],
        key=lambda p: p["last_active"] or "",
        reverse=True,
    )

    return {
        "sessions": result[:200],
        "projects": projects_list,
        "totals": {
            "cost":          round(total_cost, 4),
            "sessions":      len(result),
            "output_tokens": total_out,
            "cache_hit_rate": round(overall_cr, 1),
        },
    }


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/stats")
def stats():
    return jsonify(get_stats())


if __name__ == "__main__":
    print("Claude Code Dashboard → http://127.0.0.1:7778")
    app.run(host="127.0.0.1", port=7778, debug=False)
