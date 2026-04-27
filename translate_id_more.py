#!/usr/bin/env python3
# Additional Indonesian translations for remaining keys
id_trans = {
    # Providers
    "providers.provider_key_hint": "Ini akan digunakan sebagai ID penyedia dalam konfigurasi dan titik akhir API.",
    
    # Rate Limits
    "rate_limits_page.reset_confirm_title": "Atur Ulang Rate Limiter",
    
    # Tokens
    "tokens_page.col_endpoint": "Endpoint",
    
    # Billing
    "billing_page.col_status": "Status",
    
    # Prompts
    "prompts_page.reset_confirm_title": "Atur Ulang Prompt",
}

print(f'Additional Indonesian translations: {len(id_trans)} keys')

# Apply translations
import json

def apply(lang, translations):
    D = '/working/aisbf/static/i18n/'
    path = D + lang + '.json'
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    def set_nested(d, key, value):
        parts = key.split('.')
        c = d
        for p in parts[:-1]:
            c = c.setdefault(p, {})
        c[parts[-1]] = value
    for key, value in translations.items():
        set_nested(data, key, value)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f'Applied {len(translations)} translations for {lang}')

apply('id', id_trans)