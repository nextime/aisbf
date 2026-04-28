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
from setuptools.command.build_py import build_py as _build_py
from pathlib import Path
import os
import shutil
import sys

# Read the contents of README file
this_directory = Path(__file__).parent
long_description = (this_directory / "README.md").read_text() if (this_directory / "README.md").exists() else ""

# Read requirements
requirements = []
if (this_directory / "requirements.txt").exists():
    with open(this_directory / "requirements.txt") as f:
        requirements = [line.strip() for line in f if line.strip() and not line.startswith("#")]

class build_py(_build_py):
    """Populate aisbf/_share/ with runtime files before the wheel is assembled.

    data_files in wheels are not reliably installed by pip for all install
    modes (user vs system, --break-system-packages, etc.).  Bundling the
    runtime files as package_data inside aisbf/_share/ guarantees they land
    in site-packages/aisbf/_share/ and can be extracted by cli.py on first run.
    """

    _SHARE_FILES = ['main.py', 'requirements.txt', 'aisbf.sh', 'DOCUMENTATION.md', 'README.md', 'LICENSE.txt']
    _SHARE_DIRS  = ['templates', 'static', 'config', 'aisbf']

    def run(self):
        self._populate_share()
        self._update_package_data()
        super().run()

    def _populate_share(self):
        root = Path(__file__).parent
        share = root / 'aisbf' / '_share'
        # Full clean rebuild so stale files never sneak in
        if share.exists():
            shutil.rmtree(share)
        share.mkdir(exist_ok=True)

        for fname in self._SHARE_FILES:
            src = root / fname
            if src.exists():
                shutil.copy2(src, share / fname)

        for dname in self._SHARE_DIRS:
            src = root / dname
            dst = share / dname
            if src.is_dir():
                # Exclude _share/ when copying the aisbf package — it's the
                # directory we're currently building, so it must not recurse.
                shutil.copytree(src, dst,
                                ignore=shutil.ignore_patterns('_share', '__pycache__', '*.pyc', '*.pyo'))

    def _update_package_data(self):
        """Dynamically register every file copied into _share/ so setuptools
        includes them in the wheel.  The static package_data globs use '**'
        which older setuptools silently ignores; this method is the fix."""
        share = Path(__file__).parent / 'aisbf' / '_share'
        if not share.exists():
            return
        patterns = []
        for f in share.rglob('*'):
            if f.is_file() and '__pycache__' not in f.parts and not f.name.endswith(('.pyc', '.pyo')):
                rel = str(f.relative_to(Path(__file__).parent / 'aisbf'))
                patterns.append(rel)
        pkg_data = self.distribution.package_data
        pkg_data.setdefault('aisbf', []).extend(patterns)


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
    version="0.99.64",
    author="AISBF Contributors",
    author_email="stefy@nexlab.net",
    description="AISBF - AI Service Broker Framework || AI Should Be Free - A modular proxy server for managing multiple AI provider integrations",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://git.nexlab.net/nexlab/aisbf.git",
    packages=find_packages(),
    classifiers=[
        "Development Status :: 4 - Beta",
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
        # Minimal static stubs — the build_py hook's _update_package_data()
        # dynamically appends every file it copies into aisbf/_share/, so
        # '**' glob patterns (unsupported by older setuptools) are not needed.
        "aisbf": [
            "*.json",
            "aisbf.sh",
        ],
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
            'aisbf/cli_mode.py',
            'aisbf/cost_extractor.py',
            'aisbf/streaming_optimization.py',
            'aisbf/analytics.py',
            'aisbf/email_utils.py',
            'aisbf/geolocation.py',
            'aisbf/aisbf.sh',
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
        # aisbf.payments.wallet subpackage
        ('share/aisbf/aisbf/payments/wallet', [
            'aisbf/payments/wallet/__init__.py',
            'aisbf/payments/wallet/manager.py',
            'aisbf/payments/wallet/routes.py',
        ]),
        # Install dashboard templates
        ('share/aisbf/templates', [
            'templates/base.html',
            'templates/blocked.html',
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
            'templates/dashboard/paypal_connect.html',
            'templates/dashboard/cache_settings.html',
            'templates/dashboard/wallet.html',
            'templates/dashboard/usage.html',
            'templates/dashboard/error.html',
        ]),
        # Install static files (extension and favicon)
        ('share/aisbf/static', [
            'static/favicon.ico',
            'static/aisbf-oauth2-extension.zip',
            'static/i18n.js',
        ]),
        ('share/aisbf/static/i18n', [
            'static/i18n/af.json',
            'static/i18n/ar.json',
            'static/i18n/bel.json',
            'static/i18n/bn.json',
            'static/i18n/cs.json',
            'static/i18n/da.json',
            'static/i18n/de.json',
            'static/i18n/el.json',
            'static/i18n/en.json',
            'static/i18n/eo.json',
            'static/i18n/es.json',
            'static/i18n/fa.json',
            'static/i18n/fi.json',
            'static/i18n/fr.json',
            'static/i18n/he.json',
            'static/i18n/hi.json',
            'static/i18n/hu.json',
            'static/i18n/id.json',
            'static/i18n/it.json',
            'static/i18n/ja.json',
            'static/i18n/ko.json',
            'static/i18n/ms.json',
            'static/i18n/nb.json',
            'static/i18n/new.json',
            'static/i18n/nl.json',
            'static/i18n/pl.json',
            'static/i18n/pt.json',
            'static/i18n/qya.json',
            'static/i18n/ro.json',
            'static/i18n/ru.json',
            'static/i18n/sk.json',
            'static/i18n/sv.json',
            'static/i18n/th.json',
            'static/i18n/tlh.json',
            'static/i18n/tr.json',
            'static/i18n/uk.json',
            'static/i18n/vi.json',
            'static/i18n/vul.json',
            'static/i18n/xh.json',
            'static/i18n/zh.json',
            'static/i18n/zu.json',
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
        'build_py': build_py,
        'install': InstallCommand,
    },
)
