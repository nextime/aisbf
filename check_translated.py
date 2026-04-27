import json

# Load English and Quenya translations
with open('/working/aisbf/static/i18n/en.json', 'r', encoding='utf-8') as f:
    en = json.load(f)

with open('/working/aisbf/static/i18n/qya.json', 'r', encoding='utf-8') as f:
    qya = json.load(f)

def get_all_keys(d, prefix=''):
    keys = {}
    for k, v in d.items():
        full_key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            keys.update(get_all_keys(v, full_key))
        else:
            keys[full_key] = v
    return keys

en_flat = get_all_keys(en)
qya_flat = get_all_keys(qya)

# Count translated (value differs from English) vs untranslated
translated = {}
untranslated = {}
for key, en_val in en_flat.items():
    qya_val = qya_flat.get(key)
    if qya_val is not None and qya_val != en_val:
        translated[key] = qya_val
    else:
        untranslated[key] = en_val

print(f"Total EN keys: {len(en_flat)}")
print(f"Translated (≠ EN): {len(translated)}")
print(f"Untranslated (= EN or missing): {len(untranslated)}")

print("\nCurrently translated Quenya keys:")
for k, v in sorted(translated.items())[:30]:
    print(f"  {k}: {v}")
