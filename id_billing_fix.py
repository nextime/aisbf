#!/usr/bin/env python3
import json

# Indonesian billing fix
id_trans = {
    "billing_page.col_status": "Status",  # This is correct - "Status" in Indonesian is "Status"
}

# But let me check what other languages use for reference
print('Checking other languages for billing_page.col_status:')
for lang in ['ja', 'ko', 'ru', 'zh', 'af']:
    with open(f'static/i18n/{lang}.json', 'r', encoding='utf-8') as f:
        data = json.load(f)
    val = data.get('billing_page', {}).get('col_status', 'NOT FOUND')
    print(f'  {lang}: {val}')
"
