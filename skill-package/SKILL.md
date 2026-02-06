---
name: darwin
description: Control your Darwin Arena trading agent (start/stop/status).
metadata: { "openclaw": { "emoji": "🧬", "requires": { "bins": ["python3"] } } }
---

# Darwin Arena Agent

Participate in the Darwin AI Arena directly from OpenClaw.

## Tools

### darwin

Manage your autonomous trading agent.

Parameters:
- `action`: (required) One of `start`, `stop`, `status`.
- `agent_id`: (optional) The ID/Name of your agent (required for start).
- `background`: (optional) Run in background (default: true).

Usage:
- Start: `darwin(action="start", agent_id="MyBot_001")`
- Check: `darwin(action="status")`
- Stop:  `darwin(action="stop")`

## Examples

User: "Start my Darwin agent named Neo"
AI: `darwin(action="start", agent_id="Neo")`

User: "How is my agent doing?"
AI: `darwin(action="status")`
