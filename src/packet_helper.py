import json
import struct
import zlib
from helpers import now_ms
from constants import (
    PROTOCOL_ID,
    VERSION,
    HEADER_FMT,
    HEADER_SIZE,
    MAX_PACKET_BYTES
    )

def print_packet(packet: bytes) -> None:
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
    print(f"Message Type    : {msg_type}")
    print(f"Snapshot ID     : {snapshot_id}")
    print(f"Sequence Number : {seq}")
    print(f"Server Timestamp: {server_timestamp}")
    print(f"Payload Length  : {payload_len} bytes")
    print(f"Checksum (CRC32): 0x{checksum:08X}")
    print("===================")

    
def build_packet(msg_type: int, snap_id: int, seq: int, payload: bytes) -> bytes:
    if HEADER_SIZE + len(payload) > MAX_PACKET_BYTES:
        raise ValueError(
            f"Total packet size would be too large: header({HEADER_SIZE}) + payload({len(payload)}) > {max_total}"
        )

    ts = now_ms()

    temp_header = struct.pack(
        HEADER_FMT,
        PROTOCOL_ID,
        VERSION,
        msg_type,
        snap_id,
        seq,
        ts,
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
        ts,
        len(payload),
        crc,
    )
    return header + payload


def parse_packet(packet: bytes):
    # Size check
    if len(packet) < HEADER_SIZE:
        return None, None, None, None, None

    # Unpack header
    try:
        (protocol_id, version, msg_type,
         snapshot_id, seq_num, timestamp,
         payload_len, crc) = struct.unpack(HEADER_FMT, packet[:HEADER_SIZE])
    except struct.error:
        return None, None, None, None, None
    
    # Version check
    if version != VERSION:
        return None, None, None, None, None

    # Protocol ID check
    if protocol_id != PROTOCOL_ID:
        return None, None, None, None, None

    # Payload length check
    if len(packet) < HEADER_SIZE + payload_len:
        return None, None, None, None, None

    payload = packet[HEADER_SIZE:HEADER_SIZE + payload_len]

    # Recompute CRC
    temp_header = struct.pack(
        HEADER_FMT,
        protocol_id,
        version,
        msg_type,
        snapshot_id,
        seq_num,
        timestamp,
        payload_len,
        0
    )

    calc_crc = zlib.crc32(temp_header + payload) & 0xFFFFFFFF
    if calc_crc != crc:
        return None, None, None, None, None

    # Decode JSON payload
    try:
        payload_json = json.loads(payload.decode("utf-8"))
    except Exception:
        return None, None, None, None, None

    return msg_type, snapshot_id, seq_num, timestamp, payload_json