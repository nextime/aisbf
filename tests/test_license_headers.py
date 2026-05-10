from pathlib import Path

TASK_1_STUDIO_PYTHON_TARGETS = (
    Path("aisbf/studio.py"),
    Path("tests/test_studio.py"),
    Path("tests/routes/test_dashboard_studio.py"),
)

EXPECTED_TASK_1_STUDIO_PYTHON_TARGETS = (
    Path("aisbf/studio.py"),
    Path("tests/test_studio.py"),
    Path("tests/routes/test_dashboard_studio.py"),
)

EXPECTED_HEADER_SNIPPETS = (
    'Copyright (C) 2026 Stefy Lanza <stefy@nexlab.net>',
    'AISBF - AI Service Broker Framework || AI Should Be Free',
    'This program is free software: you can redistribute it and/or modify',
    'it under the terms of the GNU General Public License as published by',
    'This program is distributed in the hope that it will be useful,',
    'MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.',
    'GNU General Public License for more details.',
    'You should have received a copy of the GNU General Public License',
)


def _read_top_level_docstring(path: Path) -> str:
    content = path.read_text(encoding="utf-8")
    assert content.startswith('"""'), path.as_posix()

    closing_index = content.find('"""', 3)
    assert closing_index != -1, path.as_posix()

    return content[3:closing_index]


def test_task_1_header_test_targets_only_the_planned_studio_python_files():
    assert TASK_1_STUDIO_PYTHON_TARGETS == EXPECTED_TASK_1_STUDIO_PYTHON_TARGETS


def test_task_1_studio_python_files_use_aisbf_gpl_docstring_header_convention():
    repo_root = Path(__file__).resolve().parents[1]

    for relative_path in TASK_1_STUDIO_PYTHON_TARGETS:
        header = _read_top_level_docstring(repo_root / relative_path)
        assert header.startswith('\n'), relative_path.as_posix()
        for snippet in EXPECTED_HEADER_SNIPPETS:
            assert snippet in header, f"{relative_path.as_posix()}: missing {snippet!r}"
