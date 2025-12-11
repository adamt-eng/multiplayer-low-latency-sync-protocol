IF=lo

# Commands to start server/clients
START_SERVER="python3 ../src/server.py"
START_CLIENT1="python3 ../src/client.py --id 1"
START_CLIENT2="python3 ../src/client.py --id 2"
START_CLIENT3="python3 ../src/client.py --id 3"
START_CLIENT4="python3 ../src/client.py --id 4"

# Duration per test
DURATION=30

run_test() {
    NAME=$1
    NETEM_CMD=$2

    echo "======================================="
    echo "Running Test: $NAME"
    echo "======================================="

    # Clear previous netem rules
    sudo tc qdisc del dev $IF root 2>/dev/null

    # Apply new rule
    if [ ! -z "$NETEM_CMD" ]; then
        sudo tc qdisc add dev $IF root netem $NETEM_CMD
    fi

    # Start server
    bash -c "$START_SERVER" &
    SERVER_PID=$!

    # Start clients
    bash -c "$START_CLIENT1" &
    C1=$!
    bash -c "$START_CLIENT2" &
    C2=$!
    bash -c "$START_CLIENT3" &
    C3=$!
    bash -c "$START_CLIENT4" &
    C4=$!

    sleep $DURATION

    pkill -f python

    sudo tc qdisc del dev $IF root 2>/dev/null

    echo "Test completed: $NAME"
    echo
}

# ----------------------
# RUN ALL TESTS
# ----------------------

run_test "Baseline (No impairment)" ""

run_test "Loss 2%" "loss 2%"

run_test "Loss 5%" "loss 5%"

run_test "Delay 100ms" "delay 100ms"

run_test "Delay 100ms ± 10ms Jitter" "delay 1000ms 10ms"

echo "ALL TESTS COMPLETE."
