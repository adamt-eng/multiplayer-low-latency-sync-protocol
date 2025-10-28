import json
import socket
import struct
import threading
import time
import zlib
from typing import Dict, Tuple, Set

PROTOCOL_ID = b"MLSP"
VERSION = 1
MSG_INIT = 4
MSG_DATA = 1
HEADER_FMT = "!4sBBIIQHI"
HEADER_SIZE = struct.calcsize(HEADER_FMT)

def pack_header(msg_type: int, snapshot_id: int, seq_num: int, timestamp: int, payload: bytes) -> bytes:
    """Build header with CRC32 over header+payload and return full header bytes."""
    payload_len = len(payload)
    temp = struct.pack(HEADER_FMT, PROTOCOL_ID, VERSION, msg_type,
                       snapshot_id, seq_num, timestamp, payload_len, 0)
    crc = zlib.crc32(temp + payload) & 0xFFFFFFFF
    return struct.pack(HEADER_FMT, PROTOCOL_ID, VERSION, msg_type,
                       snapshot_id, seq_num, timestamp, payload_len, crc)

def now_ms() -> int:
    return int(time.time() * 1000)

# Shared state
clients: Set[Tuple[str, int]] = set()
state: Dict[str, Dict[str, float]] = {}
seq_num = 0
snapshot_id = 0
lock = threading.Lock()  # avoid race conditions

def receiver(sock: socket.socket):
    """Receive client INIT or DATA messages and update state."""
    global state
    while True:
        try:
            data, addr = sock.recvfrom(2048)
            msg = json.loads(data.decode("utf-8"))
        except Exception:
            continue

        if msg.get("type") == "INIT":
            with lock:
                clients.add(addr)
            print(f"[INIT] New client {msg.get('id')} from {addr}")

        elif msg.get("type") == "DATA":
            with lock:
                state[msg["id"]] = msg["pos"]

def broadcaster(sock: socket.socket):
    """Send snapshots to all clients every 20 ms."""
    global seq_num, snapshot_id
    period = 0.02  # 20 ms = 50 Hz
    while True:
        start = time.time()
        with lock:
            if not clients:
                time.sleep(period)
                continue
            payload = json.dumps({"state": state}).encode("utf-8")
            hdr = pack_header(MSG_DATA, snapshot_id, seq_num, now_ms(), payload)
            packet = hdr + payload
            bad = []
            for c in clients:
                try:
                    sock.sendto(packet, c)
                except Exception:
                    bad.append(c)
            for c in bad:
                clients.discard(c)
            seq_num += 1
            snapshot_id += 1
        # precise wait
        elapsed = time.time() - start
        if elapsed < period:
            time.sleep(period - elapsed)

def main() -> None:
    ADDR: Tuple[str, int] = ("0.0.0.0", 40000)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(ADDR)
    print(f"Server ready on UDP {ADDR}")

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
