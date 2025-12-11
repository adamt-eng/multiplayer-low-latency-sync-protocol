# **Multiplayer Low-Latency Sync Protocol (MLSP)**

UDP-based multiplayer synchronization for real-time grid interaction and state replication.

---

# **1. Overview**

**MLSP** implements a lightweight, low-latency multiplayer synchronization layer between a central authoritative server and multiple clients.
The system was designed for real-time interaction on an N×N grid, supporting up to **four concurrent players**.

Players click cells to acquire them.
The server validates ownership, updates the authoritative state, and broadcasts synchronized **SNAPSHOT** messages to all clients at 20 Hz.

When all cells are acquired, the server sends `GAME_OVER`, including the final scoreboard.

---

# **2. Features**

### **Transport**

* UDP (connectionless, minimal latency)
* Orjson serialization for high-speed JSON encoding

### **Protocol Message Types**

| Type                | Direction        | Purpose                             |
| ------------------- | ---------------- | ----------------------------------- |
| `MSG_INIT`          | Client → Server  | Request to join                     |
| `MSG_ASSIGN_ID`     | Server → Client  | Assign player ID                    |
| `MSG_ASSIGN_ID_ACK` | Client → Server  | Confirm ID received                 |
| `MSG_SNAPSHOT`      | Server → Client  | Delta or full grid update           |
| `MSG_SNAPSHOT_ACK`  | Client → Server  | Confirm snapshot received           |
| `MSG_SNAPSHOT_NACK` | Client → Server  | Request snapshot resend             |
| `MSG_ACQUIRE_REQ`   | Client → Server  | Attempt to claim a cell             |
| `MSG_ACQUIRE_EVENT` | Server → Clients | Reliable broadcast of a claim event |
| `MSG_ACQUIRE_ACK`   | Client → Server  | Confirm acquire event received      |
| `MSG_GAME_OVER`     | Server → Clients | End-of-game summary                 |

### **Server**

* Authoritative grid state
* Applies delta-encoding
* Broadcasts snapshots every 50ms
* Reliable delivery of acquire events
* Detects game completion

### **Client**

* GUI grid (Tkinter)
* Buffered snapshot rendering (60ms delay smoothing)
* Snapshot watchdog for missing updates
* Reliable ACKs for events
* Optional auto-clicker for automated tests

---

# **3. Automated Test Scenarios**

All tests run inside **WSL2 using Linux netem** for accurate network impairment simulation.

---

# **3.1 Setup**

Enter the project:

```bash
cd ~/multiplayer-low-latency-sync-protocol
```

Activate virtual environment:

```bash
source venv/bin/activate
```

Enter scripts folder:

```bash
cd scripts
```

---

# **3.2 Running All Tests**

Run the automated multi-test script:

```bash
./run_all_tests.sh
```

This performs the **five required tests**:

1. Baseline (no impairment)
2. Packet loss 2%
3. Packet loss 5%
4. Delay 100ms
5. Delay 100ms ± 10ms jitter

For each test, the script:

* Applies the correct `tc netem` rule
* Launches **server + 4 clients**
* Runs the test for 20 seconds
* Saves logs into:

```
test_results/<TEST_NAME>/
```

### Example result structure:

```
test_results/
    Loss 2%/
        server_log.csv
        client_log_1.csv
        client_log_2.csv
        client_log_3.csv
        client_log_4.csv
```

---

# **4. Log Contents**

### **Server logs include:**

* CPU load
* Snapshot ID
* Snapshot bandwidth
* Authoritative state JSON

### **Client logs include:**

* Snapshot ID
* Latency
* Jitter
* Sequence numbers
* Perceived state

---

# **5. Gameplay Flow**

1. Client sends `INIT`
2. Server assigns ID
3. Client confirms
4. Server sends full snapshot
5. Client uses delta updates to stay synced
6. Players click cells → server resolves ownership
7. Server reliably broadcasts acquire events
8. When all cells are owned → server sends `GAME_OVER`

---

# **6. System Requirements**

* Python **3.10+**
* Tkinter (**already included** in our environment)
* orjson, psutil (installed in venv)

---

# **10. License**

Educational use — CSE361 Computer Networks Project.
