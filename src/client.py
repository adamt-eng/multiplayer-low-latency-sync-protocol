import json
import socket
import threading
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
    BROADCAST_FREQUENCY
)
import csv
import os
from helpers import get_local_ipv4, now_ms
from packet_helper import build_packet, parse_packet, print_packet
import client_gui
from collections import deque
import random
import time

snapshot_buffer = deque()
RENDER_DELAY_MS = 60

player_id = [None] 

game_over = False
SERVER = None

grid = {(r, c): {"state": "UNCLAIMED", "owner": None}
        for r in range(GRID_SIZE) for c in range(GRID_SIZE)}

latest_snapshot = -1
last_snapshot_time = 0

chunked_snapshots = {}

# Logging setup
LOG_FIELDS = ["client_id", "snapshot_id", "seq_num", "server_timestamp_ms", "recv_time_ms", "latency_ms", "jitter_ms", "perceived_state"]
log_lock = threading.Lock()
prev_server_timestamp = None
prev_recv_time = None

def init_client_log():
    """Initialize the client log file with headers."""
    if player_id[0] is None:
        return
        
    test_name = os.environ.get("CURRENT_TEST_NAME", "default_test")

    folder = os.path.join("test_results", test_name)
    os.makedirs(folder, exist_ok=True)

    log_file = os.path.join(folder, f"client_log_{player_id[0]}.csv")
   
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
   # print_packet(packet)
    sock.sendto(packet, SERVER)
    
def send_assign_ack(sock):
    pkt = build_packet(MSG_ASSIGN_ID_ACK, 0, 0, b"{}")
    sock.sendto(pkt, SERVER)
    
def send_snapshot_ack(sock, snapshot_id):
    payload = json.dumps({"snapshot_id": snapshot_id}).encode()
    packet = build_packet(MSG_SNAPSHOT_ACK, snapshot_id, 0, payload)
    sock.sendto(packet, SERVER)

def send_acquire_request(sock, pid, cell):
    payload = json.dumps({"id": pid, "cell": cell, "timestamp": now_ms()}).encode()
    packet = build_packet(MSG_ACQUIRE_REQ, 0, 0, payload)
    #print_packet(packet)
    sock.sendto(packet, SERVER)

def apply_full_snapshot(full_grid: dict):
    """Replace entire grid with full snapshot (for late joiners)."""
    global grid
    
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

def send_snapshot_nack(sock, snapshot_id):
    payload = json.dumps({"last_snapshot": snapshot_id}).encode()
    packet = build_packet(MSG_SNAPSHOT_NACK, snapshot_id, 0, payload)
    print_packet(packet)
    sock.sendto(packet, SERVER)

# Background threads
def snapshot_watchdog(sock):
    global last_snapshot_time, latest_snapshot, game_over

    # Wait until ID assigned
    while player_id[0] is None:
        time.sleep(0.05)

    # Wait for first snapshot
    while latest_snapshot < 0:
        time.sleep(0.05)

    timeout = BROADCAST_FREQUENCY * 1000
    last_nack_time = 0

    while True:
        if game_over:
            return

        now = now_ms()

        if now - last_snapshot_time > timeout and now - last_nack_time > timeout:
            print("[WATCHDOG] Sending NACK for snapshot", latest_snapshot)
            send_snapshot_nack(sock, latest_snapshot)
            last_nack_time = now

        time.sleep(timeout)

def snapshot_applier():
    while True:
        if game_over and not snapshot_buffer:
            return

        if snapshot_buffer:
            _, recv_time, snapshot_data = snapshot_buffer[0]
            if now_ms() - recv_time >= RENDER_DELAY_MS:
                snapshot_buffer.popleft()
                
                is_full = snapshot_data.get("is_full", False)
                grid_data = snapshot_data.get("grid", {})
                
                if is_full:
                    apply_full_snapshot(grid_data)
                else:
                    for key, val in grid_data.items():
                        r, c = map(int, key.split(","))
                        grid[(r, c)] = val
                        
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

        if msg_type == MSG_ASSIGN_ID and player_id[0] is None:
            player_id[0] = data["id"]
            send_assign_ack(sock)
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
            print(f"[CLIENT ({player_id[0]}) - GAME_OVER] Winner: {data.get('winner')} | Scoreboard: {data.get('scoreboard')}")
            game_over = True
            continue
        
        if msg_type == MSG_ACQUIRE_EVENT:
            cell = tuple(data["cell"])
            owner = data["owner"]
            event_id = data["event_id"]

            grid[cell] = {"state": "ACQUIRED", "owner": owner}

            client_gui.update_grid()

            ack_payload = json.dumps({"event_id": event_id}).encode()
            pkt = build_packet(MSG_ACQUIRE_ACK, 0, 0, ack_payload)
            sock.sendto(pkt, SERVER)
            continue

def init_resender(sock):
    while player_id[0] is None:
        send_init(sock)
        time.sleep(0.3)

def random_clicker(sock):
    global player_id, game_over
    if os.environ.get("ENABLE_RANDOM_CLICKS") != "1":
        return

    while player_id[0] is None:
        time.sleep(0.05)

    while not game_over:
        r = random.randint(0, GRID_SIZE - 1)
        c = random.randint(0, GRID_SIZE - 1)
        send_acquire_request(sock, player_id[0], (r, c))
        time.sleep(random.uniform(0.5, 0.8))

def main():
    global player_id, sock, SERVER

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", 0))

    client_gui.init_gui(grid, sock, player_id, send_acquire_request)
    client_gui.setup_gui()

    threading.Thread(target=receiver, args=(sock,), daemon=True).start()
    threading.Thread(target=snapshot_watchdog, args=(sock,), daemon=True).start()
    threading.Thread(target=snapshot_applier, daemon=True).start()

    SERVER = (get_local_ipv4(), 40000)
    
    threading.Thread(target=init_resender, args=(sock,), daemon=True).start()
    threading.Thread(target=random_clicker, args=(sock,), daemon=True).start()
    
    try:
        client_gui.start_gui()
    finally:
        sock.close()

if __name__ == "__main__":
    main()