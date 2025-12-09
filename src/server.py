import socket
import threading
import time
from typing import Dict, Set, Tuple
import orjson
import constants
from helpers import now_ms
from packet_helper import build_packet, parse_packet, print_packet

# Constants
PROTOCOL_ID = constants.PROTOCOL_ID
VERSION = constants.VERSION

MSG_INIT = constants.MSG_INIT
MSG_ASSIGN_ID = constants.MSG_ASSIGN_ID
MSG_SNAPSHOT = constants.MSG_SNAPSHOT
MSG_ACQUIRE_REQ = constants.MSG_ACQUIRE_REQ
MSG_SNAPSHOT_ACK = constants.MSG_SNAPSHOT_ACK
MSG_GAME_OVER = constants.MSG_GAME_OVER

HEADER_FMT = constants.HEADER_FMT
HEADER_SIZE = constants.HEADER_SIZE
GRID_SIZE = constants.GRID_SIZE

grid = {(r, c): {"state": "UNCLAIMED", "owner": None, "timestamp": 0}
        for r in range(GRID_SIZE) for c in range(GRID_SIZE)}

clients: Set[Tuple[str, int]] = set()
seq_num = 0
snapshot_id = 0
next_id = 1
lock = threading.Lock()
is_game_over = False

last_grid = grid.copy()
client_last_acked: Dict[Tuple[str, int], int] = {}

# Request/Response Functions
def send_packet(sock, cli, msg_type, snap_id, payload):
    global seq_num

    packet = build_packet(msg_type, snap_id, seq_num, payload)
    print_packet(packet)
    seq_num += 1
    sock.sendto(packet, cli)

def send_assign_id(sock: socket.socket, addr: Tuple[str, int], pid: str) -> None:
    payload = orjson.dumps({"id": pid})
    send_packet(sock, addr, MSG_ASSIGN_ID, 0, payload)


def send_delta_snapshot(sock):
    global snapshot_id, last_grid

    delta = compute_delta()
    payload = orjson.dumps({"grid": delta, "timestamp": now_ms()})

    for cli in clients:
        send_packet(sock, cli, MSG_SNAPSHOT, snapshot_id, payload)

    if delta:
        last_grid = grid.copy()

    snapshot_id += 1


def send_game_over(sock: socket.socket, winner: str, scoreboard: Dict[str, int]) -> None:
    global seq_num, snapshot_id
    payload = orjson.dumps({"winner": winner, "scoreboard": scoreboard})

    for cli in clients:
        send_packet(sock, cli, MSG_GAME_OVER, snapshot_id, payload)


def handle_acquire_request(sock: socket.socket, msg: dict, addr: Tuple[str, int]) -> None:
    global grid, is_game_over
    cell = tuple(msg.get("cell", []))
    pid = msg.get("id")
    ts = msg.get("timestamp", 0)

    if cell not in grid:
        return

    # Conflict handling
    old = grid[cell]
    if old["state"] == "UNCLAIMED" or ts < old["timestamp"]:
        grid[cell] = {"state": "ACQUIRED", "owner": pid, "timestamp": ts}
        print(f"[ACQUIRE] {pid} claimed cell {cell}")
    else:
        return

    # Handle game over
    if all(c["state"] == "ACQUIRED" for c in grid.values()):
        counts: Dict[str, int] = {}
        for c in grid.values():
            owner = c["owner"]
            counts[owner] = counts.get(owner, 0) + 1
        winner = max(counts, key=counts.get)  # type: ignore[arg-type]
        is_game_over = True
        send_delta_snapshot(sock)
        send_game_over(sock, winner, counts)
        print(f"[GAME_OVER] Winner: {winner}")


# Reliability enhancement strategy: Delta encoding; only send changed cells since last snapshot

def compute_delta() -> Dict[str, Dict]:
    global last_grid
    changed: Dict[str, Dict] = {}
    for (r, c), cell in grid.items():
        prev = last_grid.get((r, c))
        if prev != cell:
            changed[f"{r},{c}"] = cell
    return changed

# Broadcaster and Receiver Threads
def broadcaster(sock: socket.socket) -> None:
    while True:
        if is_game_over:
            print("[BROADCASTER] Game over, stopping snapshots.")
            break
        start = time.time()
        with lock:
            send_delta_snapshot(sock)
        elapsed = time.time() - start
        if elapsed < constants.BROADCAST_FREQUENCY:
            time.sleep(constants.BROADCAST_FREQUENCY - elapsed)


def receiver(sock: socket.socket) -> None:
    global next_id, client_last_acked

    while True:
        try:
            packet, addr = sock.recvfrom(4096)
        except:
            continue

        (msg_type, snapshot_id, _, _, data) = parse_packet(packet)

        if data is None:
            continue

        if msg_type == MSG_INIT:
            with lock:
                pid = str(next_id)
                next_id += 1
                clients.add(addr)
                client_last_acked.setdefault(addr, -1)
            send_assign_id(sock, addr, pid)

        elif msg_type == MSG_ACQUIRE_REQ:
            with lock:
                handle_acquire_request(sock, data, addr)

        elif msg_type == MSG_SNAPSHOT_ACK:
            ack = snapshot_id
            with lock:
                if ack > client_last_acked.get(addr, -1): # type: ignore
                    client_last_acked[addr] = ack # type: ignore


def main() -> None:
    addr = ("0.0.0.0", 40000)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(addr)

    print(f"Server ready at UDP {addr}")

    threading.Thread(target=receiver, args=(sock,), daemon=True).start()
    threading.Thread(target=broadcaster, args=(sock,), daemon=True).start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Server interrupted.")
    finally:
        sock.close()


if __name__ == "__main__":
    main()
