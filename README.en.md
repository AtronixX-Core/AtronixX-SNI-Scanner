<div align="center">

# AtronixX-SNI-Scanner

**Find the best SNI for Reality and XHTTP — per carrier, measured from your own network**

[🇮🇷 فارسی](README.md) · 🇬🇧 English

📢 Channel: [@AtronixX_Core](https://t.me/AtronixX_Core) &nbsp;|&nbsp; 💬 Support: [@AtronixX_Support](https://t.me/AtronixX_Support)

</div>

---

## What does it do?

Every Iranian carrier (Irancell, Hamrah Aval, RighTel, Mokhaberat, Shatel, …) filters differently. A domain that works great on Irancell may be blocked or slow on Hamrah Aval. For **Reality** and **XHTTP** configs, the SNI (camouflage domain) directly affects stability and speed.

AX-Scanner builds a candidate list, tests it **from your real internet connection**, and tells you:

- which SNIs connect at all on **your carrier**;
- which complete a real **Reality (TCP/Vision)** handshake;
- which complete a real **Reality + XHTTP** handshake;
- and among those, which has the lowest latency and best stability.

The output is a ranked table valid for the carrier you tested.

## Why "from your own network" matters

SNI blocking happens inside the carrier's network, on the `ClientHello` packet. If you run the test from a server in Germany, the packets never cross the Iranian carrier, so the result is meaningless. This is plain network physics: a connection always leaves from the machine that executes the code, even if you are logged into it over SSH.

This project's answer: a **Probe Client** runs on your own computer, connects *out* to your server and stays connected (no port forwarding, no manual tunnels), and performs the tests **on that computer**. Test traffic never passes through any tunnel, so the carrier sees exactly what it would see from a real user.

## Architecture

```
   Your computer (Windows/Linux) — on the carrier you want to measure
  ┌───────────────────────────────┐
  │ probe_client.py               │   ① control link (TLS, commands & results only)
  │  • TLS probes to domains      │ ─────────────────────────────┐
  │  • its own private xray-core  │                              ▼
  │  • real IP/ISP detection      │                 ┌──────────────────────────┐
  └──────────────┬────────────────┘                 │ Your server (e.g. DE)    │
                 │ ② test traffic, direct,           │  • Agent + Broker        │
                 │    over the real carrier path     │  • AX-Scanner menu       │
                 ▼                                  │  • temporary Reality srv │
     candidate domains / temp Reality on server ◄───┴──────────────────────────┘
```

- **Agent (server):** spawns a temporary Reality server with the SNI under test, then destroys it.
- **Broker (server):** keeps the Probe Client's persistent connection and tells it which test to run.
- **Probe Client (your computer):** runs the test on your network and returns only the numbers.

## How testing works (two stages)

1. **Stage 1 — fast filter:** for every candidate (up to 400 by default) several TCP+TLS handshakes are made from your network: success rate, TLS version, ALPN, latency. DNS is resolved on your side too, so carrier DNS poisoning shows up as well.
2. **Stage 2 — deep test:** only the top 50 domains (to avoid flagging your server's IP) are tested with the real protocol, **both transports**: `VLESS+Reality (TCP/Vision)` and `VLESS+Reality (XHTTP)`. A private xray-core on your computer connects to the temporary Reality server and pushes a small request through it — a full handshake and real latency.

**XHTTP column:** for the 50 stage-2 domains it is the *real* XHTTP handshake result (✅/❌). For all others it is only an estimate from stage 1, marked with `~` so it is never mistaken for a real test.

**Carrier verification:** before testing, the IP/ISP/ASN of *your computer's* connection is checked. You get a warning if the selected carrier doesn't match the real one (or a VPN is on).

---

## Setup — step by step

### Step 1 — on the server (Ubuntu 24.04)

```bash
git clone https://github.com/AtronixX-Core/AtronixX-SNI-Scanner.git
cd AtronixX-SNI-Scanner
sudo bash install.sh
AX-Scanner
```

In the menu press **1** (set up the Agent). It asks for two ports: the Agent port and the Probe port. If port **443** is free, use it for the Probe — it looks like ordinary HTTPS and is least likely to be interfered with. If `ufw` is active, open the Probe port.

Then press **2**: the ready-to-paste command for your computer is shown, token included.

### Step 2 — on your own computer (the carrier you want to measure)

You only need **Python 3.8+** — no pip, no admin rights. Grab `probe_client.py` from this repo and run it **once** with the values the server displayed.

**Linux:**
```bash
python3 probe_client.py --server SERVER_IP --port 41081 --token TOKEN
```

**Windows (PowerShell):**
```powershell
py probe_client.py --server SERVER_IP --port 41081 --token TOKEN
```

Later runs need no arguments (`python3 probe_client.py` / `py probe_client.py`). Keep the window open; it reconnects by itself if the link drops.

- Start automatically at login (optional): `--autostart on` (`off` to disable)
- **Turn off any VPN / TUN mode (v2rayN, Nekoray, Hiddify, …).** Otherwise you measure the VPN, not the carrier. The client warns you if it sees a VPN adapter.

### Step 3 — run a test

On the server run `AX-Scanner` again (the banner shows the Probe Client status):

- **3** — automatic test (discovers domains itself)
- **4** — manual test (one domain, a list, or a `.txt` file)

Pick the carrier, the connection is verified, the test runs, and the final table appears:

| Column | Meaning |
|---|---|
| Connect | Stage 1: TCP+TLS reachability on your carrier |
| Reality | Real VLESS+Reality (TCP/Vision) handshake |
| XHTTP | Real XHTTP handshake (or `~` estimate) |
| Latency / R-Latency | Stage-1 latency / real-handshake latency |

For another carrier: switch computer (or SIM/modem), start `probe_client.py`, and test again. Results are valid only for that carrier and that server.

---

## Complete removal

**Server** (menu → option 6, or `sudo bash uninstall.sh`): the service, `/opt/ax-scanner` (xray binary, keys, certificate, token, caches), the `AX-Scanner` command and any xray process belonging to this tool are removed, and a verification checklist is printed. Your panel and its xray-core are untouched (completely separate paths and names).

**Your computer:**
```bash
python3 probe_client.py --uninstall      # Windows: py probe_client.py --uninstall
```
Settings, the private xray-core, logs and the autostart entry are removed. Only an xray running from this tool's own folder is stopped — the xray used by v2rayN and friends is never touched. A verification checklist is shown; only the `probe_client.py` file itself remains for you to delete.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| Probe Client can't connect | Open the Probe port on the server firewall (`ufw allow PORT/tcp`) and check the token. If your carrier blocks that port, try 443. |
| "server rejected the token" | Copy the token again from menu option 2. |
| xray-core won't download on your computer | GitHub access is needed. You can place `xray` / `xray.exe` manually at the path the client prints. |
| Detected carrier doesn't match your choice | A VPN is probably on, or you're on another Wi-Fi/carrier. |
| Stage 2 is skipped | No Probe Client is connected. Deep tests are meaningless without one, so they don't run. |

## Honest limitations

- A result is a snapshot. Filtering changes over time; test several times, at different hours.
- An SNI's performance depends on the **(carrier, server IP) pair**, not the carrier alone.
- The ASN list in the project is only a hint; real detection is a live lookup.
- The deep test is deliberately capped at 50 domains to protect your server's IP.

## Project layout

```
ax_scanner.py        main menu (on the server)
probe_client.py      standalone client, on your computer (Windows/Linux)
core/                Agent, Broker, test stages, ranking, terminal UI
install.sh / uninstall.sh
```

Python standard library only — no pip packages.

## License

MIT — made by [@AtronixX_Core](https://t.me/AtronixX_Core) · Support: [@AtronixX_Support](https://t.me/AtronixX_Support)
