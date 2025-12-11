import json
import socket
import threading
import time
import constants
import csv
import os
from helpers import get_local_ipv4, now_ms
from packet_helper import build_packet, parse_packet, print_packet
import client_gui
from collections import deque

snapshot_buffer = deque()
RENDER_DELAY_MS = 60

# Logging setup
LOG_FIELDS = ["client_id", "snapshot_id", "seq_num", "server_timestamp_ms", "recv_time_ms", "latency_ms", "jitter_ms", "perceived_state"]
log_lock = threading.Lock()
prev_server_timestamp = None
prev_recv_time = None

# Constants
PROTOCOL_ID = constants.PROTOCOL_ID
VERSION = constants.VERSION

MSG_INIT = constants.MSG_INIT
MSG_ASSIGN_ID = constants.MSG_ASSIGN_ID
MSG_SNAPSHOT = constants.MSG_SNAPSHOT
MSG_ACQUIRE_REQ = constants.MSG_ACQUIRE_REQ
MSG_SNAPSHOT_ACK = constants.MSG_SNAPSHOT_ACK
MSG_SNAPSHOT_NACK = constants.MSG_SNAPSHOT_NACK
MSG_GAME_OVER = constants.MSG_GAME_OVER

HEADER_FMT = constants.HEADER_FMT
HEADER_SIZE = constants.HEADER_SIZE
GRID_SIZE = constants.GRID_SIZE
CELL_SIZE = constants.CELL_SIZE

player_id = [None] 

game_over = False
Deployment = False
SERVER = None

# This dictionary is shared with client_gui. It must not be re-assigned (e.g. grid = {}).
grid = {(r, c): {"state": "UNCLAIMED", "owner": None}
        for r in range(GRID_SIZE) for c in range(GRID_SIZE)}

latest_snapshot = -1
last_snapshot_time = 0

# For handling chunked snapshots
chunked_snapshots = {}

def init_client_log():
    """Initialize the client log file with headers."""
    if player_id[0] is None:
        return
    
    log_file = f"client_log_{player_id[0]}.csv"
    if not os.path.exists(log_file):
        with open(log_file, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=LOG_FIELDS)
            writer.writeheader()
    return log_file

def log_client_metric(snap_id, seq_num, server_ts, recv_ts, log_file):
    """Log client metrics to CSV (non-blocking)."""
    global prev_server_timestamp, prev_recv_time
    
    latency = recv_ts - server_ts
    
    # Calculate jitter
    jitter = 0
    if prev_server_timestamp is not None and prev_recv_time is not None:
        recv_diff = recv_ts - prev_recv_time
        sent_diff = server_ts - prev_server_timestamp
        jitter = abs(recv_diff - sent_diff)
    
    # Create perceived state JSON
    perceived = {f"{r},{c}": cell["owner"] for (r, c), cell in grid.items()}
    
    prev_server_timestamp = server_ts
    prev_recv_time = recv_ts
    
    log_entry = {
        "client_id": player_id[0],
        "snapshot_id": snap_id,
        "seq_num": seq_num,
        "server_timestamp_ms": server_ts,
        "recv_time_ms": recv_ts,
        "latency_ms": latency,
        "jitter_ms": jitter,
        "perceived_state": json.dumps(perceived)
    }
    
    def write_log():
        with log_lock:
            with open(log_file, 'a', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=LOG_FIELDS)
                writer.writerow(log_entry)
    
    threading.Thread(target=write_log, daemon=True).start()

# Request/Response Functions
def send_init(sock):
    packet = build_packet(MSG_INIT, 0, 0, b"{}")
    print_packet(packet)
    sock.sendto(packet, SERVER)

def send_snapshot_ack(sock, snapshot_id):
    payload = json.dumps({"snapshot_id": snapshot_id}).encode()
    packet = build_packet(MSG_SNAPSHOT_ACK, snapshot_id, 0, payload)
    sock.sendto(packet, SERVER)

def send_acquire_request(sock, pid, cell):
    payload = json.dumps({"id": pid, "cell": cell, "timestamp": now_ms()}).encode()
    packet = build_packet(MSG_ACQUIRE_REQ, 0, 0, payload)
    print_packet(packet)
    sock.sendto(packet, SERVER)

def apply_delta(delta: dict):
    """Apply delta changes to the grid."""
    for key, val in delta.items():
        r, c = map(int, key.split(","))
        grid[(r, c)] = val


def apply_full_snapshot(full_grid: dict):
    """Replace entire grid with full snapshot (for late joiners)."""
    global grid
    
    # --- BUG FIX START ---
    # Do NOT create a new dictionary (grid = {}). The GUI holds a reference to the old one.
    # Instead, modify the existing dictionary in place.
    
    # 1. Reset all cells to default state in the existing dict
    for r in range(GRID_SIZE):
        for c in range(GRID_SIZE):
            grid[(r, c)] = {"state": "UNCLAIMED", "owner": None}
    
    # 2. Update with new data
    for key, val in full_grid.items():
        if isinstance(key, str):
            r, c = map(int, key.split(","))
            grid[(r, c)] = val
        else:
            grid[key] = val
    # --- BUG FIX END ---

