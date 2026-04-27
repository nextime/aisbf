#!/usr/bin/env python3
import json

# Indonesian fixes for remaining keys - use proper Indonesian
id_trans = {
    "tokens_page.col_endpoint": "Titik Akhir",
    "billing_page.col_status": "Status",
}

print(f'Indonesian final fixes: {len(id_trans)} keys')

# Apply
D = '/working/aisbf/static/i18n/'
path = D + 'id.json'
with open(path, 'r', encoding='utf-8') as f:
    data = json.load(f)

def set_nested(d, key, value):
    parts = key.split('.')
    c = d
    for p in parts[:-1]:
        c = c.setdefault(p, {})
    c[parts[-1]] = value

for key, value in id_trans.items():
    set_nested(data, key, value)

with open(path, 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print('Applied fixes for id')

# Verify
with open(path, 'r', encoding='utf-8') as f:
    data = json.load(f)
print('tokens_page.col_endpoint:', data.get('tokens_page', {}).get('col_endpoint', 'NOT FOUND'))
print('billing_page.col_status:', data.get('billing_page', {}).get('col_status', 'NOT FOUND'))
