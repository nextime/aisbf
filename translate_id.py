#!/usr/bin/env python3
# Indonesian translations for missing keys
id_trans = {
    # Providers
    "providers.kiro_refresh_token": "Token Pembaruan",
    "providers.kiro_profile_arn": "Profil ARN",
    "providers.nsfw": "NSFW",
    "providers.native_caching_section": "Caching Asli",
    "providers.prompt_cache_key": "Kunci Cache Prompt (OpenAI/Kilo)",
    "providers.auth_generic_error": "❌ Kesalahan: {error}",
    "providers.models_fetch_error": "❌ Kesalahan: {error}",
    "providers.provider_key_hint": "This will be used as the provider ID in the configuration and API endpoints",
    "rate_limits_page.response_cache": "Cache Respons",
    "rate_limits_page.reset_confirm_title": "Reset Rate Limiter",
    
    # Tokens
    "tokens_page.col_endpoint": "Endpoint",
    
    # Billing
    "billing_page.default_label": "Bawaan",
    "billing_page.col_status": "Status",
    
    # User Overview
    "user_overview.ep_chat": "Obrolan Lengkap",
    
    # Prompts
    "prompts_page.reset_confirm_title": "Reset Prompt",
}

print(f'Indonesian translations: {len(id_trans)} keys')

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