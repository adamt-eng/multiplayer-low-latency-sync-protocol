import socket
import threading
import time
from typing import Dict, Set, Tuple
import orjson
import csv
import os
import json
import psutil
from constants import (
    MSG_INIT,
    MSG_ASSIGN_ID,
    MSG_SNAPSHOT,
    MSG_ACQUIRE_REQ,
    MSG_SNAPSHOT_ACK,
    MSG_SNAPSHOT_NACK,
    MSG_GAME_OVER,
    MSG_ACQUIRE_EVENT,
    MSG_ASSIGN_ID_ACK,
    MSG_ACQUIRE_ACK,
    GRID_SIZE,
    BROADCAST_FREQUENCY,
    HEADER_SIZE,
    MAX_PACKET_BYTES
)
from helpers import now_ms
from packet_helper import build_packet, parse_packet, print_packet
import os

# Logging setup
test_name = os.environ.get("CURRENT_TEST_NAME", "default_test")
folder = os.path.join("test_results", test_name)
os.makedirs(folder, exist_ok=True)

LOG_FILE = os.path.join(folder, "server_log.csv")

LOG_FIELDS = ["timestamp_ms", "snapshot_id", "cpu_percent", "bytes_sent_instant", "authoritative_state"]
log_lock = threading.Lock()

def init_server_log():
    """Initialize the server log file with headers."""
    # Always overwrite for a new test run to avoid mixing old data
    with open(LOG_FILE, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=LOG_FIELDS)
        writer.writeheader()

def log_server_metric(snap_id, bytes_sent_instant):
    """Log server metrics to CSV (non-blocking)."""
    
    # Create authoritative state JSON
    auth_state = {f"{r},{c}": cell["owner"] for (r, c), cell in grid.items()}
    
    # Get CPU usage
    try:
        cpu_usage = psutil.cpu_percent(interval=None)
    except:
        cpu_usage = 0

    log_entry = {
        "timestamp_ms": now_ms(),
        "snapshot_id": snap_id,
        "cpu_percent": cpu_usage,
        "bytes_sent_instant": bytes_sent_instant,
        "authoritative_state": json.dumps(auth_state)
    }
    
    def write_log():
        with log_lock:
            with open(LOG_FILE, 'a', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=LOG_FIELDS)
                writer.writerow(log_entry)
    
    threading.Thread(target=write_log, daemon=True).start()

# Global server state
pending_assign = {}
pending_acquire_events = {} 

grid = {(r, c): {"state": "UNCLAIMED", "owner": None, "timestamp": 0}
        for r in range(GRID_SIZE) for c in range(GRID_SIZE)}

clients: Set[Tuple[str, int]] = set()
seq_num = 0
snapshot_id = 0
next_id = 1
lock = threading.Lock()
is_game_over = False
last_grid = grid.copy()
client_last_acked = {}

# Sending functions
def send_packet(sock, cli, msg_type, snap_id, payload):
    global seq_num
    packet = build_packet(msg_type, snap_id, seq_num, payload)
    seq_num += 1
    sock.sendto(packet, cli)

    pkt_len = len(packet)
    
    if pkt_len > MAX_PACKET_BYTES:
        print("[WARN] Packet length exceeds limit:", pkt_len)
        print(f"Packet dump for type {msg_type}, snap_id {snap_id}, seq_num {seq_num-1}:, payload={payload}")
    
    log_server_metric(snap_id, pkt_len)
    
    return pkt_len

def send_assign_id(sock: socket.socket, addr: Tuple[str, int], pid: str) -> None:
    payload = orjson.dumps({"id": pid})
    send_packet(sock, addr, MSG_ASSIGN_ID, 0, payload)

def send_chunked_snapshot(sock, cli, snap_id, base_payload):
    pending = [list(base_payload["grid"].items())]
    parts = []

    while pending:
        items = pending.pop()
        if not items:
            continue

        grid_part = {k: v for (k, v) in items}

        # Build a temporary payload for size-testing
        test_payload = {
            "grid": grid_part,
            "timestamp": base_payload["timestamp"],
            "is_full": base_payload["is_full"],
            "total_chunks": 1,
            "chunk_index": 0
        }

        raw = orjson.dumps(test_payload)

        if HEADER_SIZE + len(raw) > MAX_PACKET_BYTES and len(items) > 1:
            mid = len(items) // 2
            pending.append(items[:mid])
            pending.append(items[mid:])
            continue

        parts.append(grid_part)

    total_chunks = len(parts)

    for idx, grid_part in enumerate(parts):
        real_payload = {
            "grid": grid_part,
            "timestamp": base_payload["timestamp"],
            "is_full": base_payload["is_full"],
            "total_chunks": total_chunks,
            "chunk_index": idx
        }

        payload_bytes = orjson.dumps(real_payload)
        send_packet(sock, cli, MSG_SNAPSHOT, snap_id, payload_bytes)

def send_full_snapshot(sock, addr):
    global snapshot_id

    full_dict = {f"{r},{c}": cell for (r, c), cell in grid.items()}

    base_payload = {
        "grid": full_dict,
        "timestamp": now_ms(),
        "is_full": True
    }

    send_chunked_snapshot(sock, addr, snapshot_id, base_payload)

    snapshot_id += 1

def send_delta_snapshot(sock):
    global snapshot_id, last_grid

    delta: Dict[str, Dict] = {}
    for (r, c), cell in grid.items():
        prev = last_grid.get((r, c))
        if prev != cell:
            delta[f"{r},{c}"] = cell

    if not delta:
        snapshot_id += 1
        return

    base_payload = {
        "grid": delta,
        "timestamp": now_ms(),
        "is_full": False
    }

    for cli in list(clients):
        send_chunked_snapshot(sock, cli, snapshot_id, base_payload)

    snapshot_id += 1

