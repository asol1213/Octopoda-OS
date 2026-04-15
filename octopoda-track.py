#!/usr/bin/env python3
"""Octopoda Auto-Tracker — registriert Claude Code Sessions über die Runtime API."""
import json, sys, os, re, time, fcntl

os.environ["SYNRIX_BACKEND"] = "sqlite"
os.environ["SYNRIX_DATA_DIR"] = os.path.expanduser("~/.synrix/data")

# --- Guard: Lockfile + Cooldown (max 1 Instanz, min 3s Pause) ---
LOCK_PATH = os.path.expanduser("~/.octopoda-track.lock")
COOLDOWN_PATH = os.path.expanduser("~/.octopoda-track.last")
COOLDOWN_SECONDS = 3

# Cooldown: skip if last run was < 3s ago
try:
    if os.path.exists(COOLDOWN_PATH):
        last_run = os.path.getmtime(COOLDOWN_PATH)
        if time.time() - last_run < COOLDOWN_SECONDS:
            sys.exit(0)
except Exception:
    pass

# Lockfile: skip if another instance is already running
lock_fd = None
try:
    lock_fd = open(LOCK_PATH, "w")
    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
except (IOError, OSError):
    sys.exit(0)

# Update cooldown timestamp
try:
    with open(COOLDOWN_PATH, "w") as f:
        f.write(str(time.time()))
except Exception:
    pass

# Parse session_id from stdin
try:
    data = json.load(sys.stdin)
    session_id = data.get("session_id", "unknown")
except:
    data = {}
    session_id = "unknown"

# Try to get a meaningful name from the working directory
cwd = data.get("cwd", os.getcwd())
dir_name = os.path.basename(cwd) if cwd else "unknown"
# Sanitize: only alphanumeric, hyphens, underscores
dir_name = re.sub(r'[^a-zA-Z0-9_-]', '', dir_name)[:20]
agent_id = f"claude-{dir_name}" if dir_name and dir_name != "unknown" else f"claude-{session_id[:8]}"

try:
    from synrix_runtime.core.daemon import RuntimeDaemon
    daemon = RuntimeDaemon.get_instance()
    if not daemon.running:
        daemon.start()

    from synrix_runtime.api.runtime import AgentRuntime
    rt = AgentRuntime(agent_id, agent_type="claude-code")
    rt.remember("session:active", {"session_id": session_id, "status": "running"})

    # Auto-populate useful session data for Memory Explorer
    if cwd:
        rt.remember("session:cwd", {"value": cwd})
    project_name = os.path.basename(cwd) if cwd else "unknown"
    if project_name and project_name != "unknown":
        rt.remember("session:project", {"value": project_name})

    tool_name_for_memory = data.get("tool_name", "")
    if tool_name_for_memory:
        rt.remember("session:last_tool", {"value": tool_name_for_memory, "timestamp": __import__("time").time()})

    # Generate a read metric so read latency shows in dashboard
    try:
        rt.recall("session:active")
    except Exception:
        pass

    # Auto-log every tool call as audit event
    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})
    if tool_name:
        import time as _time
        summary = ""
        if tool_name in ("Edit", "Write"):
            summary = tool_input.get("file_path", "")
        elif tool_name == "Bash":
            cmd = tool_input.get("command", "")
            summary = cmd[:80] if cmd else ""
        elif tool_name == "Read":
            summary = tool_input.get("file_path", "")
        elif tool_name in ("Grep", "Glob"):
            summary = tool_input.get("pattern", "")
        else:
            summary = str(tool_input)[:80] if tool_input else ""

        rt.log_decision(
            f"{tool_name}: {summary}",
            f"Tool {tool_name} aufgerufen",
            {"tool": tool_name, "input_summary": summary}
        )

    # Auto-inject context: query recent memories from SQLite and write to context file
    import sqlite3
    db_path = os.path.expanduser("~/.synrix/data/synrix.db")
    if os.path.exists(db_path):
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        cursor = conn.execute(
            "SELECT DISTINCT name, data FROM nodes "
            "WHERE name LIKE 'agents:%' AND name NOT LIKE '%:session:active' "
            "ORDER BY updated_at DESC LIMIT 10"
        )
        rows = cursor.fetchall()
        conn.close()

        if rows:
            context_lines = ["## Octopoda Context (auto-loaded)", ""]
            for name, data_str in rows:
                # Extract the key part (after agent_id)
                parts = name.split(":", 2)
                key = parts[2] if len(parts) > 2 else name
                # Try to extract the value summary
                try:
                    data_obj = json.loads(data_str)
                    value = data_obj.get("value", {})
                    if isinstance(value, dict):
                        summary = value.get("value", str(value))
                    else:
                        summary = str(value)
                    # Truncate long values
                    if len(str(summary)) > 200:
                        summary = str(summary)[:200] + "..."
                except Exception:
                    summary = data_str[:200] if data_str else ""
                agent_part = parts[1] if len(parts) > 1 else "unknown"
                context_lines.append(f"- [{agent_part}] {key}: {summary}")

            context_path = os.path.expanduser("~/.octopoda-context.md")
            with open(context_path, "w") as f:
                f.write("\n".join(context_lines) + "\n")
except Exception:
    pass
finally:
    # Lock freigeben
    if lock_fd:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            lock_fd.close()
        except Exception:
            pass
