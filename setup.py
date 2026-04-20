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
    version="0.99.36",
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
    # Dependencies are installed separately via requirements.txt (e.g., in virtualenv)
    # install_requires=requirements,
    include_package_data=True,
    package_data={
        "aisbf": ["*.json"],
        "": ["templates/**/*.html", "templates/**/*.css", "templates/**/*.js", "static/**/*"],
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
        # Main aisbf module files
        ('share/aisbf/aisbf', [
            'aisbf/__init__.py',
            'aisbf/config.py',
            'aisbf/models.py',
            'aisbf/handlers.py',
            'aisbf/context.py',
            'aisbf/utils.py',
            'aisbf/database.py',
            'aisbf/mcp.py',
            'aisbf/tor.py',
            'aisbf/batching.py',
            'aisbf/cache.py',
            'aisbf/classifier.py',
            'aisbf/cost_extractor.py',
            'aisbf/streaming_optimization.py',
            'aisbf/analytics.py',
            'aisbf/email_utils.py',
        ]),
        # aisbf.providers subpackage
        ('share/aisbf/aisbf/providers', [
            'aisbf/providers/__init__.py',
            'aisbf/providers/base.py',
            'aisbf/providers/google.py',
            'aisbf/providers/openai.py',
            'aisbf/providers/anthropic.py',
            'aisbf/providers/claude.py',
            'aisbf/providers/kilo.py',
            'aisbf/providers/ollama.py',
            'aisbf/providers/codex.py',
            'aisbf/providers/qwen.py',
        ]),
        # aisbf.providers.kiro subpackage
        ('share/aisbf/aisbf/providers/kiro', [
            'aisbf/providers/kiro/__init__.py',
            'aisbf/providers/kiro/handler.py',
            'aisbf/providers/kiro/converters.py',
            'aisbf/providers/kiro/converters_openai.py',
            'aisbf/providers/kiro/models.py',
            'aisbf/providers/kiro/parsers.py',
            'aisbf/providers/kiro/utils.py',
        ]),
        # aisbf.auth subpackage
        ('share/aisbf/aisbf/auth', [
            'aisbf/auth/__init__.py',
            'aisbf/auth/kiro.py',
            'aisbf/auth/claude.py',
            'aisbf/auth/kilo.py',
            'aisbf/auth/codex.py',
            'aisbf/auth/qwen.py',
            'aisbf/auth/google.py',
            'aisbf/auth/github.py',
        ]),
        # aisbf.payments subpackage
        ('share/aisbf/aisbf/payments', [
            'aisbf/payments/__init__.py',
            'aisbf/payments/migrations.py',
            'aisbf/payments/models.py',
            'aisbf/payments/service.py',
            'aisbf/payments/scheduler.py',
        ]),
        # aisbf.payments.crypto subpackage
        ('share/aisbf/aisbf/payments/crypto', [
            'aisbf/payments/crypto/__init__.py',
            'aisbf/payments/crypto/wallet.py',
            'aisbf/payments/crypto/pricing.py',
            'aisbf/payments/crypto/monitor.py',
            'aisbf/payments/crypto/consolidation.py',
        ]),
        # aisbf.payments.fiat subpackage
        ('share/aisbf/aisbf/payments/fiat', [
            'aisbf/payments/fiat/__init__.py',
            'aisbf/payments/fiat/stripe_handler.py',
            'aisbf/payments/fiat/paypal_handler.py',
        ]),
        # aisbf.payments.subscription subpackage
        ('share/aisbf/aisbf/payments/subscription', [
            'aisbf/payments/subscription/__init__.py',
            'aisbf/payments/subscription/manager.py',
            'aisbf/payments/subscription/renewal.py',
            'aisbf/payments/subscription/retry.py',
            'aisbf/payments/subscription/quota.py',
        ]),
        # aisbf.payments.notifications subpackage
        ('share/aisbf/aisbf/payments/notifications', [
            'aisbf/payments/notifications/__init__.py',
            'aisbf/payments/notifications/email.py',
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
            'templates/dashboard/analytics.html',
            'templates/dashboard/user_index.html',
            'templates/dashboard/user_providers.html',
            'templates/dashboard/user_rotations.html',
            'templates/dashboard/user_autoselects.html',
            'templates/dashboard/user_tokens.html',
             'templates/dashboard/rate_limits.html',
             'templates/dashboard/response_cache.html',
             'templates/dashboard/users.html',
            'templates/dashboard/signup.html',
            'templates/dashboard/verify.html',
            'templates/dashboard/forgot_password.html',
            'templates/dashboard/reset_password.html',
            'templates/dashboard/profile.html',
            'templates/dashboard/change_password.html',
            'templates/dashboard/change_email.html',
            'templates/dashboard/delete_account.html',
            'templates/dashboard/admin_tiers.html',
            'templates/dashboard/admin_tier_form.html',
            'templates/dashboard/admin_payment_settings.html',
            'templates/dashboard/pricing.html',
            'templates/dashboard/subscription.html',
            'templates/dashboard/billing.html',
            'templates/dashboard/add_payment_method.html',
            'templates/dashboard/paypal_connect.html',
        ]),
        # Install static files (extension and favicon)
        ('share/aisbf/static', [
            'static/favicon.ico',
            'static/aisbf-oauth2-extension.zip',
        ]),
        ('share/aisbf/static/extension', [
            'static/extension/background.js',
            'static/extension/build.sh',
            'static/extension/content.js',
            'static/extension/generate_icons.py',
            'static/extension/manifest.json',
            'static/extension/options.html',
            'static/extension/options.js',
            'static/extension/popup.html',
            'static/extension/popup.js',
            'static/extension/README.md',
        ]),
        ('share/aisbf/static/extension/icons', [
            'static/extension/icons/icon16.png',
            'static/extension/icons/icon16.svg',
            'static/extension/icons/icon48.png',
            'static/extension/icons/icon48.svg',
            'static/extension/icons/icon128.png',
            'static/extension/icons/icon128.svg',
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