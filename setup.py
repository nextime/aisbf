"""
Copyleft (C) 2026 Stefy Lanza <stefy@nexlab.net>

AISBF - AI Service Broker Framework || AI Should Be Free

Setup configuration for AISBF.

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.

Why did the programmer quit his job? Because he didn't get arrays!
"""

from setuptools import setup, find_packages, Command
from setuptools.command.install import install as _install
from pathlib import Path
import os
import sys

# Read the contents of README file
this_directory = Path(__file__).parent
long_description = (this_directory / "README.md").read_text() if (this_directory / "README.md").exists() else ""

# Read requirements
requirements = []
if (this_directory / "requirements.txt").exists():
    with open(this_directory / "requirements.txt") as f:
        requirements = [line.strip() for line in f if line.strip() and not line.startswith("#")]

class InstallCommand(_install):
    """Custom install command that also installs the aisbf script and creates venv"""
    
    def initialize_options(self):
        _install.initialize_options(self)
        # Check if running as non-root without --user flag
        if os.geteuid() != 0 and '--user' not in sys.argv:
            print("Installing as non-root user. Adding --user flag for user-local installation.")
            self.user = True
    
    def run(self):
        # Run the standard install (this will install data_files to share directory)
        _install.run(self)
        
        # Install the aisbf script
        self._install_aisbf_script()
    
    def _install_aisbf_script(self):
        """Install the aisbf script that uses the venv"""
        # Determine the installation directory
        if '--user' in sys.argv or os.geteuid() != 0:
            # User installation - use ~/.local/bin
            bin_dir = Path.home() / '.local' / 'bin'
            share_dir = Path.home() / '.local' / 'share' / 'aisbf'
        else:
            # System installation - use /usr/local/bin
            bin_dir = Path('/usr/local/bin')
            share_dir = Path('/usr/local/share/aisbf')
        
        # Create the bin directory if it doesn't exist
        bin_dir.mkdir(parents=True, exist_ok=True)
        
        # Create the aisbf script that uses the venv
        script_content = f"""#!/bin/bash
# AISBF - AI Service Broker Framework || AI Should Be Free
# This script manages the AISBF server using the installed virtual environment

PIDFILE="/tmp/aisbf.pid"
SHARE_DIR="{share_dir}"
VENV_DIR="$SHARE_DIR/venv"

# Function to create venv if it doesn't exist
ensure_venv() {{
    if [ ! -d "$VENV_DIR" ]; then
        echo "Creating virtual environment at $VENV_DIR"
        python3 -m venv "$VENV_DIR"
        
        # Install requirements if requirements.txt exists
        if [ -f "$SHARE_DIR/requirements.txt" ]; then
            echo "Installing requirements from $SHARE_DIR/requirements.txt"
            "$VENV_DIR/bin/pip" install -r "$SHARE_DIR/requirements.txt"
        fi
    fi
}}

# Function to start the server
start_server() {{
    # Ensure venv exists
    ensure_venv
    
    # Activate the virtual environment
    source $VENV_DIR/bin/activate
    
    # Change to share directory where main.py is located
    cd $SHARE_DIR
    
    # Start the proxy server
    uvicorn main:app --host 0.0.0.0 --port 8000
}}

# Function to start as daemon
start_daemon() {{
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
    
    # Start in background with nohup
    nohup bash -c "source $VENV_DIR/bin/activate && cd $SHARE_DIR && uvicorn main:app --host 0.0.0.0 --port 8000" > /dev/null 2>&1 &
    PID=$!
    echo $PID > "$PIDFILE"
    echo "AISBF started in background (PID: $PID)"
}}

# Function to check status
check_status() {{
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
}}

# Function to stop the daemon
stop_daemon() {{
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
}}

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
"""
        
        dst = bin_dir / 'aisbf'
        
        with open(dst, 'w') as f:
            f.write(script_content)
        
        os.chmod(dst, 0o755)
        print(f"Installed 'aisbf' script to {dst}")

setup(
    name="aisbf",
    version="0.1.0",
    author="AISBF Contributors",
    author_email="stefy@nexlab.net",
    description="AISBF - AI Service Broker Framework || AI Should Be Free - A modular proxy server for managing multiple AI provider integrations",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://git.nexlab.net/nexlab/aisbf.git",
    packages=find_packages(),
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "Topic :: Software Development :: Libraries :: Python Modules",
        "License :: OSI Approved :: GNU General Public License v3 or later (GPLv3+)",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Operating System :: OS Independent",
    ],
    python_requires=">=3.8",
    install_requires=requirements,
    include_package_data=True,
    package_data={
        "aisbf": ["*.json"],
    },
    data_files=[
        # Install to /usr/local/share/aisbf (system-wide)
        ('share/aisbf', [
            'main.py',
            'requirements.txt',
            'config/providers.json',
            'config/rotations.json',
        ]),
    ],
    entry_points={
        "console_scripts": [
            "aisbf=main:main",
        ],
    },
    cmdclass={
        'install': InstallCommand,
    },
)