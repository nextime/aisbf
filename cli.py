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
from pathlib import Path


def main():
    """Main entry point for the aisbf CLI - calls the aisbf.sh shell script"""
    
    # Determine the correct script path at runtime
    # Check for system installation first (/usr/local/share/aisbf/aisbf.sh)
    script_path = Path("/usr/local/share/aisbf/aisbf.sh")
    if not script_path.exists():
        # Fall back to user installation (~/.local/share/aisbf/aisbf.sh)
        script_path = Path.home() / ".local" / "share" / "aisbf" / "aisbf.sh"
    
    # Check if the script exists
    if not script_path.exists():
        print(f"Error: AISBF script not found at {script_path}", file=sys.stderr)
        print("Please ensure AISBF is properly installed.", file=sys.stderr)
        print(f"Expected locations:", file=sys.stderr)
        print(f"  - /usr/local/share/aisbf/aisbf.sh (system-wide)", file=sys.stderr)
        print(f"  - ~/.local/share/aisbf/aisbf.sh (user installation)", file=sys.stderr)
        sys.exit(1)
    
    # Execute the shell script with all arguments passed to this Python script
    try:
        # Use subprocess to run the shell script
        result = subprocess.run(
            [str(script_path)] + sys.argv[1:],
            check=False
        )
        # Exit with the same exit code as the shell script
        sys.exit(result.returncode)
    except KeyboardInterrupt:
        # Handle Ctrl-C gracefully
        sys.exit(130)  # Standard exit code for SIGINT (128 + 2)
    except Exception as e:
        print(f"Error executing AISBF script: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()