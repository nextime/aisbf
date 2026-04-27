#!/usr/bin/env python3
import json

D = 'static/i18n/'
with open(D + 'en.json', 'r', encoding='utf-8') as f:
    en = json.load(f)
with open(D + 'ar.json', 'r', encoding='utf-8') as f:
    ar = json.load(f)

def get_key(d, key):
    parts = key.split('.')
    c = d
    for p in parts:
        if isinstance(c, dict) and p in c:
            c = c[p]
        else:
            return None
    return c

# Read the keys from TRANSLATIONS_TODO.md
hp_keys = []
with open('TRANSLATIONS_TODO.md', 'r', encoding='utf-8') as f:
    in_block = False
    for line in f:
        if line.strip() == '```':
            in_block = not in_block
            continue
        if in_block:
            key = line.strip()
            if key and not key.startswith('#'):
                hp_keys.append(key)

missing = []
for key in hp_keys:
    en_val = get_key(en, key)
    ar_val = get_key(ar, key)
    if ar_val is None or ar_val == en_val:
        missing.append((key, en_val))

print(f"Arabic missing {len(missing)} HP keys:")
for key, en_val in missing[:20]:  # Show first 20
    print(f"  {key}: {en_val}")
if len(missing) > 20:
    print(f"  ... and {len(missing) - 20} more")
