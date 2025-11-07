# Multiplayer Low-Latency Sync Protocol (MLSP)

A UDP-based multiplayer synchronization protocol designed for real-time 2D grid interaction and low-latency state sharing.

---

## Overview
**MLSP** implements a lightweight, low-latency synchronization layer between a central server and multiple clients (up to four).  
It supports smooth position and state updates, minimal jitter, and low CPU overhead using event-driven broadcasting and JSON serialization via `orjson`.

Each player sees a shared N×N grid of cells.  
Clicking a cell sends an `ACQUIRE_REQUEST` to the server.  
The server validates ownership, updates the authoritative grid, and broadcasts synchronized `SNAPSHOT` messages to all clients.  
When all cells are acquired, the server declares the winner and halts broadcasting.

---

## Features
- **Transport:** UDP (connectionless, low-latency)
- **Message Types:**  
  - `INIT` / `ASSIGN_ID` — join handshake  
  - `ACQUIRE_REQUEST` — player cell claim  
  - `SNAPSHOT` — state broadcast  
  - `GAME_OVER` — final result
- **Server capacity:** 4 concurrent clients  
- **Update rate:** ~20–50 Hz (configurable)  
- **Serialization:** `orjson` for high-speed JSON  
- **Platform support:** Windows, Linux  

---

## Directory Structure
```

/src
├── client.py     # Client GUI and network logic (Tkinter)
└── server.py     # Authoritative game state and broadcaster

/scripts
├── run_baseline.bat # Windows local baseline test
└── run_baseline.sh  # Linux local baseline test

```

---

## Running Locally

### Windows
Run the baseline batch file from the project root:
```bat
run_local.bat
```

This script:

1. Starts the MLSP server.
2. Launches two clients in new terminal windows.
3. Each client opens a GUI grid for interaction.

### Linux

Make the script executable:

```bash
chmod +x run_local.sh
```

Then run:

```bash
./run_local.sh
```

This script:

1. Launches the server in a new GNOME terminal.
2. Starts two client GUIs.
3. Automatically connects them to `localhost`.

---

## Gameplay

1. Each client automatically receives an assigned player ID (1–4).
2. Players click cells to claim them.
3. The server resolves conflicts (first-come or earliest timestamp).
4. Claimed cells are broadcast to all players via `SNAPSHOT`.
5. When all cells are claimed, the server sends a `GAME_OVER` message announcing the winner.

---

## Notes

* Ensure **Python 3.10+** is installed and available in `PATH`.
* The UDP payload size is capped at 1200 bytes.
* Both server and client scripts are cross-platform (Windows / Linux / WSL2).

---

## Example Output

**Server:**

```
Server ready on UDP ('0.0.0.0', 40000)
[INIT] Assigned ID 1 to ('127.0.0.1', 52010)
[ACQUIRE] 1 claimed cell (0, 0)
[GAME_OVER] Winner: 1
```

**Client:**

```
You are Player 1
ACQUIRE_REQUEST sent for cell (0, 0)
[SNAPSHOT] id=21 | claimed=25/25
[GAME_OVER] Winner: 1 | Scoreboard: {'1': 25}
```

---

## License

Educational use only — part of the **CSE361 Computer Networks Project**.
