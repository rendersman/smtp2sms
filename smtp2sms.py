#!/usr/bin/env python3

import asyncio
import re
import signal
import subprocess
import socket
import smtplib
import ssl
import syslog
from email import policy
from email.parser import BytesParser

# ---------------- CONFIG ----------------

LISTEN_HOST = "0.0.0.0"
LISTEN_PORT = 2525

# Open (no source IP restriction). Set to a specific IP if you want to lock it down.
ALLOW_FROM_IP = ""

# Domain routing
SMS_DOMAIN = "sms.local"

# Gmail relay (no auth; assumes your source IP is allowed by Google Workspace SMTP relay)
RELAY_HOST = "smtp-relay.gmail.com"
RELAY_PORT = 587           # 587 = STARTTLS typically; you can use 25 if that's how your relay is configured
RELAY_STARTTLS = False      # True for 587 in most cases
RELAY_TIMEOUT = 30
RELAY_HELO_NAME = None    # None = use device hostname automatically

MAX_SMS_LEN = 160
INCLUDE_SUBJECT = True
DEBUG = False

CLIENT_TIMEOUT = 60        # seconds before dropping an idle client
MAX_DATA_BYTES = 1048576   # 1 MB cap on incoming message data
MAX_CONNECTIONS = 10       # concurrent client limit

# ---------------------------------------

syslog.openlog("smtp2sms", syslog.LOG_PID, syslog.LOG_DAEMON)

def log(msg, level=syslog.LOG_INFO):
    syslog.syslog(level, msg)

_conn_semaphore = None  # initialised in main()

PHONE_RE = re.compile(r"^\+?\d[\d\- ]{6,}$")


def normalize_number(raw: str) -> str:
    n = raw.strip().replace(" ", "").replace("-", "")
    if n.startswith("+"):
        n = "00" + n[1:]
    return n


def build_sms_text(email_bytes: bytes) -> str:
    try:
        msg = BytesParser(policy=policy.default).parsebytes(email_bytes)
        subject = (msg.get("subject") or "").strip()
        body = ""

        if msg.is_multipart():
            for part in msg.walk():
                ctype = (part.get_content_type() or "").lower()
                disp = (part.get_content_disposition() or "").lower()
                if disp == "attachment":
                    continue
                if ctype == "text/plain":
                    body = (part.get_content() or "").strip()
                    break
        else:
            if (msg.get_content_type() or "").lower() == "text/plain":
                body = (msg.get_content() or "").strip()

        parts = []
        if INCLUDE_SUBJECT and subject:
            parts.append(subject)
        if body:
            parts.append(body)

        text = "\n".join(parts).strip()
        text = re.sub(r"\r\n?", "\n", text).strip()
        return text[:MAX_SMS_LEN]
    except Exception as e:
        log(f"[parse] failed to parse email: {e}", syslog.LOG_WARNING)
        return ""


def gsmctl_send_sms(number: str, text: str) -> tuple[bool, str]:
    payload = f"{number} {text}"
    res = subprocess.run(
        ["gsmctl", "-S", "-s", payload],
        capture_output=True,
        text=True,
        timeout=30,
    )
    out = ((res.stdout or "") + (res.stderr or "")).strip()
    upper = out.upper()

    ok = (res.returncode == 0) and (
        ("OK" in upper)
        or ("SMS SENT" in upper)
        or ("SENT: 1" in upper)
        or ("QUEUED" in upper)
    )
    return (ok, out) if out else (ok, f"rc={res.returncode}")


def parse_addr_path(s: str) -> str:
    s = s.strip()
    if s.startswith("<") and s.endswith(">"):
        s = s[1:-1].strip()
    return s


def domain_of(addr: str) -> str:
    if "@" not in addr:
        return ""
    return addr.split("@", 1)[1].strip().lower()


def local_of(addr: str) -> str:
    return addr.split("@", 1)[0].strip()


