#!/usr/bin/env python3
import json

# Indonesian fixes for remaining keys
id_trans = {
    "tokens_page.col_endpoint": "Endpoint",
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
