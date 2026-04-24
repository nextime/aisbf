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

import importlib.util
import os
import sys
import subprocess
import sysconfig
import shutil
from pathlib import Path


# Files and directories the share directory must contain for the server to start.
_REQUIRED_FILES = ['aisbf.sh', 'main.py', 'requirements.txt']
_REQUIRED_DIRS  = ['templates', 'static', 'config', 'aisbf']


def _is_root():
    return os.getuid() == 0


def _default_share_dest():
    """System dir for root, user dir for everyone else."""
    if _is_root():
        return Path('/usr/local/share/aisbf')
    return Path.home() / '.local' / 'share' / 'aisbf'


def _share_dir_candidates():
    """Return candidate share directories in priority order, deduplicated."""
    seen = set()
    result = []

    def add(p):
        key = str(p)
        if key not in seen:
            seen.add(key)
            result.append(Path(p))

    # sysconfig paths for the running interpreter — covers venvs, system
    # installs, and all user-install schemes regardless of how pip was invoked.
    try:
        add(Path(sysconfig.get_path('data')) / 'share' / 'aisbf')
    except Exception:
        pass

    for scheme in ('posix_user', 'posix_prefix', 'posix_home'):
        try:
            add(Path(sysconfig.get_path('data', scheme)) / 'share' / 'aisbf')
        except Exception:
            pass

    # Hardcoded legacy fallbacks
    add(Path('/usr/local/share/aisbf'))
    add(Path('/usr/share/aisbf'))
    add(Path.home() / '.local' / 'share' / 'aisbf')

    return result


def _share_dir_is_complete(d):
    return all((d / f).exists() for f in _REQUIRED_FILES + _REQUIRED_DIRS)


def _find_share_dir():
    for candidate in _share_dir_candidates():
        if _share_dir_is_complete(candidate):
            return candidate
    return None


def _pkg_bundle_dir():
    """
    Locate the bundle of runtime files shipped inside the aisbf package.

    Uses importlib.util.find_spec() to locate the package on disk without
    executing __init__.py (which would crash trying to load providers.json).

    Two sources, tried in order:
      1. aisbf/_share/   — populated by the build_py hook at wheel-build time
      2. project root    — for editable (pip install -e) installs
    """
    try:
        spec = importlib.util.find_spec('aisbf')
        if spec is None or spec.origin is None:
            return None
        pkg_dir = Path(spec.origin).parent

        share = pkg_dir / '_share'
        if share.is_dir() and (share / 'main.py').exists():
            return share

        # Editable install: package lives inside the source tree
        project_root = pkg_dir.parent
        if (project_root / 'main.py').exists():
            return project_root

    except Exception:
        pass
    return None


def _bootstrap_share_dir():
    """
    Copy all runtime files from the package bundle to the share directory.
    Prints step-by-step progress so the first run is fully traceable.
    Returns the destination Path on success, None on failure.
    """
    _log = lambda msg: print(f"[aisbf bootstrap] {msg}", file=sys.stderr)

    _log("First run — setting up share directory …")
    _log(f"  Python      : {sys.executable} ({sys.version.split()[0]})")
    _log(f"  Running as  : {'root (uid=0)' if _is_root() else f'uid={os.getuid()}'}")
    _log("")

    # ── sysconfig paths ──────────────────────────────────────────────────────
    _log("sysconfig data paths:")
    for scheme in (None, 'posix_user', 'posix_prefix', 'posix_home'):
        try:
            p = sysconfig.get_path('data', scheme) if scheme else sysconfig.get_path('data')
            _log(f"  {scheme or 'default':15s}: {p}")
        except Exception as e:
            _log(f"  {scheme or 'default':15s}: ERROR — {e}")
    _log("")

    # ── candidate share dirs ──────────────────────────────────────────────────
    _log("Candidate share directories:")
    for c in _share_dir_candidates():
        has_sh   = (c / 'aisbf.sh').exists()
        has_main = (c / 'main.py').exists()
        status   = "COMPLETE" if _share_dir_is_complete(c) else \
                   f"partial (aisbf.sh={has_sh}, main.py={has_main})"
        _log(f"  {c}: {status}")
    _log("")

    # ── package bundle ────────────────────────────────────────────────────────
    _log("Package bundle location:")
    try:
        spec = importlib.util.find_spec('aisbf')
        if spec is not None and spec.origin is not None:
            pkg_dir = Path(spec.origin).parent
            _log(f"  Package dir : {pkg_dir}")

            share = pkg_dir / '_share'
            _log(f"  _share exists: {share.exists()}")
            if share.is_dir():
                contents = sorted(p.name for p in share.iterdir())
                _log(f"  _share contents: {contents}")
        else:
            _log("  Package 'aisbf' not found by importlib")

        bundle = _pkg_bundle_dir()
        _log(f"  Bundle source: {bundle}")
    except Exception as e:
        _log(f"  ERROR inspecting package: {e}")
        bundle = None

    _log("")

    if bundle is None:
        _log("ERROR: No bundle source found.")
        _log("  The wheel was probably built before the build_py hook was added.")
        _log("  Rebuild the wheel from the current source and reinstall:")
        _log("    python -m build")
        _log("    pip install dist/aisbf-*.whl --force-reinstall")
        return None

    # ── copy files ────────────────────────────────────────────────────────────
    dest = _default_share_dest()
    _log(f"Destination : {dest}")

    try:
        dest.mkdir(parents=True, exist_ok=True)
        _log(f"  Created directory: {dest}")

        for fname in _REQUIRED_FILES:
            src = bundle / fname
            if src.exists():
                shutil.copy2(src, dest / fname)
                if fname.endswith('.sh'):
                    p = dest / fname
                    p.chmod(p.stat().st_mode | 0o755)
                _log(f"  Copied : {fname}")
            else:
                _log(f"  MISSING: {fname} (not in bundle — bundle may be incomplete)")

        for dname in _REQUIRED_DIRS:
            src = bundle / dname
            dst = dest / dname
            if src.is_dir():
                if dst.exists():
                    shutil.rmtree(dst)
                shutil.copytree(src, dst)
                n = sum(1 for _ in dst.rglob('*') if _.is_file())
                _log(f"  Copied : {dname}/ ({n} files)")
            else:
                _log(f"  MISSING: {dname}/ (not in bundle)")

        if _share_dir_is_complete(dest):
            _log(f"SUCCESS: Share directory is ready at {dest}")
            return dest

        missing = [f for f in _REQUIRED_FILES + _REQUIRED_DIRS
                   if not (dest / f).exists()]
        _log(f"INCOMPLETE after copy — still missing: {missing}")
        return None

    except Exception as e:
        _log(f"ERROR during copy: {e}")
        import traceback
        traceback.print_exc(file=sys.stderr)
        return None


def main():
    share_dir = _find_share_dir()

    if share_dir is None:
        share_dir = _bootstrap_share_dir()

    if share_dir is None:
        checked = '\n'.join(f'  - {p}' for p in _share_dir_candidates())
        dest = _default_share_dest()
        print(
            f"\nError: could not set up the AISBF share directory at {dest}.\n\n"
            "Locations checked:\n"
            f"{checked}\n\n"
            "The wheel was likely built before the build_py hook was added.\n"
            "Rebuild from the current source and reinstall:\n"
            "  python -m build\n"
            "  pip install dist/aisbf-*.whl --force-reinstall",
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