def pick_number_from_sms_rcpts(rcpt_tos: list[str]) -> str | None:
    """
    Pick the phone number from RCPT TO local-part *only* for recipients at SMS_DOMAIN.
    """
    for r in rcpt_tos:
        if domain_of(r) != SMS_DOMAIN:
            continue
        local = local_of(r)
        if PHONE_RE.match(local):
            return normalize_number(local)
    return None


def is_sms_message(rcpt_tos: list[str]) -> bool:
    """
    Route rule:
      - If ALL recipients are in SMS_DOMAIN -> send to modem (SMS)
      - Else -> relay to Gmail SMTP relay
    """
    if not rcpt_tos:
        return False
    return all(domain_of(r) == SMS_DOMAIN for r in rcpt_tos)


class SMTPv4(smtplib.SMTP):
    def _get_socket(self, host, port, timeout):
        # Resolve IPv4 only (A records)
        infos = socket.getaddrinfo(host, port, family=socket.AF_INET, type=socket.SOCK_STREAM)
        if not infos:
            raise OSError(f"No IPv4 address found for {host}")
        af, socktype, proto, canonname, sa = infos[0]
        sock = socket.socket(af, socktype, proto)
        sock.settimeout(timeout)
        sock.connect(sa)  # sa is (ipv4, port)
        return sock


def relay_via_gmail(mail_from: str, rcpt_tos: list[str], email_bytes: bytes) -> tuple[bool, str]:
    """
    Forward message to smtp-relay.gmail.com with no auth.
    """
    try:
        with SMTPv4(RELAY_HOST, RELAY_PORT, timeout=RELAY_TIMEOUT) as s:
            if RELAY_HELO_NAME:
                s.ehlo(RELAY_HELO_NAME)
            else:
                s.ehlo()

            if RELAY_STARTTLS:
                ctx = ssl.create_default_context()
                s.starttls(context=ctx)
                if RELAY_HELO_NAME:
                    s.ehlo(RELAY_HELO_NAME)
                else:
                    s.ehlo()

            # smtplib accepts bytes for msg; it will handle dot-stuffing, etc.
            s.sendmail(mail_from or "", rcpt_tos, email_bytes)
        return True, "relayed"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    peer = writer.get_extra_info("peername")
    peer_ip = peer[0] if peer else ""

    async with _conn_semaphore:
        try:
            await _handle_client_inner(reader, writer, peer_ip)
        except asyncio.TimeoutError:
            log(f"[timeout] {peer_ip} – closing idle connection", syslog.LOG_WARNING)
        except ConnectionResetError:
            if DEBUG:
                log(f"[reset] {peer_ip}")
        except Exception as e:
            log(f"[error] {peer_ip} – {type(e).__name__}: {e}", syslog.LOG_ERR)
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
            if DEBUG:
                log(f"[disc] {peer_ip}")


