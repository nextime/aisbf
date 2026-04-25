import json, glob

I18N_DIR = '/working/aisbf/static/i18n/'

with open(I18N_DIR + 'en.json') as f:
    en = json.load(f)

# New namespaces to translate
NEW_NS = [
    'users_page','wallet_page','analytics_page','rate_limits_page','login_page',
    'signup_page','forgot_page','reset_page','profile_page','password_page',
    'email_page','delete_page','tokens_page','billing_page','user_overview',
    'usage_page','prompts_page','config_page','error_page','tiers_page',
    'cache_page','response_cache_page','settings_page'
]

