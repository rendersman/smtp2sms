# smtp2sms — SMTP-to-SMS Proxy for Teltonika RUT956

A Python-based SMTP proxy designed for the Teltonika RUT956. It intercepts SMTP traffic and routes it based on the recipient domain:
- **SMS Routing**: Emails sent to `[PHONE_NUMBER]@sms.local` are sent as SMS messages via the router's internal modem.
- **Email Relay**: All other emails are relayed to `smtp-relay.gmail.com`.

Any device or application capable of sending email via SMTP can use this proxy to send SMS messages through the router's modem or relay emails through Gmail.

## Features
- **Zero Outside Dependencies**: Uses only Python 3 standard library (`asyncio`, `smtplib`).
- **Simple Deployment**: Runs directly from `/root/smtp2sms/` — no init.d scripts or system-wide installation.
- **Custom Scripts Integration**: Uses the Teltonika **Custom Scripts** feature for auto-start on boot.
- **Modem Control**: Uses the Teltonika `gsmctl` utility for reliable SMS delivery.
- **Relay Support**: Supports Gmail SMTP Relay (configured for IP-based authentication).

## Project Files

| File | Purpose |
| :--- | :--- |
| `smtp2sms.py` | The SMTP proxy application (Python 3). |
| `start.sh` | Startup script — launches the proxy in the background. |
| `stop.sh` | Stop script — kills the running proxy. |
| `test_sms.sh` | Test script — sends a test SMS or email via the proxy. |
| `VERSION` | Current version number. |

## Installation

### 1. Prerequisites
- **Teltonika RUT956** with **Python 3** installed (`opkg update && opkg install python3`).
- **Storage Memory Expansion**: Since the internal flash is limited, it is highly recommended to enable **USB Storage Expansion** via the Teltonika WebUI (**Services → Memory Expansion**) to accommodate Python.
- SSH access to the router.
- **Gmail SMTP Relay** configured to allow your router's public IP address.

### 2. Copy the folder to the router
From your development machine:

```bash
scp -r smtp2sms root@192.168.1.1:/root/
```

### 3. Configure
Edit the settings at the top of `smtp2sms.py` before starting (see [Configuration](#configuration) below).

### 4. Set up auto-start via Custom Scripts
In the Teltonika WebUI:

1. Navigate to **Services → Custom Scripts**.
2. Add the following line to the startup script (`/etc/rc.local`):
   ```
   sh /root/smtp2sms/start.sh &
   ```
3. Click **Save & Apply**.

### 5. Start manually (first time)
SSH into the router and run:

```bash
sh /root/smtp2sms/start.sh
```

### Stop / Restart
```bash
sh /root/smtp2sms/stop.sh       # stop
sh /root/smtp2sms/start.sh      # start (also stops any existing instance first)
```

### Test
```bash
sh /root/smtp2sms/test_sms.sh
```

The script will prompt you to choose between a test SMS (via modem) or a test email (via relay).

### Uninstall
1. Remove the `sh /root/smtp2sms/start.sh &` line from `/etc/rc.local` in the WebUI (**Services → Custom Scripts**).
2. Stop the service: `sh /root/smtp2sms/stop.sh`
3. Delete the folder: `rm -rf /root/smtp2sms`

## Configuration

Edit the settings at the top of `/root/smtp2sms/smtp2sms.py`:

| Setting | Default | Description |
| :--- | :--- | :--- |
| `LISTEN_PORT` | `2525` | Port the proxy listens on. |
| `SMS_DOMAIN` | `sms.local` | Domain used to trigger SMS routing. |
| `RELAY_HOST` | `smtp-relay.gmail.com` | Target for non-SMS emails. |
| `RELAY_PORT` | `587` | Port for the relay (usually 587 for STARTTLS). |
| `RELAY_STARTTLS`| `False` | Set to `True` if your relay requires STARTTLS. |
| `MAX_SMS_LEN` | `160` | Maximum SMS character length. |
| `DEBUG` | `False` | Enable verbose logging. |

## SMTP Device Setup

To configure any SMTP-capable device to use this proxy:

1. Set the **SMTP Server** to the router's LAN IP (e.g., `192.168.1.1`).
2. Set the **Port** to `2525`.
3. **Authentication**: None (leave username/password blank).
4. **Encryption**: None (no TLS/SSL required).
5. To send an **SMS**: Set the recipient to `+15551234567@sms.local` (phone number as the local part, `sms.local` as the domain).
6. To send an **Email**: Set the recipient to any standard email address (e.g., `tech@example.com`) — the proxy will relay it through Gmail.

## Troubleshooting

Check if the process is running:
```bash
cat /root/smtp2sms/smtp2sms.pid
ps | grep smtp2sms
```

Logs are available in the WebUI under **System → Maintenance → Troubleshoot → System Log**. Filter for `smtp2sms` to see relevant entries.

### Important Note on Routing
If your router is configured with multiple WAN interfaces (e.g., Mobile and Wired) or a strict VPN, you may need to add a **Static Route** to ensure traffic to `smtp-relay.gmail.com` exits via the correct interface.

**Note:** Google's relay IPs can change. If you must use a static route, it is recommended to route Google's common IP ranges or identify the IP currently resolved by the router:
```bash
nslookup smtp-relay.gmail.com
```
Then add a static route in the Teltonika WebUI (**Network → Routing → Static Routes**) for the returned IP(s).
