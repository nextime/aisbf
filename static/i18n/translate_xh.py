# Translation script for Xhosa
import json
import re

# Read files
with open('/working/aisbf/static/i18n/en.json', 'r', encoding='utf-8') as f:
    en_data = json.load(f)

with open('/working/aisbf/static/i18n/xh.json', 'r', encoding='utf-8') as f:
    xh_data = json.load(f)

# Read the key list from TRANSLATIONS_TODO.md
with open('/working/aisbf/TRANSLATIONS_TODO.md', 'r', encoding='utf-8') as f:
    content = f.read()

# Extract keys from lines 91-470 (the code block with the key list)
lines = content.split('\n')
in_block = False
key_lines = []
for line in lines[90:470]:
    if line.strip() == '```':
        in_block = not in_block
        continue
    if in_block and line.strip():
        key_lines.append(line.strip())

keys_to_translate = key_lines

def get_nested_value(data, key):
    parts = key.split('.')
    current = data
    try:
        for part in parts:
            current = current[part]
        return current
    except (KeyError, TypeError):
        return None

keys_needing_translation = []
for key in keys_to_translate:
    en_val = get_nested_value(en_data, key)
    xh_val = get_nested_value(xh_data, key)
    if en_val is None:
        print(f"WARNING: Key not found in en.json: {key}")
        continue
    if xh_val is None:
        keys_needing_translation.append((key, en_val))
    elif xh_val == en_val:
        keys_needing_translation.append((key, en_val))

print(f"Total keys to translate: {len(keys_to_translate)}")
print(f"Keys needing translation: {len(keys_needing_translation)}")
print()
for key, val in sorted(keys_needing_translation):
    print(f"{key}: {val}")