def send_game_over(sock: socket.socket, winner: str, scoreboard: Dict[str, int]) -> None:
    global seq_num, snapshot_id
    payload = orjson.dumps({"winner": winner, "scoreboard": scoreboard})
    for cli in clients:
        send_packet(sock, cli, MSG_GAME_OVER, snapshot_id, payload)

# Background threads
def update_last_grid_when_safe():
    global last_grid, client_last_acked
    while True:
        time.sleep(0.01)
        if not clients:
            continue

        min_acked = min(client_last_acked.get(cli, -1) for cli in clients)

        # Advance last_grid only when all have seen up to snapshot_id
        if min_acked >= snapshot_id - 1:
            last_grid = grid.copy()

def broadcaster(sock: socket.socket) -> None:
    while True:
        if is_game_over: break
        start = time.time()
        with lock:
            send_delta_snapshot(sock)
        elapsed = time.time() - start
        if elapsed < BROADCAST_FREQUENCY:
            time.sleep(BROADCAST_FREQUENCY - elapsed)

def handle_acquire_request(sock: socket.socket, msg: dict, addr: Tuple[str, int]) -> None:
    global grid, is_game_over
    cell = tuple(msg.get("cell", []))
    pid = msg.get("id")
    ts = msg.get("timestamp", 0)

    if cell not in grid: return

    old = grid[cell]
    if old["state"] == "UNCLAIMED" or ts < old["timestamp"]:
        grid[cell] = {"state": "ACQUIRED", "owner": pid, "timestamp": ts}
        event_id = now_ms()
        payload = orjson.dumps({
            "cell": cell,
            "owner": pid,
            "event_id": event_id
        })

        pending_acquire_events[event_id] = {
            "acks": {cli: False for cli in clients},
            "payload": payload
        }

        # Broadcast event to all clients
        for cli in clients:
            send_packet(sock, cli, MSG_ACQUIRE_EVENT, snapshot_id, payload)

        print(f"[ACQUIRE] {pid} claimed cell {cell}")
    else:
        return

    if all(c["state"] == "ACQUIRED" for c in grid.values()):
        counts: Dict[str, int] = {}
        for c in grid.values():
            owner = c["owner"]
            counts[owner] = counts.get(owner, 0) + 1
        winner = max(counts, key=counts.get) 
        is_game_over = True
        send_delta_snapshot(sock)
        send_game_over(sock, winner, counts)
        print(f"[SERVER - GAME_OVER] Winner: {winner} | Scoreboard: {counts}")

def receiver(sock: socket.socket) -> None:
    global next_id, client_last_acked, pending_assign
    while True:
        try:
            packet, addr = sock.recvfrom(4096)
        except: continue

        (msg_type, _, _, _, data) = parse_packet(packet)
        
        if data is None: continue

        if msg_type == MSG_INIT:
            with lock:
                if addr in pending_assign:
                    pid = pending_assign[addr][0]
                else:
                    pid = str(next_id)
                    pending_assign[addr] = [pid, 0]
                    next_id += 1

            send_assign_id(sock, addr, pid)
            send_full_snapshot(sock, addr)

        elif msg_type == MSG_ACQUIRE_REQ:
            with lock: handle_acquire_request(sock, data, addr)
            
        elif msg_type == MSG_SNAPSHOT_NACK:
            print(f"[NACK] from {addr}, resending delta snapshot")
            with lock: send_delta_snapshot(sock)
            
        elif msg_type == MSG_ASSIGN_ID_ACK:
            with lock:
                if addr in pending_assign:
                    pid = pending_assign[addr][0]
                    clients.add(addr)
                    client_last_acked[addr] = -1
                    del pending_assign[addr]
                    print(f"[SERVER] Client {addr} activated as ID {pid}")

        elif msg_type == MSG_ACQUIRE_ACK:
            with lock:
                eid = data["event_id"]
                if eid in pending_acquire_events:
                    pending_acquire_events[eid]["acks"][addr] = True
                    if all(pending_acquire_events[eid]["acks"].values()):
                        del pending_acquire_events[eid]
        elif msg_type == MSG_SNAPSHOT_ACK:
            with lock:
               client_last_acked[addr] = data["snapshot_id"]

def resend_acquire_events(sock):
    while True:
        time.sleep(0.1)
        for _, entry in list(pending_acquire_events.items()):
            for cli, acked in entry["acks"].items():
                if not acked:
                    send_packet(sock, cli, MSG_ACQUIRE_EVENT, 0, entry["payload"])

def resend_assign_id(sock):
    while True:
        now = now_ms()
        with lock:
            for addr in list(pending_assign.keys()):
                pid, last_sent = pending_assign[addr]
                if now - last_sent > 300:
                    send_assign_id(sock, addr, pid)
                    pending_assign[addr][1] = now
        time.sleep(0.05)

def main() -> None:
    addr = ("0.0.0.0", 40000)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(addr)
    print(f"Server ready at UDP {addr}")
    init_server_log()
    
    threading.Thread(target=receiver, args=(sock,), daemon=True).start()
    threading.Thread(target=broadcaster, args=(sock,), daemon=True).start()
    threading.Thread(target=resend_acquire_events, args=(sock,), daemon=True).start()
    threading.Thread(target=resend_assign_id, args=(sock,), daemon=True).start()
    threading.Thread(target=update_last_grid_when_safe, daemon=True).start()

    try:
        while True: time.sleep(1)
    except KeyboardInterrupt: pass
    finally: sock.close()

if __name__ == "__main__":
    main()