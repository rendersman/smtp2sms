#!/bin/sh
# ─────────────────────────────────────────────────────────────
#  smtp2sms  –  stop script
#
#  Optionally add to Custom Scripts as a Shutdown script, or
#  run manually:  sh /root/smtp2sms/stop.sh
# ─────────────────────────────────────────────────────────────

APP_DIR="/root/smtp2sms"
PID_FILE="${APP_DIR}/smtp2sms.pid"
LOG_TAG="smtp2sms"

if [ -f "$PID_FILE" ]; then
    PID="$(cat "$PID_FILE" 2>/dev/null)"
    if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then
        kill "$PID" 2>/dev/null
        logger -t "$LOG_TAG" "Stopped (PID $PID)"
    else
        logger -t "$LOG_TAG" "PID $PID not running"
    fi
    rm -f "$PID_FILE"
else
    logger -t "$LOG_TAG" "No PID file found"
fi
