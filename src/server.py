import json
import socket
import struct
import threading
import time
from typing import Dict, Set, Tuple
import zlib
import orjson
import constants

PROTOCOL_ID = constants.PROTOCOL_ID
VERSION = constants.VERSION
MSG_INIT = constants.MSG_INIT
MSG_DATA = constants.MSG_DATA
MSG_EVENT = constants.MSG_EVENT
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


def print_header(packet: bytes) -> None:
    if len(packet) < HEADER_SIZE:
        print("Packet too small to contain header.")
        return

    (
        protocol_id,
        version,
        msg_type,
        snapshot_id,
        seq,
        server_timestamp,
        payload_len,
        checksum,
    ) = struct.unpack(HEADER_FMT, packet[:HEADER_SIZE])

    print("=== MLSP Header ===")
    print(f"Protocol ID     : {protocol_id.decode(errors='ignore')}")
    print(f"Version         : {version}")
    print(f"Message Type    : {msg_type} (1=SNAPSHOT,2=EVENT,3=INIT)")
    print(f"Snapshot ID     : {snapshot_id}")
    print(f"Sequence Number : {seq}")
    print(f"Server Timestamp: {server_timestamp} ms")
    print(f"Payload Length  : {payload_len} bytes")
    print(f"Checksum (CRC32): 0x{checksum:08X}")
    print("===================")


def now_ms() -> int:
    return int(time.time() * 1000)


def build_packet(msg_type: int, snap_id: int, seq: int, payload: bytes) -> bytes:
    temp_header = struct.pack(
        HEADER_FMT,
        PROTOCOL_ID,
        VERSION,
        msg_type,
        snap_id,
        seq,
        now_ms(),
        len(payload),
        0,
    )
    crc = zlib.crc32(temp_header + payload) & 0xFFFFFFFF
    header = struct.pack(
        HEADER_FMT,
        PROTOCOL_ID,
        VERSION,
        msg_type,
        snap_id,
        seq,
        now_ms(),
        len(payload),
        crc,
    )
    return header + payload


def send_assign_id(sock: socket.socket, addr: Tuple[str, int], pid: str) -> None:
    payload = orjson.dumps({"type": "ASSIGN_ID", "id": pid})
    packet = build_packet(MSG_EVENT, 0, 0, payload)
    print_header(packet)
    sock.sendto(packet, addr)


def send_game_over(sock: socket.socket, winner: str, scoreboard: Dict[str, int]) -> None:
    global seq_num, snapshot_id
    payload = orjson.dumps(
        {
            "type": "GAME_OVER",
            "winner": winner,
            "scoreboard": scoreboard,
        }
    )
    packet = build_packet(MSG_EVENT, snapshot_id, seq_num, payload)
    print_header(packet)
    for cli in clients:
        sock.sendto(packet, cli)


def handle_acquire_request(sock: socket.socket, msg: dict, addr: Tuple[str, int]) -> None:
    global grid, is_game_over
    cell = tuple(msg.get("cell", []))
    pid = msg.get("id")
    ts = msg.get("timestamp", 0)

    if cell not in grid:
        return

    old = grid[cell]
    if old["state"] == "UNCLAIMED" or ts < old["timestamp"]:
        grid[cell] = {"state": "ACQUIRED", "owner": pid, "timestamp": ts}
        print(f"[ACQUIRE] {pid} claimed cell {cell}")
    else:
        return

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


def receiver(sock: socket.socket) -> None:
    global next_id, client_last_acked
    while True:
        try:
            data, addr = sock.recvfrom(2048)
            msg = json.loads(data.decode("utf-8"))
        except Exception:
            continue

        m = msg.get("type")
        if m == "INIT":
            with lock:
                pid = str(next_id)
                next_id += 1
                clients.add(addr)
                client_last_acked.setdefault(addr, -1)
            print(f"[INIT] Assigned ID {pid} to {addr}")
            send_assign_id(sock, addr, pid)

        elif m == "ACQUIRE_REQUEST":
            with lock:
                handle_acquire_request(sock, msg, addr)

        elif m == "SNAPSHOT_ACK":
            ack_id = int(msg.get("snapshot_id", -1))
            with lock:
                prev = client_last_acked.get(addr, -1)
                if ack_id > prev:
                    client_last_acked[addr] = ack_id
                    # For future: we could trim history based on min(client_last_acked.values())


def compute_delta() -> Dict[str, Dict]:
    global last_grid
    changed: Dict[str, Dict] = {}
    for (r, c), cell in grid.items():
        prev = last_grid.get((r, c))
        if prev != cell:
            changed[f"{r},{c}"] = cell
    return changed


def send_delta_snapshot(sock: socket.socket) -> None:
    global seq_num, snapshot_id, last_grid
    delta = compute_delta()
    payload = orjson.dumps(
        {
            "type": "SNAPSHOT",
            "snapshot_id": snapshot_id,
            "timestamp": now_ms(),
            "grid": delta,
        }
    )
    packet = build_packet(MSG_DATA, snapshot_id, seq_num, payload)
    print_header(packet)
    for cli in clients:
        sock.sendto(packet, cli)
    if delta:
        last_grid = grid.copy()
    snapshot_id += 1
    seq_num += 1


def broadcaster(sock: socket.socket) -> None:
    period = 0.05
    while True:
        if is_game_over:
            print("[BROADCASTER] Game over, stopping snapshots.")
            break
        start = time.time()
        with lock:
            send_delta_snapshot(sock)
        elapsed = time.time() - start
        if elapsed < period:
            time.sleep(period - elapsed)


def main() -> None:
    addr = ("0.0.0.0", 40000)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(addr)
    print(f"Server ready on UDP {addr}")

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
