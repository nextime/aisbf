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
# Clean script for removing build artifacts and temporary files

set -e

echo "=========================================="
echo "Cleaning AISBF Build Artifacts"
echo "=========================================="
echo ""

# Remove distribution directory
if [ -d "dist" ]; then
    echo "Removing dist/ directory..."
    rm -rf dist/
    echo "  ✓ dist/ removed"
else
    echo "  - dist/ not found (skipping)"
fi

# Remove build directory
if [ -d "build" ]; then
    echo "Removing build/ directory..."
    rm -rf build/
    echo "  ✓ build/ removed"
else
    echo "  - build/ not found (skipping)"
fi

# Remove egg-info directories
if ls *.egg-info 1> /dev/null 2>&1; then
    echo "Removing *.egg-info directories..."
    rm -rf *.egg-info
    echo "  ✓ *.egg-info removed"
else
    echo "  - *.egg-info not found (skipping)"
fi

# Remove Python cache directories
if [ -d "__pycache__" ]; then
    echo "Removing __pycache__/ directory..."
    rm -rf __pycache__
    echo "  ✓ __pycache__/ removed"
else
    echo "  - __pycache__/ not found (skipping)"
fi

# Remove Python cache directories in subdirectories
if find . -type d -name "__pycache__" | grep -q .; then
    echo "Removing __pycache__/ directories in subdirectories..."
    find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
    echo "  ✓ __pycache__/ in subdirectories removed"
else
    echo "  - __pycache__/ in subdirectories not found (skipping)"
fi

# Remove .pyc files
if find . -type f -name "*.pyc" | grep -q .; then
    echo "Removing .pyc files..."
    find . -type f -name "*.pyc" -delete
    echo "  ✓ .pyc files removed"
else
    echo "  - .pyc files not found (skipping)"
fi

# Remove .pyo files
if find . -type f -name "*.pyo" | grep -q .; then
    echo "Removing .pyo files..."
    find . -type f -name "*.pyo" -delete
    echo "  ✓ .pyo files removed"
else
    echo "  - .pyo files not found (skipping)"
fi

# Remove .pyd files
if find . -type f -name "*.pyd" | grep -q .; then
    echo "Removing .pyd files..."
    find . -type f -name "*.pyd" -delete
    echo "  ✓ .pyd files removed"
else
    echo "  - .pyd files not found (skipping)"
fi

# Remove .pytest_cache directory
if [ -d ".pytest_cache" ]; then
    echo "Removing .pytest_cache/ directory..."
    rm -rf .pytest_cache
    echo "  ✓ .pytest_cache/ removed"
else
    echo "  - .pytest_cache/ not found (skipping)"
fi

# Remove .mypy_cache directory
if [ -d ".mypy_cache" ]; then
    echo "Removing .mypy_cache/ directory..."
    rm -rf .mypy_cache
    echo "  ✓ .mypy_cache/ removed"
else
    echo "  - .mypy_cache/ not found (skipping)"
fi

# Remove .coverage files
if [ -f ".coverage" ]; then
    echo "Removing .coverage file..."
    rm -f .coverage
    echo "  ✓ .coverage removed"
else
    echo "  - .coverage not found (skipping)"
fi

# Remove htmlcov directory
if [ -d "htmlcov" ]; then
    echo "Removing htmlcov/ directory..."
    rm -rf htmlcov
    echo "  ✓ htmlcov/ removed"
else
    echo "  - htmlcov/ not found (skipping)"
fi

# Remove _share directory (PyPI packaging artifacts)
if [ -d "_share" ]; then
    echo "Removing _share/ directory..."
    rm -rf _share
    echo "  ✓ _share/ removed"
else
    echo "  - _share/ not found (skipping)"
fi

# Remove __pycache__ in aisbf module
if [ -d "aisbf/__pycache__" ]; then
    echo "Removing aisbf/__pycache__/ directory..."
    rm -rf aisbf/__pycache__
    echo "  ✓ aisbf/__pycache__/ removed"
else
    echo "  - aisbf/__pycache__/ not found (skipping)"
fi

# Remove additional files:
rm -f debug.log || true
rm -f *.db || true
rm -f *.sqlite3 || true

echo ""
echo "=========================================="
echo "Clean completed successfully!"
echo "=========================================="
echo ""
echo "All build artifacts and temporary files have been removed."
echo ""
