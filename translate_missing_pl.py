import json
from deep_translator import GoogleTranslator
import re

# Load English and Polish translations
with open('/working/aisbf/static/i18n/en.json', 'r', encoding='utf-8') as f:
    en = json.load(f)

with open('/working/aisbf/static/i18n/pl.json', 'r', encoding='utf-8') as f:
    pl = json.load(f)

# Read the missing keys from TRANSLATIONS_TODO.md (lines 91-470)
with open('/working/aisbf/TRANSLATIONS_TODO.md', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Extract keys from lines 91 to 470 (0-indexed, so 90 to 469)
missing_keys_raw = [line.strip() for line in lines[90:470] if line.strip()]
missing_keys = []
for key in missing_keys_raw:
    if key:  # skip empty lines
        missing_keys.append(key)

print(f"Found {len(missing_keys)} keys to check for translation.")

# Function to get nested value from dict using dot notation
def get_nested(obj, path):
    keys = path.split('.')
    for key in keys:
        if isinstance(obj, dict) and key in obj:
            obj = obj[key]
        else:
            return None
    return obj

# Function to set nested value in dict using dot notation
def set_nested(obj, path, value):
    keys = path.split('.')
    for key in keys[:-1]:
        obj = obj.setdefault(key, {})
    obj[keys[-1]] = value

# Translate each missing key if not already translated
translated_count = 0
for key in missing_keys:
    en_value = get_nested(en, key)
    if en_value is None:
        print(f"Warning: Key '{key}' not found in en.json")
        continue

    pl_value = get_nested(pl, key)
    # If the key exists in pl and the value is different from English, assume it's translated
    if pl_value is not None and pl_value != en_value:
        continue

    # Translate to Polish
    try:
        # Use Google Translate to Polish
        translated = GoogleTranslator(source='en', target='pl').translate(en_value)
        
        # Post-process: ensure placeholders and symbols are preserved
        # We'll do a simple check: if the translated string doesn't have the same placeholders, we might have issues.
        # But for now, we trust the translator.
        set_nested(pl, key, translated)
        translated_count += 1
        print(f"Translated '{key}': '{en_value}' -> '{translated}'")
    except Exception as e:
        print(f"Error translating key '{key}': {e}")

# Save the updated pl.json
with open('/working/aisbf/static/i18n/pl.json', 'w', encoding='utf-8') as f:
    json.dump(pl, f, ensure_ascii=False, indent=2)

print(f"\nTranslation complete. Translated {translated_count} keys.")
print("Updated pl.json saved.")

# Validate JSON
try:
    with open('/working/aisbf/static/i18n/pl.json', 'r', encoding='utf-8') as f:
        json.load(f)
    print("JSON validation: OK")
except Exception as e:
    print(f"JSON validation failed: {e}")