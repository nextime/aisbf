#!/usr/bin/env python3
import json

D = 'static/i18n/'
with open(D + 'en.json', 'r', encoding='utf-8') as f:
    en = json.load(f)

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

print(f'HP keys from TODO: {len(hp_keys)}')

# Get English values for all HP keys
en_values = {}
for key in hp_keys:
    val = get_key(en, key)
    if val is not None:
        en_values[key] = val
    else:
        print(f"Warning: Key not found in English: {key}")

# Save to file for reference
import json
with open('hp_keys_en.json', 'w', encoding='utf-8') as f:
    json.dump(en_values, f, indent=2, ensure_ascii=False)

print(f"Saved {len(en_values)} HP key values to hp_keys_en.json")
