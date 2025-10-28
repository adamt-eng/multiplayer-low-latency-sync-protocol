import json
import socket
import struct
import threading
import os
import time
from typing import Tuple

PROTOCOL_ID = b"MLSP"
VERSION = 1
MSG_INIT = 4
MSG_DATA = 1
HEADER_FMT = "!4sBBIIQHI"
HEADER_SIZE = struct.calcsize(HEADER_FMT)


def get_local_ipv4() -> str:
    """Return the local IPv4 address used for outbound connections.

    This opens a temporary UDP socket to a public IP (no packets are sent)
    to let the OS choose the appropriate outbound interface, then reads
    the socket's own address.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    # connect to a public IP; no traffic is sent for UDP connect
    sock.connect(("8.8.8.8", 80))
    ip = sock.getsockname()[0]
    sock.close()
    return ip


# Allow environment override for convenience during testing/deployment
env_host = os.environ.get("SERVER_HOST")
SERVER = (env_host if env_host else get_local_ipv4(), 40000)


def now_ms() -> int:
    """Return current time in milliseconds."""
    return int(time.time() * 1000)


def parse_header(packet: bytes) -> Tuple[bytes, int, int, int, int, int, int, int]:
    """Unpack and return the packet header fields.

    Raises ValueError if the packet is too small.
    """
    if len(packet) < HEADER_SIZE:
        raise ValueError("packet too small for header")
    return struct.unpack(HEADER_FMT, packet[:HEADER_SIZE])


def send_init(sock: socket.socket, player_id: str) -> None:
    """Send an INIT JSON message to the server."""
    msg = json.dumps({"type": "INIT", "id": player_id}).encode("utf-8")
    sock.sendto(msg, SERVER)
    print(f"INIT sent to {SERVER} for player {player_id}")


def send_data(sock: socket.socket, player_id: str) -> None:
    """Continuously send simple position updates to the server."""
    pos = {"x": 0.0, "y": 0.0}
    try:
        while True:
            # Update position and send DATA message
            pos["x"] = (pos["x"] + 0.2) % 10
            pos["y"] = (pos["y"] + 0.15) % 10
            msg = json.dumps({"type": "DATA", "id": player_id, "pos": pos}).encode("utf-8")
            try:
                sock.sendto(msg, SERVER)
            except Exception:
                print("Warning: failed to send DATA")
            time.sleep(1)
    except Exception:
        print("send_data thread exiting")

def print_message_format(header_tuple, payload_bytes):
    """Display header and payload fields in human-readable format."""
    (
        protocol_id,
        ver,
        msg_type,
        snapshot_id,
        seq_num,
        ts,
        plen,
        crc,
    ) = header_tuple

    print("\nHeader:")
    print(f'protocol_id="{protocol_id.decode()}"')
    print(f"version={ver}")
    print(f"msg_type={msg_type}")
    print(f"snapshot_id={snapshot_id}")
    print(f"seq_num={seq_num}")
    print(f"timestamp={ts}")
    print(f"payload_len={plen}")
    print(f"checksum=0x{crc:08X}")

    # Decode payload (if JSON)
    try:
        payload_text = json.dumps(json.loads(payload_bytes.decode("utf-8")), indent=2)
        print("\nPayload (JSON for prototype):")
        print(payload_text)
    except Exception:
        print("\nPayload (raw bytes):")
        print(payload_bytes)
    print("-" * 40)


def recv_loop(sock: socket.socket) -> None:
    """Receive packets, parse header and print a brief summary."""
    while True:
        try:
            packet, _ = sock.recvfrom(4096)
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
            try:
                data = json.loads(payload.decode("utf-8"))
            except Exception:
                print("Warning: failed to parse payload JSON")
                continue
            players = list(data.get("state", {}).keys())
            print_message_format(hdr, payload)
        except Exception:
            print("recv_loop encountered an error, continuing")


def main() -> None:
    player_id = input("Enter player id: ").strip()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", 0))
    send_init(sock, player_id)
    t = threading.Thread(target=send_data, args=(sock, player_id), daemon=True)
    t.start()
    try:
        recv_loop(sock)
    except KeyboardInterrupt:
        print("Interrupted, exiting.")
    finally:
        sock.close()


if __name__ == "__main__":
    main()