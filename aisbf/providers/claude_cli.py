"""
Copyleft (C) 2026 Stefy Lanza <stefy@nexlab.net>

AISBF - AI Service Broker Framework || AI Should Be Free

Claude CLI mode detection module.

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
"""
import shutil
from typing import Optional

CLAUDE_CLI_MODE: bool = False
CLAUDE_CLI_PATH: Optional[str] = None


def detect_claude_cli() -> bool:
    global CLAUDE_CLI_MODE, CLAUDE_CLI_PATH
    path = shutil.which('claude')
    if path:
        CLAUDE_CLI_MODE = True
        CLAUDE_CLI_PATH = path
        return True
    return False
