#!/bin/bash 
########################################################
# Copyright (C) 2026 Stefy Lanza <stefy@nexlab.net>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
#
# Why did the programmer quit his job? Because he didn't get arrays!
########################################################

# AISBF - AI Service Broker Framework || AI Should Be Free
# This script manages the AISBF server using the installed virtual environment

PIDFILE="/tmp/aisbf.pid"

# Determine the correct share directory at runtime
# Check for system installation first (/usr/share/aisbf)
if [ -d "/usr/share/aisbf" ]; then
    SHARE_DIR="/usr/share/aisbf"
    VENV_DIR="/usr/share/aisbf/venv"
    # Running as root - use /var/log/aisbf
    LOG_DIR="/var/log/aisbf"
else
    # Fall back to user installation (~/.local/share/aisbf)
    SHARE_DIR="$HOME/.local/share/aisbf"
    VENV_DIR="$HOME/.local/share/aisbf/venv"
    # Running as user - use ~/.local/var/log/aisbf
    LOG_DIR="$HOME/.local/var/log/aisbf"
fi

# Create log directory if it doesn't exist
mkdir -p "$LOG_DIR"

# Function to find the aisbf.json config file
# Checks user config first, then installed locations, then source tree
find_config_file() {
    # Check user config first (~/.aisbf/aisbf.json)
    if [ -f "$HOME/.aisbf/aisbf.json" ]; then
        echo "$HOME/.aisbf/aisbf.json"
        return
    fi
    
    # Check installed locations
    if [ -f "/usr/share/aisbf/aisbf.json" ]; then
        echo "/usr/share/aisbf/aisbf.json"
        return
    fi
    
    if [ -f "$HOME/.local/share/aisbf/aisbf.json" ]; then
        echo "$HOME/.local/share/aisbf/aisbf.json"
        return
    fi
    
    # Check source tree config
    if [ -f "$SHARE_DIR/config/aisbf.json" ]; then
        echo "$SHARE_DIR/config/aisbf.json"
        return
    fi
    
    # Not found
    echo ""
}

