"""
Copyright (C) 2026 Stefy Lanza <stefy@nexlab.net>

AISBF - AI Service Broker Framework || AI Should Be Free

Python CLI wrapper that calls the aisbf.sh shell script.

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

import os
import sys
import subprocess
import sysconfig
import shutil
from pathlib import Path


# Files and directories that must be present in the share directory for the
# server to start correctly.
_REQUIRED_FILES = ['aisbf.sh', 'main.py', 'requirements.txt']
_REQUIRED_DIRS  = ['templates', 'static', 'config']


def _share_dir_candidates():
    """Return candidate share directories in priority order, deduplicated."""
    seen = set()
    result = []

    def add(p):
        key = str(p)
        if key not in seen:
            seen.add(key)
            result.append(Path(p))

    # sysconfig paths for the running Python interpreter — covers venvs,
    # system installs, and user installs regardless of pip's install scheme.
    add(Path(sysconfig.get_path('data')) / 'share' / 'aisbf')

    for scheme in ('posix_user', 'posix_prefix', 'posix_home'):
        try:
            add(Path(sysconfig.get_path('data', scheme)) / 'share' / 'aisbf')
        except Exception:
            pass

    # Legacy hardcoded fallbacks
    add(Path('/usr/local/share/aisbf'))
    add(Path('/usr/share/aisbf'))
    add(Path.home() / '.local' / 'share' / 'aisbf')

    return result


def _share_dir_is_complete(d):
    """Return True only if d contains every file/dir the server needs."""
    return all((d / f).exists() for f in _REQUIRED_FILES + _REQUIRED_DIRS)


def _find_share_dir():
    """Return the first complete share directory found, or None."""
    for candidate in _share_dir_candidates():
        if _share_dir_is_complete(candidate):
            return candidate
    return None


def _pkg_bundle_dir():
    """
    Return the aisbf/_share/ directory bundled inside the installed package,
    or None if it doesn't exist (e.g. editable source install before build).
    Falls back to the project root for editable installs.
    """
    try:
        import aisbf as _pkg
        pkg_dir = Path(_pkg.__file__).parent

        # Normal wheel install: _share/ populated by build_py hook
        share = pkg_dir / '_share'
        if share.exists() and (share / 'main.py').exists():
            return share

        # Editable install: files live in the project root (one level up)
        project_root = pkg_dir.parent
        if (project_root / 'main.py').exists():
            return project_root

    except Exception:
        pass
    return None


def _bootstrap_share_dir():
    """
    Copy all runtime files from the bundled package data to
    ~/.local/share/aisbf/ and return the destination path, or None on failure.
    """
    bundle = _pkg_bundle_dir()
    if bundle is None:
        return None

    dest = Path.home() / '.local' / 'share' / 'aisbf'
    try:
        dest.mkdir(parents=True, exist_ok=True)

        for fname in _REQUIRED_FILES:
            src = bundle / fname
            if src.exists():
                shutil.copy2(src, dest / fname)
                if fname.endswith('.sh'):
                    p = dest / fname
                    p.chmod(p.stat().st_mode | 0o755)

        for dname in _REQUIRED_DIRS:
            src = bundle / dname
            dst = dest / dname
            if src.exists():
                if dst.exists():
                    shutil.rmtree(dst)
                shutil.copytree(src, dst)

        return dest if _share_dir_is_complete(dest) else None

    except Exception as e:
        print(f"Warning: could not bootstrap share directory: {e}", file=sys.stderr)
        return None


def main():
    share_dir = _find_share_dir()

    if share_dir is None:
        print(
            "AISBF share directory not found or incomplete — bootstrapping from package data …",
            file=sys.stderr,
        )
        share_dir = _bootstrap_share_dir()

        if share_dir:
            print(
                f"Bootstrapped to {share_dir}. Future runs will use this location.",
                file=sys.stderr,
            )
        else:
            checked = '\n'.join(f'  - {p}' for p in _share_dir_candidates())
            print(
                "Error: could not set up the AISBF share directory.\n\n"
                "Checked locations:\n"
                f"{checked}\n\n"
                "The wheel may have been built without runtime files.\n"
                "Re-install from a source distribution to fix this:\n"
                "  pip install aisbf --no-binary aisbf\n"
                "Or install system-wide as root:\n"
                "  sudo pip install aisbf",
                file=sys.stderr,
            )
            sys.exit(1)

    script_path = share_dir / 'aisbf.sh'

    try:
        result = subprocess.run([str(script_path)] + sys.argv[1:], check=False)
        sys.exit(result.returncode)
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as e:
        print(f"Error executing AISBF script: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
