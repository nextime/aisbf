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
import shutil
import sys
import subprocess

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
        # Run the standard install
        _install.run(self)
        
        # Install config files
        self._install_config_files()
        
        # Install main.py to share directory
        self._install_main_file()
        
        # Create venv and install requirements
        self._create_venv_and_install_requirements()
        
        # Install the aisbf script
        self._install_aisbf_script()
    
    def _create_venv_and_install_requirements(self):
        """Create a virtual environment and install requirements"""
        # Determine installation directory
        if '--user' in sys.argv or os.geteuid() != 0:
            # User installation - use ~/.local
            install_dir = Path.home() / '.local'
        else:
            # System installation - use /usr/local
            install_dir = Path('/usr/local')
        
        venv_dir = install_dir / 'aisbf-venv'
        
        # Create venv if it doesn't exist
        if not venv_dir.exists():
            print(f"Creating virtual environment at {venv_dir}")
            subprocess.run([sys.executable, '-m', 'venv', str(venv_dir)], check=True)
        else:
            print(f"Virtual environment already exists at {venv_dir}")
        
        # Install requirements in the venv
        pip_path = venv_dir / 'bin' / 'pip'
        requirements_path = this_directory / 'requirements.txt'
        
        if requirements_path.exists():
            print(f"Installing requirements from {requirements_path}")
            subprocess.run([str(pip_path), 'install', '-r', str(requirements_path)], check=True)
        else:
            print("No requirements.txt found, skipping dependency installation")
    
    def _install_config_files(self):
        """Install config files to the appropriate share directory"""
        # Determine the share directory
        if '--user' in sys.argv or os.geteuid() != 0:
            # User installation - use ~/.local/share
            share_dir = Path.home() / '.local' / 'share' / 'aisbf'
        else:
            # System installation - use /usr/local/share
            share_dir = Path('/usr/local/share/aisbf')
        
        # Create the share directory if it doesn't exist
        share_dir.mkdir(parents=True, exist_ok=True)
        
        # Copy config files
        config_dir = this_directory / 'config'
        if config_dir.exists():
            for config_file in config_dir.glob('*.json'):
                dst = share_dir / config_file.name
                shutil.copy2(config_file, dst)
                print(f"Installed config file {config_file.name} to {dst}")
        else:
            print(f"Warning: Config directory {config_dir} not found")
    
    def _install_main_file(self):
        """Install main.py to the appropriate share directory"""
        # Determine the share directory
        if '--user' in sys.argv or os.geteuid() != 0:
            # User installation - use ~/.local/share
            share_dir = Path.home() / '.local' / 'share' / 'aisbf'
        else:
            # System installation - use /usr/local/share
            share_dir = Path('/usr/local/share/aisbf')
        
        # Create the share directory if it doesn't exist
        share_dir.mkdir(parents=True, exist_ok=True)
        
        # Copy main.py
        main_file = this_directory / 'main.py'
        if main_file.exists():
            dst = share_dir / 'main.py'
            shutil.copy2(main_file, dst)
            print(f"Installed main.py to {dst}")
        else:
            print(f"Warning: main.py not found")
    
    def _install_aisbf_script(self):
        """Install the aisbf script that uses the venv"""
        # Determine the installation directory
        if '--user' in sys.argv or os.geteuid() != 0:
            # User installation - use ~/.local/bin
            bin_dir = Path.home() / '.local' / 'bin'
            venv_dir = Path.home() / '.local' / 'aisbf-venv'
            share_dir = Path.home() / '.local' / 'share' / 'aisbf'
        else:
            # System installation - use /usr/local/bin
            bin_dir = Path('/usr/local/bin')
            venv_dir = Path('/usr/local') / 'aisbf-venv'
            share_dir = Path('/usr/local/share/aisbf')
        
        # Create the bin directory if it doesn't exist
        bin_dir.mkdir(parents=True, exist_ok=True)
        
        # Create the aisbf script that uses the venv
        script_content = f"""#!/bin/bash
# AISBF - AI Service Broker Framework || AI Should Be Free
# This script manages the AISBF server using the installed virtual environment

PIDFILE="/tmp/aisbf.pid"
VENV_DIR="{venv_dir}"
SHARE_DIR="{share_dir}"

# Function to start the server
start_server() {{
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
    entry_points={
        "console_scripts": [
            "aisbf=main:main",
        ],
    },
    cmdclass={
        'install': InstallCommand,
    },
)