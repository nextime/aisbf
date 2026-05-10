# Studio License Header Remediation Design

**Date:** 2026-05-10  
**Status:** Approved  
**Approach:** Targeted Studio-Only Header Normalization

## Problem Statement

The recent Studio integration added several new Studio-related source and test files that do not yet include the GPL/Copyleft license header pattern already used across the AISBF repository. This creates inconsistency in licensing notices and leaves the new Studio code less clearly aligned with the project’s established legal and documentation conventions.

The user explicitly wants this remediation scoped only to the newly added Studio-related files, not a repository-wide cleanup.

## Requirements

1. Add license headers only to the newly added Studio-related files that are currently missing them
2. Follow the existing AISBF header conventions already present in the repository
3. Use file-type-appropriate comment syntax for each target file
4. Avoid changing logic, behavior, formatting, or unrelated content
5. Re-run Studio-related tests after the header insertions to confirm no accidental breakage

## In-Scope Files

The remediation applies only to these files:

- `aisbf/studio.py`
- `static/dashboard/studio.js`
- `static/dashboard/studio.css`
- `templates/dashboard/studio.html`
- `tests/test_studio.py`
- `tests/routes/test_dashboard_studio.py`

## Out of Scope

The following are explicitly out of scope for this change:

- Any non-Studio files that may also be missing headers
- Any repository-wide header audit or normalization pass
- Any functional or behavioral code changes
- Any refactoring, formatting cleanup, or test rewrites unrelated to header insertion
- Any changes to the existing license text itself

## Design Overview

### Header Strategy

This remediation should use the nearest existing AISBF header style for each file type instead of inventing a new variant.

- **Python files** should match the Copyleft/GPL header style already used in files like `aisbf/config.py` and `aisbf/handlers.py`
- **HTML files** should match the HTML comment GPL header style already used in files like `templates/base.html`
- **JavaScript files** should use a top-of-file block comment with the same GPL wording already present in embedded JavaScript inside `templates/base.html`
- **CSS files** should use a top-of-file block comment with the same GPL wording adapted to CSS comment syntax
- **Test files** should receive the same Python-style header used for normal `.py` source files because they are committed project code

### Placement Rules

Headers should be inserted at the very top of each file:

- Before imports in Python files
- Before any selectors or declarations in CSS files
- Before any executable statements in JavaScript files
- Before template markup in HTML files

This keeps the header visible, conventional, and aligned with the repository’s existing style.

### Consistency Rules

The inserted header text should preserve the established AISBF conventions:

- Same copyright/copy-left owner attribution
- Same year currently used by the surrounding Studio integration changes
- Same GPL wording already used elsewhere in the repository
- Same link to `<https://www.gnu.org/licenses/>`

The implementation should not mix multiple wording variants inside the new Studio files unless the repository already uses those file-type-specific variants.

## Implementation Notes

### Python Targets

For these files:

- `aisbf/studio.py`
- `tests/test_studio.py`
- `tests/routes/test_dashboard_studio.py`

Insert the same Python top-of-file license block used in current AISBF Python modules. The header must appear before any imports.

### Frontend Targets

For these files:

- `templates/dashboard/studio.html`
- `static/dashboard/studio.js`
- `static/dashboard/studio.css`

Insert file-type-native GPL comment headers matching existing dashboard/frontend conventions. These should be placed before the first template tag, script code, or CSS rule.

## Risks and Mitigations

### Risk: accidental functional edits

Because these files are active source/test files, broad editing or formatting could create noisy or risky diffs.

**Mitigation:** only insert the header block at the top of each file and avoid touching any other lines unless strictly required for syntax correctness.

### Risk: incorrect comment syntax

Using the wrong header syntax could break parsing or rendering in frontend files.

**Mitigation:** use `<!-- ... -->` for HTML and `/* ... */` for JS/CSS.

### Risk: import/order breakage in Python tests

Top-of-file changes can sometimes affect module docstring/import layout if done carelessly.

**Mitigation:** keep the inserted Python header in the same form already used by existing Python modules and verify tests afterward.

## Validation Plan

After implementation:

1. Confirm that each in-scope file now contains a license header
2. Re-run the Studio-focused test slice to verify nothing broke due to top-of-file edits
3. Inspect the diff to ensure no unrelated code changes slipped in

Recommended verification command:

```bash
PYTHONPATH=/working/aisbf pytest tests/test_studio.py tests/routes/test_dashboard_studio.py -v
```

## Success Criteria

This remediation is successful if all of the following are true:

- All six in-scope Studio-related files have license headers
- The header text matches AISBF conventions already used elsewhere
- No non-Studio files are changed as part of this task
- No functional behavior changes are introduced
- Studio-related tests still pass after the edits
