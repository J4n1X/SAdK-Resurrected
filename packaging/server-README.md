# Running a server — quick guide

The server for *Die Siedler - Auferstehung der Kulturen*: it lets unmodified copies of
*Die Siedler: Aufbruch der Kulturen* log in, meet in the lobby village and play matches together.

## 1. Requirements

- Python 3.10 or newer.
- A legal copy of the game, for one file: the game's message schema `msgdefs.ini`.

## 2. Add the game's msgdefs.ini

The server reads the game's own message definitions, which are not distributed with it. Copy
`bin\msgdefs.ini` from your game installation to:

```
server/sadk_lobby/data/msgdefs.ini
```

Without it the server refuses to start and tells you where the file belongs.

## 3. Install the dependencies

```bash
cd server
python3 -m venv .venv                 # optional, but keeps things tidy
. .venv/bin/activate                  # Windows: .venv\Scripts\activate
pip install -r requirements.txt       # cryptography, twofish (the game's login crypto)
```

## 4. Tell the server its address

Clients are handed the server's address for their chat, village and match connections, so the server
must know the IP address players reach it at:

```bash
export SADK_ADVERTISE_IP=203.0.113.10     # your public IP (or LAN IP for a LAN-only server)
```

Windows: `set SADK_ADVERTISE_IP=203.0.113.10`. Use an IP address, not a host name.

## 5. Open the ports

Forward these **TCP** ports to the server machine (and allow them in its firewall):

| Port | Role |
|---|---|
| 7070 | lobby: login, characters, game browser, mail, friends |
| 7071 | chat |
| 5477 | lobby village (3D world) |
| 5481 | referee: match start and end |
| 7072 | host bridge: control and data |
| 7073 | host bridge: joiners |

## 6. Start it

```bash
python3 -m sadk_lobby
```

The banner shows the lobby port and the advertised IP. Stop it with Ctrl+C.

To keep it running on Linux, a systemd user service works well, for example
`~/.config/systemd/user/sadk-lobby.service`:

```ini
[Unit]
Description=Die Siedler - Auferstehung der Kulturen server
After=network-online.target

[Service]
WorkingDirectory=/path/to/server
Environment=SADK_ADVERTISE_IP=203.0.113.10
ExecStart=/usr/bin/python3 -u -m sadk_lobby
Restart=always
RestartSec=3

[Install]
WantedBy=default.target
```

Then `systemctl --user enable --now sadk-lobby`, logs with `journalctl --user -u sadk-lobby -f`.

## 7. Players

Each player runs **SAdK-ServerConfig.exe** (in this release), enters the server's address and clicks
**Save**. That points their game at the server and installs the host bridge. A new user name is
registered on its first login with the password used; after that the password must match. In the
game, `!help` in the chat lists the server commands.

**Hosting matches:** the host's game port (TCP 5479 by default) must be reachable from the joiners.
If it isn't, the bridge relays joiners through the server automatically, as long as both players have
the bridge installed (SAdK-ServerConfig does that).

## Files the server writes (next to `sadk_lobby/`)

| File | Content |
|---|---|
| `sadk_players.json` | accounts (passwords are stored hashed), characters and their saves — **back this up** |
| `sadk_mail.json` | in-game mail |
| `tincat_server.log` | the server log |
| `sadk_captures/` | raw per-connection captures for debugging; safe to delete |
| `npc_positions.json` | positions saved with the `!pos` chat command |
