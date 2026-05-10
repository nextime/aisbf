from pathlib import Path

PYTHON_LICENSE_HEADER = [
    '"""',
    'Copyright (C) 2026 Stefy Lanza <stefy@nexlab.net>',
    '',
    'AISBF - AI Service Broker Framework || AI Should Be Free',
    '',
    'This program is free software: you can redistribute it and/or modify',
    'it under the terms of the GNU General Public License as published by',
    'the Free Software Foundation, either version 3 of the License, or',
    '(at your option) any later version.',
    '',
    'This program is distributed in the hope that it will be useful,',
    'but WITHOUT ANY WARRANTY; without even the implied warranty of',
    'MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the',
    'GNU General Public License for more details.',
    '',
    'You should have received a copy of the GNU General Public License',
    'along with this program.  If not, see <https://www.gnu.org/licenses/>.',
    '"""',
]


def test_target_studio_python_files_use_standard_aisbf_license_header():
    repo_root = Path(__file__).resolve().parents[1]
    target_files = [
        repo_root / 'aisbf' / 'studio.py',
        repo_root / 'tests' / 'test_studio.py',
        repo_root / 'tests' / 'routes' / 'test_dashboard_studio.py',
    ]

    for path in target_files:
        lines = path.read_text(encoding='utf-8').splitlines()
        assert lines[: len(PYTHON_LICENSE_HEADER)] == PYTHON_LICENSE_HEADER, path.as_posix()
