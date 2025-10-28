# Move to the directory containing this script
cd "$(dirname "$0")"

echo "Starting MLSP baseline test..."
PORT=40000

# Start server in new terminal
gnome-terminal --title="MLSP SERVER" -- bash -c "python3 server.py; exec bash"

# Wait for server startup
sleep 2

# Launch four clients
gnome-terminal --title="CLIENT 1" -- bash -c "python3 client.py; exec bash"
sleep 1
gnome-terminal --title="CLIENT 2" -- bash -c "python3 client.py; exec bash"
sleep 1
gnome-terminal --title="CLIENT 3" -- bash -c "python3 client.py; exec bash"
sleep 1
gnome-terminal --title="CLIENT 4" -- bash -c "python3 client.py; exec bash"

echo "All clients launched."
echo "Close terminals manually when done."
