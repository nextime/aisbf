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

from setuptools import setup, find_packages
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
    """Custom install command that adds --user flag for non-root users"""
    
    def initialize_options(self):
        _install.initialize_options(self)
        # Check if running as non-root without --user flag
        if os.geteuid() != 0 and '--user' not in sys.argv:
            print("Installing as non-root user. Adding --user flag for user-local installation.")
            self.user = True

setup(
    name="aisbf",
    version="0.7.0",
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
            'aisbf.sh',
            'DOCUMENTATION.md',
            'README.md',
            'LICENSE.txt',
            'config/providers.json',
            'config/rotations.json',
            'config/autoselect.json',
            'config/autoselect.md',
            'config/condensation_conversational.md',
            'config/condensation_semantic.md',
            'config/aisbf.json',
        ]),
        # Install aisbf package to share directory for venv installation
        ('share/aisbf/aisbf', [
            'aisbf/__init__.py',
            'aisbf/config.py',
            'aisbf/models.py',
            'aisbf/providers.py',
            'aisbf/handlers.py',
            'aisbf/context.py',
            'aisbf/utils.py',
            'aisbf/database.py',
            'aisbf/mcp.py',
            'aisbf/tor.py',
            'aisbf/kiro_auth.py',
            'aisbf/kiro_converters.py',
            'aisbf/kiro_converters_openai.py',
            'aisbf/kiro_models.py',
            'aisbf/kiro_parsers.py',
            'aisbf/kiro_utils.py',
            'aisbf/semantic_classifier.py',
        ]),
        # Install dashboard templates
        ('share/aisbf/templates', [
            'templates/base.html',
        ]),
        ('share/aisbf/templates/dashboard', [
            'templates/dashboard/login.html',
            'templates/dashboard/index.html',
            'templates/dashboard/edit_config.html',
            'templates/dashboard/settings.html',
            'templates/dashboard/providers.html',
            'templates/dashboard/rotations.html',
            'templates/dashboard/autoselect.html',
            'templates/dashboard/prompts.html',
            'templates/dashboard/docs.html',
        ]),
    ],
    entry_points={
        "console_scripts": [
            "aisbf=cli:main",
        ],
    },
    cmdclass={
        'install': InstallCommand,
    },
)