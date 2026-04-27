
import json
from deep_translator import GoogleTranslator
import time
import sys

def get_value(d, key):
    cur = d
    for p in key.split('.'):
        if p not in cur:
            return None
        cur = cur[p]
    return cur

def set_value(d, key, value):
    parts = key.split('.')
    c = d
    for p in parts[:-1]:
        if p not in c:
            c[p] = {}
        c = c[p]
    c[parts[-1]] = value

# Load English
with open('static/i18n/en.json', 'r', encoding='utf-8') as f:
    en = json.load(f)

# Read HP keys from TRANSLATIONS_TODO
hp_keys = []
with open('TRANSLATIONS_TODO.md', 'r', encoding='utf-8') as f:
    in_block = False
    for line in f:
        if line.strip() == '```':
            in_block = not in_block
            continue
        if in_block and line.strip() and not line.startswith('#'):
            hp_keys.append(line.strip())

lang_codes = {
    'cs': 'cs', 'el': 'el', 'fi': 'fi',
    'hi': 'hi', 'hu': 'hu', 'pl': 'pl', 'th': 'th',
}

# Process one language at a time
langs_to_do = ['cs', 'el', 'fi', 'hi', 'hu', 'pl', 'th']

for lang_code in langs_to_do:
    target_code = lang_codes[lang_code]
    
    with open(f'static/i18n/{lang_code}.json', 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    # Find missing keys
    missing = []
    for key in hp_keys:
        val = get_value(data, key)
        en_val = get_value(en, key)
        if val is None or val == en_val:
            missing.append(key)
    
    print(f"{lang_code}: {len(missing)} keys to translate")
    
    if not missing:
        continue
    
    translated = 0
    errors = []
    
    for i, key in enumerate(missing):
        text = get_value(en, key)
        try:
            translator = GoogleTranslator(source='en', target=target_code)
            result = translator.translate(text)
            set_value(data, key, result)
            translated += 1
        except Exception as e:
            errors.append((key, str(e)))
        
        if (i + 1) % 20 == 0:
            print(f"  {lang_code}: {translated}/{len(missing)} done")
            time.sleep(2)
    
    # Save
    with open(f'static/i18n/{lang_code}.json', 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
    print(f"  {lang_code}: SAVED - {translated}/{len(missing)} translated, {len(errors)} errors")
    if errors:
        for k, e in errors[:3]:
            print(f"    ERR: {k} - {e}")

print("\nDONE")
