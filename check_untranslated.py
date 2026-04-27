#!/usr/bin/env python3
import json

D = '/working/aisbf/static/i18n/'

with open(D + 'en.json') as f:
    en = json.load(f)
with open(D + 'ar.json') as f:
    ar = json.load(f)

# Parse TRANSLATIONS_TODO.md to get keys list from the first code block after "### Key list"
with open('/working/aisbf/TRANSLATIONS_TODO.md') as f:
    content = f.read()

# Find the section
start_marker = "### Key list (same for all 27 languages)"
start = content.find(start_marker)
if start == -1:
    raise ValueError("Section not found")
# Find first ``` after that
code_start = content.find("```", start)
if code_start == -1:
    raise ValueError("Code block start not found")
code_start += 3  # after ```
# Find closing ```
code_end = content.find("```", code_start)
if code_end == -1:
    raise ValueError("Code block end not found")

keys_block = content[code_start:code_end]
keys = [line.strip() for line in keys_block.splitlines() if line.strip()]

print(f"Total keys in TODO list: {len(keys)}")

def get_nested(d, key):
    parts = key.split('.')
    c = d
    for p in parts:
        if p not in c:
            return None
        c = c[p]
    return c

untranslated = []
for key in keys:
    en_val = get_nested(en, key)
    ar_val = get_nested(ar, key)
    if ar_val is None or ar_val == en_val:
        untranslated.append((key, en_val))

print(f"\nUntranslated keys: {len(untranslated)}")
print("\nKey -> English value:")
for key, val in untranslated:
    print(f"{key} -> {val}")
