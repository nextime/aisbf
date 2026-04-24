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
    # system installs, and user installs regardless of scheme.
    add(Path(sysconfig.get_path('data')) / 'share' / 'aisbf')

    for scheme in ('posix_user', 'posix_prefix', 'posix_home'):
        try:
            add(Path(sysconfig.get_path('data', scheme)) / 'share' / 'aisbf')
        except Exception:
            pass

    # Legacy hardcoded fallbacks (setup.py installs here for system-wide)
    add(Path('/usr/local/share/aisbf'))
    add(Path('/usr/share/aisbf'))
    add(Path.home() / '.local' / 'share' / 'aisbf')

    return result


def _find_share_dir():
    """Return the first candidate that contains aisbf.sh, or None."""
    for candidate in _share_dir_candidates():
        if (candidate / 'aisbf.sh').exists():
            return candidate
    return None


def _bootstrap_from_package():
    """
    Last-resort: copy aisbf.sh from the bundled package data to
    ~/.local/share/aisbf/ so the user can at least run the script.
    The other runtime files (main.py, templates, …) still need to be
    present — this only fixes the 'aisbf.sh not found' error.
    """
    try:
        import aisbf as _pkg
        bundled = Path(_pkg.__file__).parent / 'aisbf.sh'
        if not bundled.exists():
            return None

        dest_dir = Path.home() / '.local' / 'share' / 'aisbf'
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / 'aisbf.sh'
        shutil.copy2(str(bundled), str(dest))
        dest.chmod(dest.stat().st_mode | 0o755)
        return dest_dir
    except Exception:
        return None


def main():
    share_dir = _find_share_dir()

    if share_dir is None:
        share_dir = _bootstrap_from_package()
        if share_dir:
            print(
                "Warning: AISBF data files were not installed by pip to the expected\n"
                f"location. Bootstrapped aisbf.sh to {share_dir}.\n"
                "If the server fails to start, runtime files (main.py, templates/,\n"
                "static/, config/, requirements.txt) may be missing from that directory.\n"
                "Re-install from source to fix this:\n"
                "  pip install aisbf --no-binary aisbf",
                file=sys.stderr,
            )

    if share_dir is None or not (share_dir / 'aisbf.sh').exists():
        checked = '\n'.join(f'  - {p}' for p in _share_dir_candidates())
        print(
            "Error: AISBF share directory not found.\n"
            "The data files may not have been installed correctly from the wheel.\n\n"
            "Checked locations:\n"
            f"{checked}\n\n"
            "To fix, reinstall from source so pip can place files correctly:\n"
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
