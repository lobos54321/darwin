#!/bin/bash
# Launch all 6 OpenClaw agents with auto-restart on crash
cd "$(dirname "$0")"
ACCTS="$(cat accounts.json)"
ARENA="wss://www.darwinx.fun"

launch_agent() {
    local id=$1
    local agent_name="OpenClaw_Agent_00${id}"
    local logfile="/tmp/${agent_name}.log"

    # Restart loop - if agent crashes, wait and restart
    while true; do
        echo "[$(date)] Starting ${agent_name}" >> "$logfile"
        ACCOUNTS_JSON="$ACCTS" LLM_MODEL="gemini-3-pro-high" PYTHONUNBUFFERED=1 \
            python3 -u -m agent_template.agent \
            --id "$agent_name" \
            --arena "$ARENA" \
            >> "$logfile" 2>&1

        echo "[$(date)] ${agent_name} exited (code: $?). Restarting in 10s..." >> "$logfile"
        sleep 10
    done
}

# Kill any existing agents (macOS Python path is case-sensitive)
pkill -f "agent_template" 2>/dev/null || true
pkill -f "launch_agents.sh" 2>/dev/null || true
sleep 2
# Double-check: force kill any remaining
pkill -9 -f "agent_template" 2>/dev/null || true
sleep 1

# Clear logs
for i in 1 2 3 4 5 6; do
    rm -f "/tmp/OpenClaw_Agent_00${i}.log"
done

# Launch all agents as background jobs
for i in 1 2 3 4 5 6; do
    launch_agent $i &
done

echo "All 6 agents launched with auto-restart."
echo "Logs: /tmp/OpenClaw_Agent_00*.log"
echo "Press Ctrl+C to stop all agents."

# Wait for all background jobs
wait
