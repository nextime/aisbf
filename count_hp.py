#!/usr/bin/env python3
# Let's count how many of our translations are actually from the HP key list
import json

def get_all_keys(d, prefix=''):
    keys = []
    for k, v in d.items():
        full_key = prefix + k if not prefix else prefix + '.' + k
        if isinstance(v, dict) and v:
            keys.extend(get_all_keys(v, full_key))
        else:
            keys.append(full_key)
    return set(keys)

# Load EN and all languages
with open('static/i18n/en.json', 'r', encoding='utf-8') as f:
    en = json.load(f)
en_keys = get_all_keys(en)

# Load HP keys from TODO
with open('TRANSLATIONS_TODO.md', 'r') as f:
    in_block = False
    hp_keys = []
    for line in f:
        if line.strip() == '```':
            in_block = not in_block
            continue
        if in_block:
            key = line.strip()
            if key and not key.startswith('#'):
                hp_keys.append(key)

print(f'Total HP keys from TODO: {len(hp_keys)}')

# Filter to only those that exist in en.json
hp_keys = [k for k in hp_keys if k in en_keys]
print(f'HP keys in en.json: {len(hp_keys)}')

# Get EN values for HP keys
en_hp = {}
for key in hp_keys:
    parts = key.split('.')
    d = en
    for p in parts:
        if isinstance(d, dict) and p in d:
            d = d[p]
        else:
            d = None
            break
    en_hp[key] = d

print(f'Keys where EN has None: {sum(1 for v in en_hp.values() if v is None)}')

# Now check each language for translated HP keys
langs = ['af', 'id', 'ja', 'ko', 'ru', 'zh']
for lang in langs:
    with open(f'static/i18n/{lang}.json', 'r', encoding='utf-8') as f:
        lang_data = json.load(f)
    
    translated = 0
    not_translated = 0
    for key, en_val in en_hp.items():
        if en_val is None:
            continue
        parts = key.split('.')
        d = lang_data
        for p in parts:
            if isinstance(d, dict) and p in d:
                d = d[p]
            else:
                d = None
                break
        if d is not None and d != en_val:
            translated += 1
        else:
            not_translated += 1
    
    print(f'{lang}: {translated} HP keys translated, {not_translated} HP keys not translated (still EN) = {translated+not_translated} total HP keys')