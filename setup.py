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
            share_dir = Path('/usr/share/aisbf')
        
        # Create the bin directory if it doesn't exist
        bin_dir.mkdir(parents=True, exist_ok=True)
        
        # Copy the aisbf.sh script from the share directory to the bin directory
        src = share_dir / 'aisbf.sh'
        dst = bin_dir / 'aisbf'
        
        # Copy the script
        import shutil
        shutil.copy(src, dst)
        
        # Make it executable
        os.chmod(dst, 0o755)
        print(f"Installed 'aisbf' script to {dst}")

setup(
    name="aisbf",
    version="0.2.0",
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
        # Install to /usr/share/aisbf (system-wide)
        ('share/aisbf', [
            'main.py',
            'requirements.txt',
            'aisbf.sh',
            'config/providers.json',
            'config/rotations.json',
            'config/autoselect.json',
            'config/autoselect.md',
        ]),
        # Install aisbf package to share directory for venv installation
        ('share/aisbf/aisbf', [
            'aisbf/__init__.py',
            'aisbf/config.py',
            'aisbf/models.py',
            'aisbf/providers.py',
            'aisbf/handlers.py',
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