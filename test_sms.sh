#!/bin/sh
# ─────────────────────────────────────────────────────────────
#  smtp2sms test  –  send a test SMS or Email via the local proxy
#
#  Usage:  sh test_sms.sh
#
#  Presents a menu to send a test SMS (via modem) or a test
#  email (via relay). Both go through the smtp2sms service
#  on localhost:2525.
#  Requires: python3 (already installed for smtp2sms).
# ─────────────────────────────────────────────────────────────

PORT=2525
HOST="127.0.0.1"
SMS_DOMAIN="sms.local"
FROM="test@smtp2sms.local"

# ── menu ─────────────────────────────────────────────────────
echo ""
echo "  smtp2sms – Test Utility"
echo "  ─────────────────────────"
echo "  1) Send test SMS  (routes via modem)"
echo "  2) Send test Email (routes via relay)"
echo ""
printf "  Choose [1/2]: "
read CHOICE

case "$CHOICE" in
    1) MODE="sms" ;;
    2) MODE="email" ;;
    *)
        echo "Invalid choice."
        exit 1
        ;;
esac

# ── collect destination ──────────────────────────────────────
if [ "$MODE" = "sms" ]; then
    printf "Enter phone number (e.g. +15551234567): "
    read DEST

    if [ -z "$DEST" ]; then
        echo "ERROR: No phone number entered."
        exit 1
    fi

    CLEAN="$(echo "$DEST" | tr -d ' -')"
    case "$CLEAN" in
        +[0-9]*|[0-9]*) ;;
        *)
            echo "ERROR: '$DEST' does not look like a valid phone number."
            exit 1
            ;;
    esac

    RCPT="${DEST}@${SMS_DOMAIN}"
    SUBJECT="smtp2sms test"
    BODY="This is a test SMS from smtp2sms."
    LABEL="SMS to ${DEST}"
else
    printf "Enter FROM address (your real email, e.g. you@yourdomain.com): "
    read SEND_FROM

    if [ -z "$SEND_FROM" ]; then
        echo "ERROR: No FROM address entered."
        exit 1
    fi

    case "$SEND_FROM" in
        *@*.*)  ;;
        *)
            echo "ERROR: '$SEND_FROM' does not look like a valid email address."
            exit 1
            ;;
    esac

    printf "Enter TO address: "
    read DEST

    if [ -z "$DEST" ]; then
        echo "ERROR: No TO address entered."
        exit 1
    fi

    case "$DEST" in
        *@*.*)  ;;
        *)
            echo "ERROR: '$DEST' does not look like a valid email address."
            exit 1
            ;;
    esac

    FROM="$SEND_FROM"
    RCPT="$DEST"
    SUBJECT="smtp2sms relay test"
    BODY="This is a test email sent through the smtp2sms relay."
    LABEL="Email from ${FROM} to ${DEST}"
fi

# ── send via Python smtplib ──────────────────────────────────
echo ""
echo "Sending ${LABEL}..."
echo "  To:      ${RCPT}"
echo "  Subject: ${SUBJECT}"
echo "  Body:    ${BODY}"
echo "  Via:     ${HOST}:${PORT}"
echo ""

RESPONSE=$(python3 -c "
import smtplib, sys
try:
    s = smtplib.SMTP('${HOST}', ${PORT}, timeout=10)
    s.ehlo('test')
    msg = (
        'From: ${FROM}\r\n'
        'To: ${RCPT}\r\n'
        'Subject: ${SUBJECT}\r\n'
        '\r\n'
        '${BODY}\r\n'
    )
    s.sendmail('${FROM}', ['${RCPT}'], msg)
    s.quit()
    print('OK')
except Exception as e:
    print('FAIL: ' + str(e))
    sys.exit(1)
" 2>&1)

# ── check result ─────────────────────────────────────────────
echo "── Result ──"
echo "$RESPONSE"
echo "────────────"

if echo "$RESPONSE" | grep -q "^OK"; then
    echo ""
    echo "SUCCESS: ${LABEL}"
else
    echo ""
    echo "FAILED: ${RESPONSE}"
    echo "Check logs: WebUI -> System -> Maintenance -> Troubleshoot -> System Log"
    exit 1
fi
