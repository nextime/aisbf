
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

print(f"Total HP keys: {len(hp_keys)}")

# Target languages: cs, el, fi, hi, hu, pl, th
lang_codes = {
    'cs': 'cs',
    'el': 'el', 
    'fi': 'fi',
    'hi': 'hi',
    'hu': 'hu',
    'pl': 'pl',
    'th': 'th',
}

# Filter to only the 7 target languages
langs_to_do = ['cs', 'el', 'fi', 'hi', 'hu', 'pl', 'th']

# Find keys that need translation for each lang
missing_per_lang = {}
for lang_code in langs_to_do:
    with open(f'static/i18n/{lang_code}.json', 'r', encoding='utf-8') as f:
        data = json.load(f)
    missing = []
    for key in hp_keys:
        val = get_value(data, key)
        en_val = get_value(en, key)
        if val is None or val == en_val:
            missing.append(key)
    missing_per_lang[lang_code] = missing
    print(f"{lang_code}: {len(missing)} keys need translation")

# Translate in batches
total_calls = sum(len(v) for v in missing_per_lang.values())
print(f"\nTotal translation calls needed: {total_calls}")
print("Starting batch translation...\n")

for lang_code in langs_to_do:
    lang_name = lang_code
    target_code = lang_codes[lang_code]
    missing = missing_per_lang[lang_code]
    
    if not missing:
        print(f"\n{lang_code} has no missing keys, skipping.")
        continue
    
    print(f"\n{'='*60}")
    print(f"Translating {len(missing)} keys to {lang_code} ({target_code})")
    print(f"{'='*60}")
    
    # Load current language file
    with open(f'static/i18n/{lang_code}.json', 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    # Batch translate
    batch_size = 50
    translated_count = 0
    errors = []
    
    for i in range(0, len(missing), batch_size):
        batch = missing[i:i+batch_size]
        
        # Build batch text
        texts = []
        for key in batch:
            texts.append(get_value(en, key))
        
        try:
            # Translate batch
            translator = GoogleTranslator(source='en', target=target_code)
            results = translator.translate(texts)
            
            # Handle single result vs list
            if not isinstance(results, list):
                results = [results]
            
            # Apply translations
            for j, key in enumerate(batch):
                if j < len(results):
                    set_value(data, key, results[j])
                    translated_count += 1
            
            print(f"  Batch {i//batch_size + 1}: translated {len(batch)} keys ({translated_count}/{len(missing)})")
            time.sleep(1)  # Rate limit
            
        except Exception as e:
            print(f"  ERROR in batch {i//batch_size + 1}: {e}")
            # Try individual translations
            for key in batch:
                try:
                    text = get_value(en, key)
                    translator = GoogleTranslator(source='en', target=target_code)
                    result = translator.translate(text)
                    set_value(data, key, result)
                    translated_count += 1
                    time.sleep(0.5)
                except Exception as e2:
                    print(f"    Individual fail for {key}: {e2}")
                    errors.append((key, str(e2)))
    
    # Save
    with open(f'static/i18n/{lang_code}.json', 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
    print(f"\n{lang_code}: Saved {translated_count} translations")
    if errors:
        print(f"  Errors: {len(errors)}")
        for k, e in errors[:5]:
            print(f"    {k}: {e}")

print("\n" + "="*60)
print("TRANSLATION COMPLETE")
print("="*60)

# Verify
print("\nVerification:")
for lang_code in langs_to_do:
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
    print(f"{lang_code}: {pct:.1f}% = {done}/{total}")

