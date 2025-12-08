import json
import socket
import struct
import threading
import time
from typing import Tuple, Optional
import tkinter as tk
import constants

PROTOCOL_ID = constants.PROTOCOL_ID
VERSION = constants.VERSION
MSG_INIT = constants.MSG_INIT
MSG_DATA = constants.MSG_DATA
MSG_EVENT = constants.MSG_EVENT
HEADER_FMT = constants.HEADER_FMT
HEADER_SIZE = constants.HEADER_SIZE
GRID_SIZE = constants.GRID_SIZE
CELL_SIZE = constants.CELL_SIZE

player_id: str | None = None
ui_dirty = False
root: Optional[tk.Tk] = None
canvas: Optional[tk.Canvas] = None

COLORS = ["lightgray", "lightblue", "lightgreen", "lightcoral", "khaki"]

def get_local_ipv4() -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.connect(("8.8.8.8", 80))
    ip = sock.getsockname()[0]
    sock.close()
    return ip

SERVER = (get_local_ipv4(), 40000)

grid = {(r, c): {"state": "UNCLAIMED", "owner": None}
        for r in range(GRID_SIZE) for c in range(GRID_SIZE)}

latest_snapshot = -1

def now_ms() -> int:
    return int(time.time() * 1000)

def parse_header(packet: bytes):
    return struct.unpack(HEADER_FMT, packet[:HEADER_SIZE])

def apply_delta(delta: dict):
    for key, val in delta.items():
        r, c = map(int, key.split(","))
        grid[(r, c)] = val

def draw_grid():
    if canvas is None:
        return
    canvas.delete("all")
    for r in range(GRID_SIZE):
        for c in range(GRID_SIZE):
            cell = grid[(r, c)]
            owner = cell.get("owner")
            try:
                idx = int(owner) if owner is not None else 0
            except:
                idx = 0
            if idx >= len(COLORS):
                idx = 0
            color = COLORS[idx]
            x0, y0 = c * CELL_SIZE, r * CELL_SIZE
            x1, y1 = x0 + CELL_SIZE, y0 + CELL_SIZE
            canvas.create_rectangle(x0, y0, x1, y1, fill=color, outline="black")


def send_snapshot_ack(sock: socket.socket, snapshot_id: int):
    ack = json.dumps({
        "type": "SNAPSHOT_ACK",
        "snapshot_id": snapshot_id
    }).encode("utf-8")
    sock.sendto(ack, SERVER)


def handle_binary_packet(packet: bytes):
    global latest_snapshot, ui_dirty, player_id

    if len(packet) < HEADER_SIZE:
        return

    protocol_id, version, msg_type, snapshot_id, seq_num, ts, plen, crc = parse_header(packet)

    if protocol_id != PROTOCOL_ID:
        return

    if len(packet) < HEADER_SIZE + plen:
        return

    payload = packet[HEADER_SIZE:HEADER_SIZE + plen]

    try:
        data = json.loads(payload.decode("utf-8"))
    except:
        return

    t = data.get("type")

    if t == "ASSIGN_ID":
        player_id = data["id"]
        if root:
            root.after(0, lambda: root.title(f"Grid Clash — Player {player_id}"))  # type: ignore
        return

    if t == "SNAPSHOT":
        sid = data.get("snapshot_id", 0)

        # Discard outdated snapshots
        if sid <= latest_snapshot:
            return

        latest_snapshot = sid

        delta = data.get("grid", {})
        apply_delta(delta)
        ui_dirty = True
        if root:
            root.after(0, draw_grid)

        send_snapshot_ack(sock, sid)

        return

    if t == "GAME_OVER":
        print(f"[GAME_OVER] Winner: {data.get('winner')}  Scoreboard: {data.get('scoreboard')}")
        return

def handle_json_packet(data: bytes):
    global player_id
    try:
        msg = json.loads(data.decode("utf-8"))
    except:
        return

    t = msg.get("type")

    if t == "ASSIGN_ID":
        player_id = msg["id"]
        if root:
            root.after(0, lambda: root.title(f"Grid Clash — Player {player_id}"))  # type: ignore

def recv_loop(sock: socket.socket):
    while True:
        try:
            packet, addr = sock.recvfrom(4096)

            if packet.startswith(PROTOCOL_ID) and len(packet) >= HEADER_SIZE:
                handle_binary_packet(packet)
            else:
                handle_json_packet(packet)

        except Exception:
            continue

def send_acquire_request(sock: socket.socket, player_id: str, cell: Tuple[int, int]):
    msg = {
        "type": "ACQUIRE_REQUEST",
        "id": player_id,
        "cell": cell,
        "timestamp": now_ms()
    }
    sock.sendto(json.dumps(msg).encode("utf-8"), SERVER)

def main():
    global root, canvas, player_id, sock

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", 0))

    threading.Thread(target=recv_loop, args=(sock,), daemon=True).start()

    sock.sendto(json.dumps({"type": "INIT"}).encode("utf-8"), SERVER)

    root = tk.Tk()
    root.title("Grid Clash")
    canvas = tk.Canvas(root, width=GRID_SIZE * CELL_SIZE, height=GRID_SIZE * CELL_SIZE)
    canvas.pack()

    def on_click(event):
        global player_id
        r, c = event.y // CELL_SIZE, event.x // CELL_SIZE
        if player_id is not None:
            send_acquire_request(sock, player_id, (r, c))

    canvas.bind("<Button-1>", on_click)

    draw_grid()

    try:
        root.mainloop()
    finally:
        sock.close()

if __name__ == "__main__":
    main()
