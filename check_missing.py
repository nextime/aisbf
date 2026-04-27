import json

# Load English and Quenya translations
with open('/working/aisbf/static/i18n/en.json', 'r', encoding='utf-8') as f:
    en = json.load(f)

with open('/working/aisbf/static/i18n/qya.json', 'r', encoding='utf-8') as f:
    qya = json.load(f)

def get_all_keys(d, prefix=''):
    """Recursively flatten nested dict into dot-separated keys"""
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

# Find missing/untouched keys (where qya equals en or key doesn't exist)
missing = {}
for key, en_val in en_flat.items():
    qya_val = qya_flat.get(key)
    if qya_val is None or qya_val == en_val:
        missing[key] = en_val

print(f"Total EN keys: {len(en_flat)}")
print(f"Total QYA keys: {len(qya_flat)}")
print(f"Missing/untouched keys: {len(missing)}")

# Show some examples
print("\nFirst 20 missing keys:")
for i, (k, v) in enumerate(list(missing.items())[:20]):
    print(f"  {k}: {v}")
