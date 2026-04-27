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

# Read the keys from TRANSLATIONS_TODO
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

langs = ['af', 'id', 'ja', 'ko', 'ru', 'zh']

all_missing = {}

for lang in langs:
    with open(D + lang + '.json', 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    missing = []
    for key in hp_keys:
        val = get_key(data, key)
        en_val = get_key(en, key)
        if val is None or val == en_val:
            missing.append(key)
    
    all_missing[lang] = missing
    print(f'{lang}: {len(missing)} missing keys')

# Now let's write these to a file for reference
with open('missing_keys_output.txt', 'w', encoding='utf-8') as f:
    for lang, keys in all_missing.items():
        f.write(f'\n=== {lang} ({len(keys)} keys) ===\n')
        for key in keys:
            en_val = get_key(en, key)
            f.write(f'{key} = {en_val}\n')
