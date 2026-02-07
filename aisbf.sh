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

# Function to create venv if it doesn't exist
ensure_venv() {
    if [ ! -d "$VENV_DIR" ]; then
        echo "Creating virtual environment at $VENV_DIR"
        python3 -m venv "$VENV_DIR"
        
        # Install requirements if requirements.txt exists
        if [ -f "$SHARE_DIR/requirements.txt" ]; then
            echo "Installing requirements from $SHARE_DIR/requirements.txt"
            "$VENV_DIR/bin/pip" install -r "$SHARE_DIR/requirements.txt"
        fi
        
        # Install aisbf package from system site-packages into venv
        # This allows the venv to find the aisbf module
        echo "Installing aisbf package in venv"
        "$VENV_DIR/bin/pip" install aisbf
    fi
}

# Function to update venv packages silently
update_venv() {
    # Update requirements if requirements.txt exists
    if [ -f "$SHARE_DIR/requirements.txt" ]; then
        "$VENV_DIR/bin/pip" install --upgrade -r "$SHARE_DIR/requirements.txt" -q 2>/dev/null
    fi
    
    # Update aisbf package silently
    "$VENV_DIR/bin/pip" install --upgrade aisbf -q 2>/dev/null
}

# Function to start the server
start_server() {
    # Ensure venv exists
    ensure_venv
    
    # Update venv packages silently
    update_venv
    
    # Activate the virtual environment
    source $VENV_DIR/bin/activate
    
    # Change to share directory where main.py is located
    cd $SHARE_DIR
    
    # Start the proxy server with logging
    # Redirect stderr to suppress BrokenPipeError during shutdown
    uvicorn main:app --host 127.0.0.1 --port 17765 2>&1 | while IFS= read -r line; do
        # Filter out BrokenPipeError logging errors
        if [[ "$line" != *"--- Logging error ---"* ]] && [[ "$line" != *"BrokenPipeError"* ]] && [[ "$line" != *"Call stack:"* ]] && [[ "$line" != *"File "*"/python"* ]] && [[ "$line" != *"Message:"* ]] && [[ "$line" != *"Arguments:"* ]]; then
            echo "$line" | tee -a "$LOG_DIR/aisbf_stdout.log"
        fi
    done
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
    
    # Update venv packages silently
    update_venv
    
    # Start in background with nohup and logging
    # Filter out BrokenPipeError logging errors
    nohup bash -c "source $VENV_DIR/bin/activate && cd $SHARE_DIR && uvicorn main:app --host 127.0.0.1 --port 17765 2>&1 | grep -v '--- Logging error ---' | grep -v 'BrokenPipeError' | grep -v 'Call stack:' | grep -v 'File .*python' | grep -v 'Message:' | grep -v 'Arguments:'" >> "$LOG_DIR/aisbf_stdout.log" 2>&1 &
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

# Main command handling
case "$1" in
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
