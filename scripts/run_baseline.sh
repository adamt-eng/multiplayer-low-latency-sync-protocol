set -e

# ============================================
# Baseline Local Test - MLSP
# ============================================

echo "Starting MLSP baseline test..."

# Check for Python
if ! command -v python3 &> /dev/null; then
    echo "Python not found in PATH."
    exit 1
fi

PYTHON_EXE="python3"

# Get script directory
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

# Start server
echo "Starting server..."
gnome-terminal -- bash -c "$PYTHON_EXE ../src/server.py; exec bash" &
sleep 2

# Start two clients
for i in 1 2; do
    echo "Starting client $i..."
    gnome-terminal -- bash -c "$PYTHON_EXE ../src/client.py; exec bash" &
    sleep 1
done

exit 0