
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
        c = c.setdefault(p, {})
    c[parts[-1]] = value

with open('static/i18n/en.json', 'r', encoding='utf-8') as f:
    en = json.load(f)

hp_keys = []
with open('TRANSLATIONS_TODO.md', 'r', encoding='utf-8') as f:
    in_block = False
    for line in f:
        if line.strip() == '```':
            in_block = not in_block
            continue
        if in_block and line.strip() and not line.startswith('#'):
            k = line.strip()
            if not ('---' in k or k.startswith('- ') and not k.startswith('`')):
                hp_keys.append(k)

langs_to_do = ['fi', 'hi', 'hu', 'pl', 'th']
lang_codes = {'fi': 'fi', 'hi': 'hi', 'hu': 'hu', 'pl': 'pl', 'th': 'th'}

for lang_code in langs_to_do:
    target = lang_codes[lang_code]
    
    with open(f'static/i18n/{lang_code}.json', 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    missing = []
    for key in hp_keys:
        val = get_value(data, key)
        en_val = get_value(en, key)
        if val is None or val == en_val:
            missing.append(key)
    
    print(f"\n{lang_code}: {len(missing)} missing")
    
    if not missing:
        continue
    
    # Try translating
    translator = GoogleTranslator(source='en', target=target)
    ok = 0
    err = 0
    
    for i, key in enumerate(missing):
        text = get_value(en, key)
        try:
            result = translator.translate(text)
            set_value(data, key, result)
            ok += 1
        except Exception as e:
            err += 1
        
        if (i + 1) % 10 == 0:
            print(f"  {ok}/{len(missing)} done")
            time.sleep(1.5)
    
    with open(f'static/i18n/{lang_code}.json', 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
    print(f"  Done: {ok} ok, {err} errors")

print("\nAll done!")

# Verify
for lang_code in langs_to_do + ['cs', 'el']:
    with open(f'static/i18n/{lang_code}.json', 'r', encoding='utf-8') as f:
        data = json.load(f)
    missing = []
    for key in hp_keys:
        val = get_value(data, key)
        en_val = get_value(en, key)
        if val is None or val == en_val:
            missing.append(key)
    total = len(hp_keys)
    done = total - len(missing)
    pct = done / total * 100
    print(f"{lang_code}: {pct:.1f}% ({done}/{total})")

