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
# Build script for creating PyPI distribution packages

set -e

echo "=========================================="
echo "Building AISBF Package for PyPI"
echo "=========================================="
echo ""

# Check if build and twine are installed
if ! command -v python &> /dev/null; then
    echo "Error: Python is not installed or not in PATH"
    exit 1
fi

# Function to run pip with --break-system-packages if needed
pip_install() {
    # Try without --break-system-packages first
    if pip install "$@" 2>&1 | grep -q "externally-managed-environment"; then
        echo "System requires --break-system-packages flag, retrying..."
        pip install --break-system-packages "$@"
    elif ! pip install "$@" 2>&1; then
        # If first attempt failed, check if it's the externally-managed error
        if pip install "$@" 2>&1 | grep -q "externally-managed-environment"; then
            echo "System requires --break-system-packages flag, retrying..."
            pip install --break-system-packages "$@"
        else
            # Re-run to show the actual error
            pip install "$@"
        fi
    fi
}

# Install build tools if not already installed
echo "Checking for build tools..."
if ! python -m build --version &> /dev/null; then
    echo "Installing build and twine..."
    pip_install build twine
fi

# Build the extension first
echo ""
echo "Building OAuth2 extension..."
if [ -f "static/extension/build.sh" ]; then
    cd static/extension
    bash build.sh
    cd ../..
    echo "Extension built successfully"
else
    echo "Warning: Extension build script not found, skipping extension build"
fi

# Clean previous builds
echo ""
echo "Cleaning previous build artifacts..."
rm -rf dist/ build/ *.egg-info

# Build the package
echo ""
echo "Building package..."
python -m build

# Verify the package
echo ""
echo "Verifying package..."
twine check dist/*

# Display results
echo ""
echo "=========================================="
echo "Build completed successfully!"
echo "=========================================="
echo ""
echo "Created files:"
ls -lh dist/
echo ""
echo "To upload to TestPyPI:"
echo "  python -m twine upload --repository testpypi dist/*"
echo ""
echo "To upload to PyPI:"
echo "  python -m twine upload dist/*"
echo ""