async def _handle_client_inner(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, peer_ip: str):
    if DEBUG:
        log(f"[conn] from {peer_ip}")

    if ALLOW_FROM_IP and peer_ip != ALLOW_FROM_IP:
        writer.write(b"550 Not allowed\r\n")
        await writer.drain()
        return

    def reply(line: str):
        writer.write((line + "\r\n").encode("utf-8", errors="replace"))

    reply("220 smtp-proxy ready")
    await writer.drain()

    mail_from: str = ""
    rcpt_tos: list[str] = []
    in_data = False
    data_lines: list[bytes] = []
    data_size = 0

    while True:
        line = await asyncio.wait_for(reader.readline(), timeout=CLIENT_TIMEOUT)
        if not line:
            break

        if in_data:
            if line in (b".\r\n", b".\n"):
                in_data = False
                email_bytes = b"".join(data_lines)
                data_lines = []
                data_size = 0

                route_sms = is_sms_message(rcpt_tos)
                if DEBUG:
                    log(f"[mail] from={mail_from} rcpts={rcpt_tos} route={'sms' if route_sms else 'relay'}")

                if route_sms:
                    number = pick_number_from_sms_rcpts(rcpt_tos)
                    if not number:
                        reply(f"554 No valid phone number in RCPT TO for @{SMS_DOMAIN}")
                        await writer.drain()
                        mail_from = ""
                        rcpt_tos = []
                        continue

                    text = build_sms_text(email_bytes)
                    if not text:
                        reply("554 Empty message")
                        await writer.drain()
                        mail_from = ""
                        rcpt_tos = []
                        continue

                    ok, out = await asyncio.to_thread(gsmctl_send_sms, number, text)

                    if ok:
                        if DEBUG:
                            log(f"[sms] sent to {number}")
                        reply("250 OK")
                    else:
                        log(f"[sms] FAILED to {number}: {out}", syslog.LOG_WARNING)
                        reply(f"451 gsmctl failed: {out}")

                    await writer.drain()
                    mail_from = ""
                    rcpt_tos = []
                    continue

                # Relay everything else
                ok, out = await asyncio.to_thread(relay_via_gmail, mail_from, rcpt_tos, email_bytes)

                if ok:
                    if DEBUG:
                        log(f"[relay] sent from={mail_from} to={rcpt_tos}")
                    reply("250 OK")
                else:
                    log(f"[relay] FAILED from={mail_from} to={rcpt_tos}: {out}", syslog.LOG_WARNING)
                    reply(f"451 relay failed: {out}")

                await writer.drain()
                mail_from = ""
                rcpt_tos = []
                continue

            if line.startswith(b".."):
                line = line[1:]

            data_size += len(line)
            if data_size > MAX_DATA_BYTES:
                reply("552 Message too large")
                await writer.drain()
                in_data = False
                data_lines = []
                data_size = 0
                mail_from = ""
                rcpt_tos = []
                continue

            data_lines.append(line)
            continue

        cmd = line.decode("utf-8", errors="replace").strip()
        u = cmd.upper()
        if DEBUG:
            log(f"[cmd] {cmd}")

        if u.startswith("HELO") or u.startswith("EHLO"):
            reply("250-smtp-proxy")
            reply(f"250 SIZE {MAX_DATA_BYTES}")
        elif u.startswith("MAIL FROM:"):
            mail_from = parse_addr_path(cmd[10:].strip())
            rcpt_tos = []
            reply("250 OK")
        elif u.startswith("RCPT TO:"):
            addr = parse_addr_path(cmd[8:].strip())
            rcpt_tos.append(addr)
            reply("250 OK")
        elif u == "DATA":
            if not rcpt_tos:
                reply("554 No recipients")
            else:
                in_data = True
                data_lines = []
                data_size = 0
                reply("354 End data with <CRLF>.<CRLF>")
        elif u == "RSET":
            mail_from = ""
            rcpt_tos = []
            in_data = False
            data_lines = []
            data_size = 0
            reply("250 OK")
        elif u == "NOOP":
            reply("250 OK")
        elif u == "QUIT":
            reply("221 Bye")
            await writer.drain()
            break
        else:
            # keep permissive, like your original
            reply("250 OK")

        await writer.drain()


async def main():
    global _conn_semaphore
    _conn_semaphore = asyncio.Semaphore(MAX_CONNECTIONS)

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    def request_shutdown():
        if DEBUG:
            log("Shutdown requested...")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, request_shutdown)
        except NotImplementedError:
            pass

    server = await asyncio.start_server(handle_client, LISTEN_HOST, LISTEN_PORT)
    addrs = ", ".join(str(s.getsockname()) for s in (server.sockets or []))
    log(f"Listening on {addrs}")
    log(f"Routing: *@{SMS_DOMAIN} -> modem (gsmctl), everything else -> {RELAY_HOST}:{RELAY_PORT} (no auth)")

    try:
        await stop_event.wait()
    finally:
        server.close()
        await server.wait_closed()
        log("Stopped.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass