import struct

PROTOCOL_ID = b"MLSP"
VERSION = 1

MSG_INIT          = 1   # Client → server (initial handshake)
MSG_ASSIGN_ID     = 2   # Server → client
MSG_SNAPSHOT      = 3   # Server → client
MSG_ACQUIRE_REQ   = 4   # Client → server
MSG_SNAPSHOT_ACK  = 5   # Client → server
MSG_GAME_OVER     = 6   # Server → client
MSG_SNAPSHOT_NACK = 7   # Client → server
MSG_ASSIGN_ID_ACK = 8
MSG_ACQUIRE_EVENT = 9   # Server → client (reliable broadcast of acquisitions)
MSG_ACQUIRE_ACK   = 10  # Client → server (ack for acquire event)

HEADER_FMT = "!4sBBIIQHI"
HEADER_SIZE = struct.calcsize(HEADER_FMT)

GRID_SIZE = 5
CELL_SIZE = 65

BROADCAST_FREQUENCY = 0.05 # 50ms