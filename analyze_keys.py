#!/usr/bin/env python3
import json

# Load English
with open('static/i18n/en.json', 'r', encoding='utf-8') as f:
    en = json.load(f)

def get_all_keys(d, prefix=''):
    keys = []
    for k, v in d.items():
        full_key = prefix + k if not prefix else prefix + '.' + k
        if isinstance(v, dict) and v:
            keys.extend(get_all_keys(v, full_key))
        else:
            keys.append(full_key)
    return keys

en_keys = set(get_all_keys(en))
print(f'English total keys: {len(en_keys)}')

# Check which keys from TRANSLATIONS_TODO are actually in en.json
with open('TRANSLATIONS_TODO.md', 'r') as f:
    in_block = False
    todo_keys = []
    for line in f:
        if line.strip() == '```':
            in_block = not in_block
            continue
        if in_block:
            key = line.strip()
            if key and not key.startswith('#'):
                todo_keys.append(key)

print(f'TODO keys count: {len(todo_keys)}')

# Check which are actually in en.json
todo_in_en = [k for k in todo_keys if k in en_keys]
print(f'TODO keys in en.json: {len(todo_in_en)}')

# Keys in en.json but NOT in TODO list
not_in_todo = en_keys - set(todo_keys)
print(f'Keys in en.json not in TODO: {len(not_in_todo)}')

# Show some examples
print(f'First 10 not in TODO: {list(not_in_todo)[:10]}')
