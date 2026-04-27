import json

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

# HP domains (user-facing UI)
HP_DOMAINS = {
    'header', 'nav', 'account_menu', 'notifications', 'footer',
    'donate', 'welcome', 'contact', 'modal', 'common',
    'providers', 'rotations', 'autoselect', 'users', 'wallet',
    'analytics', 'rate_limits', 'billing', 'payments', 'overview',
    'users_page', 'wallet_page', 'analytics_page', 'rate_limits_page',
    'login_page', 'signup_page', 'forgot_page', 'reset_page',
    'profile_page', 'password_page', 'email_page', 'delete_page',
    'tokens_page', 'billing_page', 'user_overview', 'usage_page',
    'prompts_page', 'config_page', 'error_page', 'tiers_page',
    'cache_page', 'response_cache_page', 'settings_page',
    'payments_page', 'subscription_page',
    'user_providers_page', 'user_rotations_page', 'user_autoselects_page',
    # Also include important keys from these domains regardless of exact path
}

# Also HP if key contains these patterns
HP_PATTERNS = [
    'title', 'label', 'button', 'submit', 'cancel', 'delete', 'save',
    'error', 'success', 'warning', 'notice', 'confirm',
    'loading', 'no_', 'not_found', 'missing', 'invalid', 'failed',
    'copy', 'remove', 'add', 'edit', 'search', 'filter', 'refresh',
    'status', 'active', 'inactive', 'enabled', 'disabled',
    'yes', 'no', 'ok', 'back', 'next', 'prev',
    'minutes_ago', 'hours_ago', 'days_ago',
    'copied', 'saved', 'saving',
    '_desc', '_hint', '_placeholder',
    'email', 'password', 'username',
    'wallet', 'balance', 'topup', 'deposit',
    'provider', 'model', 'rotation', 'autoselect',
    'tier', 'subscription', 'billing',
    'notification', 'token', 'api',
    'transaction', 'credit', 'debit',
    # Time-related placeholders with {n}
    'seconds', 'minutes_ago', 'hours_ago', 'days_ago', 'resets_in',
    'result_count', 'models_found',
    # Common UI actions
    'send_', 'create_', 'revoke', 'reset',
]

def is_hp_key(key, en_val):
    # Check if key domain is in HP_DOMAINS
    domain = key.split('.')[0]
    if domain in HP_DOMAINS:
        return True
    # Check if any HP pattern is in key
    for pattern in HP_PATTERNS:
        if pattern in key.lower():
            return True
    # Short values that are common UI words are HP
    common_hp_words = [
        'title', 'subtitle', 'message', 'help', 'docs', 'about',
        'logout', 'restart', 'edit', 'view', 'manage',
    ]
    for w in common_hp_words:
        if w in key.lower():
            return True
    return False

hp_translated = []
hp_untranslated = []
lp_translated = []
lp_untranslated = []

for key, en_val in en_flat.items():
    is_hp = is_hp_key(key, en_val)
    qya_val = qya_flat.get(key)
    is_translated = qya_val is not None and qya_val != en_val

    if is_hp:
        if is_translated:
            hp_translated.append(key)
        else:
            hp_untranslated.append(key)
    else:
        if is_translated:
            lp_translated.append(key)
        else:
            lp_untranslated.append(key)

print(f"HP keys total: {len(hp_translated) + len(hp_untranslated)}")
print(f"  HP translated: {len(hp_translated)}")
print(f"  HP untranslated: {len(hp_untranslated)}")
print(f"LP keys total: {len(lp_translated) + len(lp_untranslated)}")
print(f"  LP translated: {len(lp_translated)}")
print(f"  LP untranslated: {len(lp_untranslated)}")

print("\nSample HP untranslated keys (first 40):")
for k in hp_untranslated[:40]:
    print(f"  {k}: {en_flat[k]}")