def send_snapshot_nack(sock, snapshot_id):
    payload = json.dumps({"last_snapshot": snapshot_id}).encode()
    packet = build_packet(constants.MSG_SNAPSHOT_NACK, snapshot_id, 0, payload)
    print_packet(packet)
    sock.sendto(packet, SERVER)
    
def snapshot_watchdog(sock):
    global last_snapshot_time, latest_snapshot, game_over

    expected = constants.BROADCAST_FREQUENCY * 1000
    timeout = int(expected * 1.2)

    while True:
        if game_over:
            return
        
        now = now_ms()
        if last_snapshot_time != 0 and now - last_snapshot_time > timeout:
            send_snapshot_nack(sock, latest_snapshot)
            last_snapshot_time = now
        time.sleep(constants.BROADCAST_FREQUENCY)


def snapshot_applier():
    while True:
        if game_over and not snapshot_buffer:
            return

        if snapshot_buffer:
            snap_id, recv_time, snapshot_data = snapshot_buffer[0]
            if now_ms() - recv_time >= RENDER_DELAY_MS:
                snapshot_buffer.popleft()
                
                is_full = snapshot_data.get("is_full", False)
                grid_data = snapshot_data.get("grid", {})
                
                if is_full:
                    apply_full_snapshot(grid_data)
                else:
                    apply_delta(grid_data)
                
                client_gui.update_grid()
                continue

        time.sleep(0.01)


def receiver(sock: socket.socket):
    global latest_snapshot, player_id, last_snapshot_time, game_over
    
    log_file = None

    while True:
        try:
            packet, _ = sock.recvfrom(4096)
        except:
            continue

        (msg_type, snapshot_id, seq_num, server_timestamp, data) = parse_packet(packet)

        if data is None:
             continue

        if msg_type == MSG_ASSIGN_ID:
            player_id[0] = data["id"]
            print(f"[ASSIGN_ID] Assigned Player ID: {player_id[0]}")
            client_gui.update_window_title(player_id[0])
            log_file = init_client_log()
            print(f"Client logging to {log_file}")
            continue

        if msg_type == MSG_SNAPSHOT:
            if snapshot_id <= latest_snapshot:
                continue

            total_chunks = data.get("total_chunks", 1)
            chunk_index = data.get("chunk_index", 0)
            
            if total_chunks > 1:
                if snapshot_id not in chunked_snapshots:
                    chunked_snapshots[snapshot_id] = {
                        "chunks": {},
                        "total_chunks": total_chunks,
                        "timestamp": now_ms()
                    }
                
                chunked_snapshots[snapshot_id]["chunks"][chunk_index] = data.get("grid", {})
                send_snapshot_ack(sock, snapshot_id)
                
                if len(chunked_snapshots[snapshot_id]["chunks"]) == total_chunks:
                    full_grid = {}
                    for idx in range(total_chunks):
                        full_grid.update(chunked_snapshots[snapshot_id]["chunks"][idx])
                    
                    reassembled_data = {
                        "grid": full_grid,
                        "timestamp": chunked_snapshots[snapshot_id]["timestamp"],
                        "is_full": data.get("is_full", True)
                    }
                    
                    latest_snapshot = snapshot_id
                    last_snapshot_time = now_ms()
                    snapshot_buffer.append((snapshot_id, now_ms(), reassembled_data))
                    
                    if log_file:
                        log_client_metric(snapshot_id, seq_num, server_timestamp, now_ms(), log_file)
                    
                    del chunked_snapshots[snapshot_id]
                continue
            else:
                latest_snapshot = snapshot_id
                last_snapshot_time = now_ms()
                snapshot_buffer.append((snapshot_id, now_ms(), data))
                send_snapshot_ack(sock, snapshot_id)
                
                if log_file:
                    log_client_metric(snapshot_id, seq_num, server_timestamp, now_ms(), log_file)
                
                continue


        if msg_type == MSG_GAME_OVER:
            print(f"[GAME_OVER] Winner: {data.get('winner')} | Scoreboard: {data.get('scoreboard')}")
            game_over = True
            continue

def main():
    global player_id, sock, SERVER

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", 0))

    # Pass the grid dictionary to the GUI. 
    # Because we fixed apply_full_snapshot to update in-place, the GUI will see the changes.
    client_gui.init_gui(grid, sock, player_id, send_acquire_request)
    client_gui.setup_gui()

    threading.Thread(target=receiver, args=(sock,), daemon=True).start()
    threading.Thread(target=snapshot_watchdog, args=(sock,), daemon=True).start()
    threading.Thread(target=snapshot_applier, daemon=True).start()

    if Deployment:
        SERVER = ("", 40000)
    else:
        SERVER = (get_local_ipv4(), 40000)

    send_init(sock)

    try:
        client_gui.start_gui()
    finally:
        sock.close()

if __name__ == "__main__":
    main()