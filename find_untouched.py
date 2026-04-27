#!/usr/bin/env python3
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

with open('static/i18n/en.json', 'r', encoding='utf-8') as f:
    en = json.load(f)
en_keys = get_all_keys(en)

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

hp_keys = [k for k in hp_keys if k in en_keys]

langs = ['af', 'id', 'ja', 'ko', 'ru', 'zh']
for lang in langs:
    with open(f'static/i18n/{lang}.json', 'r', encoding='utf-8') as f:
        lang_data = json.load(f)
    
    not_translated = []
    for key in hp_keys:
        parts = key.split('.')
        d = lang_data
        for p in parts:
            if isinstance(d, dict) and p in d:
                d = d[p]
            else:
                d = None
                break
        en_val = en
        for p in parts:
            if isinstance(en_val, dict) and p in en_val:
                en_val = en_val[p]
            else:
                en_val = None
                break
        if d is None or d == en_val:
            not_translated.append(key)
    
    print(f'{lang}: {len(not_translated)} untranslated HP keys')
    for k in not_translated:
        print(f'  {k}')
