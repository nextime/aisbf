# Studio License Header Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the existing AISBF GPL/Copyleft license header pattern to the newly added Studio-related files that currently lack it, without changing behavior.

**Architecture:** This change is a narrow file-header normalization pass scoped only to the new Studio Python, HTML, JS, CSS, and test files. The implementation reuses existing per-file-type header conventions already present in the repository, inserts them at the top of the target files, and verifies the Studio test slice still passes afterward.

**Tech Stack:** Python, Jinja2/HTML, JavaScript, CSS, pytest, git

---

## File Structure

**Python source and tests:**
- Modify: `aisbf/studio.py` - add the standard AISBF Python Copyleft/GPL header above imports
- Modify: `tests/test_studio.py` - add the standard AISBF Python Copyleft/GPL header above imports
- Modify: `tests/routes/test_dashboard_studio.py` - add the standard AISBF Python Copyleft/GPL header above imports

**Frontend files:**
- Modify: `templates/dashboard/studio.html` - add the standard AISBF HTML GPL header before template markup
- Modify: `static/dashboard/studio.js` - add a JS block-comment GPL header before executable code
- Modify: `static/dashboard/studio.css` - add a CSS block-comment GPL header before any selectors or declarations

**Validation:**
- Test: `tests/test_studio.py`
- Test: `tests/routes/test_dashboard_studio.py`

---

### Task 1: Add Python-style license headers to Studio Python files

**Files:**
- Modify: `aisbf/studio.py:1`
- Modify: `tests/test_studio.py:1`
- Modify: `tests/routes/test_dashboard_studio.py:1`
- Test: `tests/test_studio.py`
- Test: `tests/routes/test_dashboard_studio.py`

- [ ] **Step 1: Write the failing tests that assert missing Python headers**

Create `tests/test_license_headers.py`:

```python
from pathlib import Path


def _read_text(relative_path: str) -> str:
    return Path(relative_path).read_text(encoding="utf-8")


def test_studio_python_module_has_license_header():
    text = _read_text("aisbf/studio.py")
    assert "Copyleft (C) 2026 Stefy Lanza <stefy@nexlab.net>" in text.splitlines()[:20]
    assert "GNU General Public License" in text[:600]



def test_studio_unit_test_has_license_header():
    text = _read_text("tests/test_studio.py")
    assert "Copyleft (C) 2026 Stefy Lanza <stefy@nexlab.net>" in text.splitlines()[:20]
    assert "GNU General Public License" in text[:600]



def test_studio_route_test_has_license_header():
    text = _read_text("tests/routes/test_dashboard_studio.py")
    assert "Copyleft (C) 2026 Stefy Lanza <stefy@nexlab.net>" in text.splitlines()[:20]
    assert "GNU General Public License" in text[:600]
```

- [ ] **Step 2: Run the header tests to verify they fail**

Run: `PYTHONPATH=/working/aisbf pytest tests/test_license_headers.py -v`

Expected: FAIL because the three Python files currently do not contain the header text near the top.

- [ ] **Step 3: Add the standard Python license header to `aisbf/studio.py`**

Insert this exact top-of-file block before the existing imports in `aisbf/studio.py`:

```python
"""
Copyleft (C) 2026 Stefy Lanza <stefy@nexlab.net>

AISBF - AI Service Broker Framework || AI Should Be Free

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
```

- [ ] **Step 4: Add the same Python license header to `tests/test_studio.py` and `tests/routes/test_dashboard_studio.py`**

Insert the same block from Step 3 at line 1 of each file, before any imports.

- [ ] **Step 5: Run the Python header tests to verify they pass**

Run: `PYTHONPATH=/working/aisbf pytest tests/test_license_headers.py -v`

Expected: PASS for all three header assertions.

- [ ] **Step 6: Run the Studio test slice to confirm no behavior changed**

Run: `PYTHONPATH=/working/aisbf pytest tests/test_studio.py tests/routes/test_dashboard_studio.py -v`

Expected: PASS for the existing Studio tests.

- [ ] **Step 7: Commit**

```bash
git add aisbf/studio.py tests/test_studio.py tests/routes/test_dashboard_studio.py tests/test_license_headers.py
git commit -m "chore(license): add Python headers to Studio files"
```

---

### Task 2: Add frontend license headers to the Studio HTML, JS, and CSS files

