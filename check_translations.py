#!/usr/bin/env python3
import json
import sys

D = '/working/aisbf/static/i18n/'

with open(D + 'en.json', 'r', encoding='utf-8') as f:
    en = json.load(f)

def get_nested(d, key):
    """Get value from nested dict using dot notation"""
    parts = key.split('.')
    c = d
    for p in parts:
        if isinstance(c, dict) and p in c:
            c = c[p]
        else:
            return None
    return c

def key_exists(d, key):
    """Check if key exists in nested dict"""
    parts = key.split('.')
    c = d
    for p in parts:
        if isinstance(c, dict) and p in c:
            c = c[p]
        else:
            return False
    return True

# List of all keys to check from TRANSLATIONS_TODO.md
keys_to_check = []
with open('/working/aisbf/TRANSLATIONS_TODO.md', 'r', encoding='utf-8') as f:
    in_list = False
    for line in f:
        if line.strip() == '```':
            if in_list:
                break
            else:
                in_list = True
                continue
        if in_list and line.strip():
            key = line.strip()
            if key and not key.startswith('#'):
                keys_to_check.append(key)

print(f"Total keys to check: {len(keys_to_check)}")

# Check each language
langs = ['af', 'id', 'ja', 'ko', 'ru', 'zh']

for lang in langs:
    with open(D + lang + '.json', 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    missing = []
    same_as_en = []
    
    for key in keys_to_check:
        if not key_exists(data, key):
            missing.append(key)
        else:
            val = get_nested(data, key)
            en_val = get_nested(en, key)
            if val == en_val:
                same_as_en.append(key)
    
    total_needed = len(missing) + len(same_as_en)
    print(f"\n{lang}:")
    print(f"  Missing keys: {len(missing)}")
    print(f"  Same as English (untranslated): {len(same_as_en)}")
    print(f"  Total needed: {total_needed}")
    
    if total_needed != 267:
        # Count how many keys from en.json are in our list vs not
        all_keys_from_en = set()
        def extract_keys(d, prefix=""):
            for k, v in d.items():
                full_key = f"{prefix}{k}" if prefix else k
                if isinstance(v, dict) and v:
                    extract_keys(v, full_key + ".")
                else:
                    all_keys_from_en.add(full_key)
        extract_keys(en)
        
        # Count keys in keys_to_check that are in all_keys_from_en
        keys_in_en = sum(1 for k in keys_to_check if k in all_keys_from_en)
        print(f"  Keys in list that exist in en.json: {keys_in_en}")
        print(f"  Keys in en.json total: {len(all_keys_from_en)}")