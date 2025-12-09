import json
import socket
import threading
import constants
from helpers import get_local_ipv4, now_ms
from packet_helper import build_packet, parse_packet, print_packet
import client_gui

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
CELL_SIZE = constants.CELL_SIZE

player_id = [None] 

Deployment = False
SERVER = None

grid = {(r, c): {"state": "UNCLAIMED", "owner": None}
        for r in range(GRID_SIZE) for c in range(GRID_SIZE)}

latest_snapshot = -1

# Request/Response Functions
def send_init(sock):
    packet = build_packet(MSG_INIT, 0, 0, b"{}")
    print_packet(packet)
    sock.sendto(packet, SERVER)

def send_snapshot_ack(sock, snapshot_id):
    payload = json.dumps({"snapshot_id": snapshot_id}).encode()
    packet = build_packet(MSG_SNAPSHOT_ACK, snapshot_id, 0, payload)
    print_packet(packet)
    sock.sendto(packet, SERVER)

def send_acquire_request(sock, pid, cell):
    payload = json.dumps({"id": pid, "cell": cell, "timestamp": now_ms()}).encode()
    packet = build_packet(MSG_ACQUIRE_REQ, 0, 0, payload)
    print_packet(packet)
    sock.sendto(packet, SERVER)

def apply_delta(delta: dict):
    for key, val in delta.items():
        r, c = map(int, key.split(","))
        grid[(r, c)] = val


# Receiver Thread
def receiver(sock: socket.socket):
    global latest_snapshot, player_id

    while True:
        try:
            packet, _ = sock.recvfrom(4096)
        except:
            continue

        (msg_type, snapshot_id, _, _, data) = parse_packet(packet)

        if data is None:
             continue

        if msg_type == MSG_ASSIGN_ID:
            player_id[0] = data["id"]
            print(f"[ASSIGN_ID] Assigned Player ID: {player_id[0]}")
            client_gui.update_window_title(player_id[0])
            continue

        if msg_type == MSG_SNAPSHOT:
            if snapshot_id <= latest_snapshot: # type: ignore
                continue
            latest_snapshot = snapshot_id

            delta = data.get("grid", {})
            apply_delta(delta)
            client_gui.update_grid()
            send_snapshot_ack(sock, snapshot_id)
            continue

        if msg_type == MSG_GAME_OVER:
            print(f"[GAME_OVER] Winner: {data.get('winner')} | Scoreboard: {data.get('scoreboard')}")
            return



def main():
    global player_id, sock, SERVER

    # UDP Setup
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", 0))

    client_gui.init_gui(grid, sock, player_id, send_acquire_request)
    client_gui.setup_gui()

    # Start receiver thread
    threading.Thread(target=receiver, args=(sock,), daemon=True).start()

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
