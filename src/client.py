import json
import socket
import struct
import threading
import time
from typing import Tuple, Optional
import tkinter as tk

# --- Protocol constants ---
PROTOCOL_ID = b"MLSP"
VERSION = 1
MSG_INIT = 4
MSG_DATA = 1
HEADER_FMT = "!4sBBIIQHI"
HEADER_SIZE = struct.calcsize(HEADER_FMT)
MSG_ACQUIRE_REQUEST = 2
GRID_SIZE = 5

# --- Globals ---
player_id: str | None = None
ui_dirty = False
root: Optional[tk.Tk] = None
canvas: Optional[tk.Canvas] = None
CELL_SIZE = 65
COLORS = ["lightgray", "lightblue", "lightgreen", "lightcoral", "khaki"]

# --- Networking setup ---
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


# --- Helpers ---
def now_ms() -> int:
    return int(time.time() * 1000)


def parse_header(packet: bytes) -> Tuple[bytes, int, int, int, int, int, int, int]:
    if len(packet) < HEADER_SIZE:
        raise ValueError("packet too small for header")
    return struct.unpack(HEADER_FMT, packet[:HEADER_SIZE])


# --- Sending functions ---
def send_acquire_request(sock: socket.socket, player_id: str, cell: Tuple[int, int]) -> None:
    msg = {
        "type": "ACQUIRE_REQUEST",
        "id": player_id,
        "cell": cell,
        "timestamp": now_ms(),
    }
    sock.sendto(json.dumps(msg).encode("utf-8"), SERVER)
    print(f"ACQUIRE_REQUEST sent for cell {cell}")


# --- Drawing ---
def draw_grid() -> None:
    global canvas
    if canvas is None:
        return
    canvas.delete("all")
    for r in range(GRID_SIZE):
        for c in range(GRID_SIZE):
            cell = grid[(r, c)]
            owner_val = cell.get("owner")
            try:
                idx = int(owner_val) if owner_val is not None else 0
            except (TypeError, ValueError):
                idx = 0
            color = COLORS[idx if 0 <= idx < len(COLORS) else 0]
            x0, y0 = c * CELL_SIZE, r * CELL_SIZE
            x1, y1 = x0 + CELL_SIZE, y0 + CELL_SIZE
            canvas.create_rectangle(x0, y0, x1, y1, fill=color, outline="black")


# --- Receiving thread ---
def recv_loop(sock: socket.socket) -> None:
    global latest_snapshot, grid, player_id, ui_dirty
    while True:
        try:
            packet, addr = sock.recvfrom(4096)
            # detect binary packet by checking 4-byte protocol ID
            if len(packet) >= 4 and packet[:4] == PROTOCOL_ID:
                hdr = parse_header(packet)
                (
                    protocol_id,
                    ver,
                    msg_type,
                    snapshot_id,
                    seq_num,
                    ts,
                    plen,
                    crc,
                ) = hdr
                payload = packet[HEADER_SIZE:HEADER_SIZE + plen]
                data = json.loads(payload.decode("utf-8"))
            else:
                data = json.loads(packet.decode("utf-8"))

            msg_type = data.get("type")

            if msg_type == "ASSIGN_ID":
                player_id = data["id"]
                print(f"You are Player {player_id}")
                continue

            elif msg_type == "SNAPSHOT":
                sid = data.get("snapshot_id", 0)
                if sid <= latest_snapshot:
                    continue
                latest_snapshot = sid
                new_grid = {}
                for key, val in data.get("grid", {}).items():
                    try:
                        r, c = map(int, key.split(","))
                        new_grid[(r, c)] = val
                    except Exception:
                        continue
                grid.update(new_grid)
                ui_dirty = True
                if root is not None:
                    root.after(0, draw_grid)
                claimed = sum(1 for c in grid.values() if c["state"] == "ACQUIRED")
                print(f"[SNAPSHOT] id={sid} | claimed={claimed}/{len(grid)}")

            elif msg_type == "GAME_OVER":
                print(f"[GAME_OVER] Winner: {data.get('winner')} | Scoreboard: {data.get('scoreboard')}")

        except Exception:
            continue


# --- Main and GUI ---
def main() -> None:
    global player_id, ui_dirty, root, canvas
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", 0))
    player_id = None

    # Start receiver thread before INIT
    threading.Thread(target=recv_loop, args=(sock,), daemon=True).start()
    sock.sendto(json.dumps({"type": "INIT"}).encode("utf-8"), SERVER)

    root = tk.Tk()
    root.title("Grid Clash")
    canvas = tk.Canvas(root, width=GRID_SIZE * CELL_SIZE, height=GRID_SIZE * CELL_SIZE)
    canvas.pack()

    def click_handler(event):
        global player_id
        r, c = event.y // CELL_SIZE, event.x // CELL_SIZE
        if player_id is None:
            print("ID not yet assigned by server.")
            return
        send_acquire_request(sock, player_id, (r, c))

    canvas.bind("<Button-1>", click_handler)

    draw_grid()

    def refresh_title():
        r = root
        if r is not None:
            if player_id is not None:
                r.title(f"Grid Clash — Player {player_id}")
            r.after(200, refresh_title)

    refresh_title()

    def periodic_refresh():
        global ui_dirty
        if ui_dirty:
            draw_grid()
            ui_dirty = False
        if root:
            root.after(50, periodic_refresh)

    periodic_refresh()

    try:
        root.mainloop()
    finally:
        sock.close()


if __name__ == "__main__":
    main()
