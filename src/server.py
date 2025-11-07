import json
import socket
import struct
import threading
import time
from typing import Dict, Set, Tuple
import orjson

# --- Protocol constants ---
PROTOCOL_ID = b"MLSP"
VERSION = 1
MSG_INIT = 4
MSG_DATA = 1
HEADER_FMT = "!4sBBIIQHI"
HEADER_SIZE = struct.calcsize(HEADER_FMT)
GRID_SIZE = 5

# --- Shared state ---
STATES = {"UNCLAIMED": 0, "ACQUIRED": 1}
grid = {(r, c): {"state": "UNCLAIMED", "owner": None, "timestamp": 0}
        for r in range(GRID_SIZE) for c in range(GRID_SIZE)}

clients: Set[Tuple[str, int]] = set()
state: Dict[str, Dict[str, float]] = {}
seq_num = 0
snapshot_id = 0
next_id = 1
lock = threading.Lock()

last_snapshot: Dict[Tuple[int, int], Dict] = {}
is_game_over = False


# --- Utility ---
def now_ms() -> int:
    return int(time.time() * 1000)


# --- Core handlers ---
def handle_acquire_request(sock: socket.socket, msg: dict, addr: Tuple[str, int]) -> None:
    """Resolve ACQUIRE_REQUEST conflicts and update grid state."""
    global grid, is_game_over

    cell = tuple(msg.get("cell", []))
    pid = msg.get("id")
    ts = msg.get("timestamp", 0)

    if cell not in grid:
        return

    cell_state = grid[cell]

    # Only unclaimed or older timestamp can claim
    if cell_state["state"] == "UNCLAIMED" or ts < cell_state["timestamp"]:
        grid[cell] = {"state": "ACQUIRED", "owner": pid, "timestamp": ts}
        print(f"[ACQUIRE] {pid} claimed cell {cell}")
    else:
        return

    # Check for game over
    if all(c["state"] == "ACQUIRED" for c in grid.values()):
        winner_counts: Dict[str, int] = {}
        for c in grid.values():
            owner = c["owner"]
            winner_counts[owner] = winner_counts.get(owner, 0) + 1

        if winner_counts:
            winner = max(winner_counts, key=lambda k: winner_counts[k])

            # --- Send final snapshot including the last claimed cell ---
            final_snapshot = {
                "type": "SNAPSHOT",
                "snapshot_id": snapshot_id,
                "timestamp": now_ms(),
                "grid": {f"{r},{c}": cell for (r, c), cell in grid.items()},
            }
            final_payload = orjson.dumps(final_snapshot)
            for cli in clients:
                try:
                    sock.sendto(final_payload, cli)
                except Exception:
                    pass

            # --- Send GAME_OVER message ---
            game_over_msg = {
                "type": "GAME_OVER",
                "winner": winner,
                "scoreboard": winner_counts,
            }
            packet = orjson.dumps(game_over_msg)
            for cli in clients:
                try:
                    sock.sendto(packet, cli)
                except Exception:
                    pass

            is_game_over = True
            print(f"[GAME_OVER] Winner: {winner}")


def receiver(sock: socket.socket) -> None:
    """Handle INIT, DATA, and ACQUIRE_REQUEST messages from clients."""
    global next_id, state
    while True:
        try:
            data, addr = sock.recvfrom(2048)
            msg = json.loads(data.decode("utf-8"))
        except Exception:
            continue

        msg_type = msg.get("type")

        if msg_type == "INIT":
            with lock:
                if len(clients) >= 4:
                    reject = orjson.dumps({"type": "ERROR", "reason": "Server full (max 4 players)"})
                    sock.sendto(reject, addr)
                    continue
                pid = str(next_id)
                next_id += 1
                clients.add(addr)
            print(f"[INIT] Assigned ID {pid} to {addr}")
            assign = orjson.dumps({"type": "ASSIGN_ID", "id": pid})
            sock.sendto(assign, addr)

        elif msg_type == "DATA":
            with lock:
                state[msg["id"]] = msg["pos"]

        elif msg_type == "ACQUIRE_REQUEST":
            with lock:
                handle_acquire_request(sock, msg, addr)


def broadcaster(sock: socket.socket):
    global seq_num, snapshot_id, last_snapshot
    period = 0.05  # 50 ms = 20 Hz

    while True:
        if is_game_over:
            print("[BROADCASTER] Game over, stopping snapshots.")
            break
        start = time.time()
        with lock:
            if not clients:
                time.sleep(period)
                continue

            full_snapshot = {f"{r},{c}": cell for (r, c), cell in grid.items()}
            payload = orjson.dumps({
                "type": "SNAPSHOT",
                "snapshot_id": snapshot_id,
                "timestamp": now_ms(),
                "grid": full_snapshot
            })

            for cli in clients:
                try:
                    sock.sendto(payload, cli)
                except Exception:
                    pass

            seq_num += 1
            snapshot_id += 1
            last_snapshot = grid.copy()

        elapsed = time.time() - start
        if elapsed < period:
            time.sleep(period - elapsed)


# --- Main ---
def main() -> None:
    addr: Tuple[str, int] = ("0.0.0.0", 40000)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(addr)
    print(f"Server ready on UDP {addr}")

    threading.Thread(target=receiver, args=(sock,), daemon=True).start()
    threading.Thread(target=broadcaster, args=(sock,), daemon=True).start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Server interrupted, shutting down.")
    finally:
        sock.close()


if __name__ == "__main__":
    main()