**Files:**
- Modify: `templates/dashboard/studio.html:1`
- Modify: `static/dashboard/studio.js:1`
- Modify: `static/dashboard/studio.css:1`
- Modify: `tests/test_license_headers.py`
- Test: `tests/test_license_headers.py`
- Test: `tests/test_studio.py`
- Test: `tests/routes/test_dashboard_studio.py`

- [ ] **Step 1: Extend the failing header tests for HTML, JS, and CSS targets**

Append to `tests/test_license_headers.py`:

```python

def test_studio_template_has_license_header():
    text = _read_text("templates/dashboard/studio.html")
    assert "Copyright (C) 2026 Stefy Lanza <stefy@nexlab.net>" in text[:400]
    assert "GNU General Public License" in text[:700]



def test_studio_javascript_has_license_header():
    text = _read_text("static/dashboard/studio.js")
    assert "Copyright (C) 2026 Stefy Lanza <stefy@nexlab.net>" in text[:400]
    assert "GNU General Public License" in text[:700]



def test_studio_css_has_license_header():
    text = _read_text("static/dashboard/studio.css")
    assert "Copyright (C) 2026 Stefy Lanza <stefy@nexlab.net>" in text[:400]
    assert "GNU General Public License" in text[:700]
```

- [ ] **Step 2: Run the header tests to verify the frontend cases fail**

Run: `PYTHONPATH=/working/aisbf pytest tests/test_license_headers.py -v`

Expected: FAIL for the HTML, JS, and CSS header checks while the Python ones pass.

- [ ] **Step 3: Add the HTML license header to `templates/dashboard/studio.html`**

Insert this exact header before `{% extends "base.html" %}`:

```html
<!--
Copyright (C) 2026 Stefy Lanza <stefy@nexlab.net>

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
-->
```

- [ ] **Step 4: Add the JS and CSS block-comment headers**

Insert this exact block at the top of `static/dashboard/studio.js` and `static/dashboard/studio.css`:

```javascript
/*
 * Copyright (C) 2026 Stefy Lanza <stefy@nexlab.net>
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with this program.  If not, see <https://www.gnu.org/licenses/>.
 */
```

Use the same text in CSS comment syntax (`/* ... */`) without changing any runtime code below it.

- [ ] **Step 5: Run the header tests to verify all six files now pass**

Run: `PYTHONPATH=/working/aisbf pytest tests/test_license_headers.py -v`

Expected: PASS for all six target files.

- [ ] **Step 6: Re-run the Studio functional tests**

Run: `PYTHONPATH=/working/aisbf pytest tests/test_studio.py tests/routes/test_dashboard_studio.py -v`

Expected: PASS for the Studio-related tests, confirming header insertion did not alter behavior.

- [ ] **Step 7: Commit**

```bash
git add templates/dashboard/studio.html static/dashboard/studio.js static/dashboard/studio.css tests/test_license_headers.py
git commit -m "chore(license): add frontend headers to Studio files"
```

---

### Task 3: Final scoped verification and diff review

**Files:**
- Test: `tests/test_license_headers.py`
- Test: `tests/test_studio.py`
- Test: `tests/routes/test_dashboard_studio.py`

- [ ] **Step 1: Run the full scoped verification command**

Run: `PYTHONPATH=/working/aisbf pytest tests/test_license_headers.py tests/test_studio.py tests/routes/test_dashboard_studio.py -v`

Expected: PASS for all header and Studio tests.

- [ ] **Step 2: Inspect the diff to confirm scope containment**

Run: `git diff --stat HEAD~2..HEAD`

Expected: only the six in-scope Studio-related files plus `tests/test_license_headers.py` are changed in the implementation commits; no unrelated functional files appear.

- [ ] **Step 3: Inspect the working tree to confirm clean state**

Run: `git status --short`

Expected: no uncommitted changes.

- [ ] **Step 4: Commit only if additional cleanup was needed**

If Step 2 or 3 required a small correction, commit it with:

```bash
git add <corrected-files>
git commit -m "chore(license): finalize Studio header remediation"
```

If no correction was needed, do not create an extra commit.

---

## Self-Review

- Spec coverage: the plan covers all six in-scope files, uses per-file-type header conventions, avoids non-Studio scope creep, and includes test verification afterward.
- Placeholder scan: all tasks contain exact files, header blocks, commands, and expected outcomes; no `TODO`/`TBD` placeholders remain.
- Type consistency: the plan consistently uses the AISBF Python header for `.py` files, HTML comment headers for templates, block comments for JS/CSS, and a dedicated `tests/test_license_headers.py` verification file across all tasks.