# Function to get host from config file
get_host() {
    local DEFAULT_HOST="127.0.0.1"
    local CONFIG_FILE=$(find_config_file)
    
    # Check if config file was found
    if [ -z "$CONFIG_FILE" ]; then
        echo "$DEFAULT_HOST"
        return
    fi
    
    # Try to read host from config using Python
    local HOST=$(python3 -c "
import json
import sys
try:
    with open('$CONFIG_FILE', 'r') as f:
        config = json.load(f)
        server = config.get('server', {})
        print(server.get('host', '$DEFAULT_HOST'))
except:
    print('$DEFAULT_HOST')
" 2>/dev/null)
    
    # Validate host is not empty
    if [ -n "$HOST" ]; then
        echo "$HOST"
    else
        echo "$DEFAULT_HOST"
    fi
}

# Function to get port from config file
get_port() {
    local DEFAULT_PORT=17765
    local CONFIG_FILE=$(find_config_file)
    
    # Check if config file was found
    if [ -z "$CONFIG_FILE" ]; then
        echo "$DEFAULT_PORT"
        return
    fi
    
    # Try to read port from config using Python
    local PORT=$(python3 -c "
import json
import sys
try:
    with open('$CONFIG_FILE', 'r') as f:
        config = json.load(f)
        server = config.get('server', {})
        print(server.get('port', $DEFAULT_PORT))
except:
    print($DEFAULT_PORT)
" 2>/dev/null)
    
    # Validate port is a number
    if [[ "$PORT" =~ ^[0-9]+$ ]]; then
        echo "$PORT"
    else
        echo "$DEFAULT_PORT"
    fi
}

# Function to check if package was upgraded
check_package_upgrade() {
    local INSTALLED_VERSION_FILE="$VENV_DIR/.aisbf_version"
    local CURRENT_VERSION=$(python3 -c "import aisbf; print(aisbf.__version__)" 2>/dev/null || echo "unknown")
    local SAVED_VERSION=""
    
    if [ -f "$INSTALLED_VERSION_FILE" ]; then
        SAVED_VERSION=$(cat "$INSTALLED_VERSION_FILE")
    fi
    
    if [ "$SAVED_VERSION" != "$CURRENT_VERSION" ]; then
        return 0  # Needs update
    fi
    return 1  # No update needed
}

# Function to create venv if it doesn't exist
ensure_venv() {
    if [ "$DEBUG" = "true" ]; then
        echo "=== DEBUG: ensure_venv called ==="
        echo "VENV_DIR: $VENV_DIR"
        echo "SHARE_DIR: $SHARE_DIR"
    fi

    if [ ! -d "$VENV_DIR" ]; then
        echo "Creating virtual environment at $VENV_DIR"
        # Create venv with --system-site-packages to access system-installed aisbf
        [ "$DEBUG" = "true" ] && echo "=== DEBUG: Creating venv ==="
        python3 -m venv --system-site-packages "$VENV_DIR"

        # Install requirements if requirements.txt exists
        if [ -f "$SHARE_DIR/requirements.txt" ]; then
            echo "Installing requirements from $SHARE_DIR/requirements.txt"
            [ "$DEBUG" = "true" ] && echo "=== DEBUG: Installing requirements ==="
            if ! "$VENV_DIR/bin/pip" install -r "$SHARE_DIR/requirements.txt"; then
                echo ""
                echo "=========================================="
                echo "ERROR: Failed to install Python dependencies"
                echo "=========================================="
                echo ""
                echo "Some packages require system libraries to build."
                echo "If you see errors about 'coincurve', 'bip32', or 'secp256k1', install:"
                echo ""
                echo "  Ubuntu/Debian:"
                echo "    sudo apt-get update"
                echo "    sudo apt-get install pkg-config libsecp256k1-dev build-essential"
                echo ""
                echo "  RHEL/CentOS/Fedora:"
                echo "    sudo yum install pkgconfig libsecp256k1-devel gcc"
                echo ""
                echo "  Alpine Linux:"
                echo "    sudo apk add pkgconfig libsecp256k1-dev gcc musl-dev"
                echo ""
                echo "After installing system dependencies, run this script again."
                echo ""
                exit 1
            fi
            [ "$DEBUG" = "true" ] && echo "=== DEBUG: Force reinstalling uvicorn ==="
            # Force reinstall uvicorn in venv to ensure it's available inside the virtual environment
            "$VENV_DIR/bin/pip" install --force-reinstall uvicorn
        fi

        # Save version for future upgrade detection
        [ "$DEBUG" = "true" ] && echo "=== DEBUG: Saving version info ==="
        python3 -c "import aisbf; print(aisbf.__version__)" > "$VENV_DIR/.aisbf_version" 2>/dev/null || echo "unknown" > "$VENV_DIR/.aisbf_version"
    else
        [ "$DEBUG" = "true" ] && echo "=== DEBUG: Venv already exists, checking for upgrades ==="
        # Check if package was upgraded via pip
        if check_package_upgrade; then
            echo "Package upgrade detected, updating venv dependencies..."
            # Only update requirements, aisbf is accessed from system site-packages
            if [ -f "$SHARE_DIR/requirements.txt" ]; then
                [ "$DEBUG" = "true" ] && echo "=== DEBUG: Updating requirements ==="
                if ! "$VENV_DIR/bin/pip" install -r "$SHARE_DIR/requirements.txt"; then
                    echo ""
                    echo "=========================================="
                    echo "ERROR: Failed to update Python dependencies"
                    echo "=========================================="
                    echo ""
                    echo "Some packages require system libraries. See error messages above."
                    echo "You may need to install system dependencies (pkg-config, libsecp256k1-dev, build-essential)"
                    echo ""
                    exit 1
                fi
                [ "$DEBUG" = "true" ] && echo "=== DEBUG: Force reinstalling uvicorn ==="
                # Force reinstall uvicorn in venv to ensure it's available inside the virtual environment
                "$VENV_DIR/bin/pip" install --force-reinstall uvicorn
            fi
            python3 -c "import aisbf; print(aisbf.__version__)" > "$VENV_DIR/.aisbf_version" 2>/dev/null || echo "unknown" > "$VENV_DIR/.aisbf_version"
            echo "Virtual environment updated successfully"
        else
            [ "$DEBUG" = "true" ] && echo "=== DEBUG: No package upgrade detected ==="
        fi
    fi
    [ "$DEBUG" = "true" ] && echo "=== DEBUG: ensure_venv completed ==="
}

# Function to update venv packages (only install missing ones, no forced upgrades)
update_venv() {
    # Only update if requirements file exists
    if [ -f "$SHARE_DIR/requirements.txt" ]; then
        # Check if there are any new packages to install (not already satisfied)
        "$VENV_DIR/bin/pip" install -r "$SHARE_DIR/requirements.txt" 2>&1 | grep -q "Requirement already satisfied"
        ALREADY_SATISFIED=$?
        
        if [ $ALREADY_SATISFIED -ne 0 ]; then
            echo "Installing new requirements (this will take a while!) ... "
            if ! "$VENV_DIR/bin/pip" install -r "$SHARE_DIR/requirements.txt"; then
                echo ""
                echo "=========================================="
                echo "ERROR: Failed to install Python dependencies"
                echo "=========================================="
                echo ""
                echo "Some packages require system libraries. Install them with:"
                echo ""
                echo "  Ubuntu/Debian:"
                echo "    sudo apt-get install pkg-config libsecp256k1-dev build-essential"
                echo ""
                echo "  RHEL/CentOS:"
                echo "    sudo yum install pkgconfig libsecp256k1-devel gcc"
                echo ""
                exit 1
            fi
            # Force reinstall uvicorn in venv to ensure it's available inside the virtual environment
            "$VENV_DIR/bin/pip" install --force-reinstall uvicorn
            echo "[OK]"
        else
            echo "Virtual env already up to date"
            # Still force reinstall uvicorn to ensure it's in venv
            "$VENV_DIR/bin/pip" install --force-reinstall uvicorn
        fi
    fi
}

# Function to start the server
start_server() {
    echo "=== DEBUG: Starting start_server function ==="
    echo "SHARE_DIR: $SHARE_DIR"
    echo "VENV_DIR: $VENV_DIR"
    echo "LOG_DIR: $LOG_DIR"

    # Ensure venv exists
    echo "=== DEBUG: Ensuring venv exists ==="
    ensure_venv
    echo "=== DEBUG: Venv check complete ==="

    # Get host and port from config
    echo "=== DEBUG: Getting host and port ==="
    HOST=$(get_host)
    PORT=$(get_port)
    echo "=== DEBUG: Host=$HOST, Port=$PORT ==="

    # Activate the virtual environment
    echo "=== DEBUG: Activating virtual environment ==="
    source $VENV_DIR/bin/activate
    echo "=== DEBUG: Virtual environment activated ==="

    # Check Python path and imports
    echo "=== DEBUG: Checking Python environment ==="
    echo "Python executable: $(which python3)"
    python3 -c "import sys; print('Python version:', sys.version); print('Python path:', sys.path[:3])"
    echo "=== DEBUG: Testing basic imports ==="
    python3 -c "import uvicorn; print('uvicorn imported successfully')" 2>&1 || echo "ERROR: Failed to import uvicorn"
    python3 -c "import fastapi; print('fastapi imported successfully')" 2>&1 || echo "ERROR: Failed to import fastapi"

    # Change to share directory where main.py is located
    echo "=== DEBUG: Changing to share directory ==="
    cd $SHARE_DIR
    echo "=== DEBUG: Current directory: $(pwd) ==="
    ls -la main.py 2>/dev/null || echo "WARNING: main.py not found in $SHARE_DIR"

    echo "Starting AISBF on $HOST:$PORT..."

    # Check if debug mode is enabled
    if [ "$DEBUG" = "true" ]; then
        echo "Debug mode enabled - showing all debug messages"
        export AISBF_DEBUG=true
    fi

    # Test importing main module before starting uvicorn
    echo "=== DEBUG: Testing main module import ==="
    python3 -c "
try:
    import main
    print('main module imported successfully')
except Exception as e:
    print(f'ERROR: Failed to import main module: {e}')
    import traceback
    traceback.print_exc()
    exit(1)
" 2>&1

    # Start the proxy server - runs in foreground
    # Use exec to replace the shell process so signals are properly handled
    echo "=== DEBUG: Starting uvicorn ==="
    if [ "$DEBUG" = "true" ]; then
        exec uvicorn main:app --host $HOST --port $PORT --log-level debug 2>&1 | tee -a "$LOG_DIR/aisbf_stdout.log"
    else
        exec uvicorn main:app --host $HOST --port $PORT 2>&1 | grep -v -E "(--- Logging error ---|BrokenPipeError|Call stack:|Message:|Arguments:)" | tee -a "$LOG_DIR/aisbf_stdout.log"
    fi
}

# Function to start as daemon
start_daemon() {
    # Check if already running
    if [ -f "$PIDFILE" ]; then
        PID=$(cat "$PIDFILE")
        if ps -p "$PID" > /dev/null 2>&1; then
            echo "AISBF is already running (PID: $PID)"
            exit 1
        else
            # Stale PID file, remove it
            rm -f "$PIDFILE"
        fi
    fi
    
    # Ensure venv exists
    ensure_venv
    
    # Get host and port from config
    HOST=$(get_host)
    PORT=$(get_port)
    
    echo "Starting AISBF on $HOST:$PORT in background..."
    
    # Check if debug mode is enabled
    if [ "$DEBUG" = "true" ]; then
        echo "Debug mode enabled - showing all debug messages"
        export AISBF_DEBUG=true
    fi
    
    # Start in background with nohup and logging
    # Filter out BrokenPipeError logging errors
    if [ "$DEBUG" = "true" ]; then
        nohup bash -c "source $VENV_DIR/bin/activate && cd $SHARE_DIR && uvicorn main:app --host $HOST --port $PORT --log-level debug 2>&1" >> "$LOG_DIR/aisbf_stdout.log" 2>&1 &
    else
        nohup bash -c "source $VENV_DIR/bin/activate && cd $SHARE_DIR && uvicorn main:app --host $HOST --port $PORT 2>&1 | grep -v '--- Logging error ---' | grep -v 'BrokenPipeError' | grep -v 'Call stack:' | grep -v 'File .*python' | grep -v 'Message:' | grep -v 'Arguments:'" >> "$LOG_DIR/aisbf_stdout.log" 2>&1 &
    fi
    PID=$!
    echo $PID > "$PIDFILE"
    echo "AISBF started in background (PID: $PID)"
    echo "Logs are being written to: $LOG_DIR"
}

# Function to check status
check_status() {
    if [ -f "$PIDFILE" ]; then
        PID=$(cat "$PIDFILE")
        if ps -p "$PID" > /dev/null 2>&1; then
            echo "AISBF is running (PID: $PID)"
            exit 0
        else
            echo "AISBF is not running (stale PID file)"
            rm -f "$PIDFILE"
            exit 1
        fi
    else
        echo "AISBF is not running"
        exit 1
    fi
}

# Function to stop the daemon
stop_daemon() {
    if [ -f "$PIDFILE" ]; then
        PID=$(cat "$PIDFILE")
        if ps -p "$PID" > /dev/null 2>&1; then
            kill "$PID"
            rm -f "$PIDFILE"
            echo "AISBF stopped (PID: $PID)"
        else
            echo "AISBF is not running (stale PID file)"
            rm -f "$PIDFILE"
        fi
    else
        echo "AISBF is not running"
    fi
}

# Function to show help
show_help() {
    echo "AISBF - AI Service Broker Framework"
    echo ""
    echo "Usage: aisbf.sh [OPTIONS] [COMMAND]"
    echo ""
    echo "Options:"
    echo "  --debug     Enable debug mode with verbose logging"
    echo "  -h, --help  Show this help message"
    echo ""
    echo "Commands:"
    echo "  daemon   Start AISBF in background (daemon mode)"
    echo "  status   Check if AISBF is running"
    echo "  stop     Stop the AISBF daemon"
    echo ""
    echo "Examples:"
    echo "  aisbf.sh                  # Start in foreground"
    echo "  aisbf.sh --debug          # Start with debug logging"
    echo "  aisbf.sh daemon           # Start in background"
    echo "  aisbf.sh --debug daemon   # Start in background with debug"
    echo "  aisbf.sh status           # Check status"
    echo "  aisbf.sh stop             # Stop the server"
}

# Parse command line arguments
DEBUG="false"
COMMAND=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --debug|-d)
            DEBUG="true"
            shift
            ;;
        -h|--help)
            show_help
            exit 0
            ;;
        daemon|status|stop)
            COMMAND="$1"
            shift
            ;;
        *)
            echo "Unknown option: $1"
            echo ""
            show_help
            exit 1
            ;;
    esac
done

# Main command handling
case "$COMMAND" in
    daemon)
        start_daemon
        ;;
    status)
        check_status
        ;;
    stop)
        stop_daemon
        ;;
    *)
        # Default: start in foreground
        start_server
        ;;
esac
