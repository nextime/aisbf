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

print(f'HP keys from TODO: {len(hp_keys)}')

# Check each language against these specific HP keys
langs = ['af', 'id', 'ja', 'ko', 'ru', 'zh']

for lang in langs:
    with open(D + lang + '.json', 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    missing_or_english = []
    for key in hp_keys:
        val = get_key(data, key)
        en_val = get_key(en, key)
        if val is None or val == en_val:
            missing_or_english.append(key)
    
    print(f'{lang}: {len(missing_or_english)} HP keys missing/untranslated (target: 267)')
    if len(missing_or_english) <= 10:
        for k in missing_or_english[:10]:
            print(f'  {k}')
