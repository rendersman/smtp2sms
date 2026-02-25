#!/bin/sh
# ─────────────────────────────────────────────────────────────
#  smtp2sms  –  start script for Teltonika Custom Scripts
#
#  Add this in the router WebUI:
#    Services -> Custom Scripts -> Add Script
#    Type: Startup    Script: /root/smtp2sms/start.sh
# ─────────────────────────────────────────────────────────────

APP_DIR="/root/smtp2sms"
PID_FILE="${APP_DIR}/smtp2sms.pid"
LOG_TAG="smtp2sms"

# find python3
PY="$(command -v python3 2>/dev/null)"
[ -z "$PY" ] && PY="/usr/local/usr/bin/python3"

if [ ! -x "$PY" ]; then
    logger -t "$LOG_TAG" "ERROR: python3 not found"
    exit 1
fi

# stop any existing instance
if [ -f "$PID_FILE" ]; then
    OLD_PID="$(cat "$PID_FILE" 2>/dev/null)"
    if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
        kill "$OLD_PID" 2>/dev/null
        sleep 1
    fi
    rm -f "$PID_FILE"
fi

# start in background
"$PY" -u "${APP_DIR}/smtp2sms.py" &
echo $! > "$PID_FILE"

logger -t "$LOG_TAG" "Started (PID $(cat "$PID_FILE"))"
