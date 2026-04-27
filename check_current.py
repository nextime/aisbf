import json, os

def get_value(d, key):
    cur = d
    for p in key.split('.'):
        if p not in cur:
            return None
        cur = cur[p]
    return cur

with open('TRANSLATIONS_TODO.md') as f:
    content = f.read()

todo_keys = []
for line in content.split('\n')[90:470]:
    line = line.strip()
    if line and not line.startswith('#') and not line.startswith('```') and not line.startswith('|') and '.' in line:
        if line.startswith('`') and line.endswith('`'):
            todo_keys.append(line.strip('`'))
        else:
            todo_keys.append(line)

lp_patterns = ['_hint', '_desc']
extra_lp = [
    'signup_page.username_hint', 'signup_page.email_hint', 'signup_page.password_hint',
    'forgot_page.intro', 'forgot_page.sent', 'reset_page.intro', 'reset_page.password_hint',
    'reset_page.success', 'reset_page.go_to_login', 'reset_page.invalid_token', 'reset_page.request_new',
    'email_page.password_hint', 'profile_page.display_name_hint', 'profile_page.no_email',
    'profile_page.add_email', 'profile_page.change_email', 'profile_page.email_requires_verify',
    'profile_page.upload_image', 'profile_page.upload_hint', 'profile_page.danger_zone',
    'profile_page.danger_zone_desc', 'profile_page.delete_account', 'profile_page.uploading',
    'profile_page.upload_pct', 'profile_page.upload_success', 'profile_page.upload_too_large',
    'profile_page.upload_invalid_type', 'profile_page.upload_failed',
    'usage_page.manage_subscription', 'usage_page.current_plan', 'usage_page.activity_quotas',
    'usage_page.activity_quotas_desc', 'usage_page.config_limits', 'usage_page.config_limits_desc',
    'usage_page.requests_today', 'usage_page.resets_midnight', 'usage_page.resets_in',
    'usage_page.requests_month', 'usage_page.resets_on_1st', 'usage_page.resets_in_days',
    'usage_page.resets_in_days_plural', 'usage_page.tokens_24h', 'usage_page.tokens_combined',
    'usage_page.tokens_used', 'usage_page.unlimited', 'usage_page.quota_reached',
    'usage_page.remaining', 'usage_page.ai_providers', 'usage_page.ai_providers_desc',
    'usage_page.rotations', 'usage_page.rotations_desc', 'usage_page.autoselections',
    'usage_page.autoselections_desc', 'usage_page.unlimited_slots',
    'usage_page.pct_used_slots_free', 'usage_page.pct_used_slots_free_plural',
    'usage_page.need_higher_limits', 'usage_page.upgrade_desc', 'usage_page.view_plans',
    'prompts_page.select_file', 'prompts_page.content_hint', 'prompts_page.reset_confirm',
    'prompts_page.reset_confirm_title', 'user_overview.admin_access', 'user_overview.admin_access_desc',
    'user_overview.token_required', 'user_overview.manage_tokens'
]

hp_keys = [k for k in todo_keys if not (any(p in k for p in lp_patterns) or k in extra_lp)]
en_data = json.load(open('static/i18n/en.json'))

langs = sorted(['ar','bn','cs','da','el','fa','fi','he','hi','hu','id','ms','nb','pl','sk','th','tr','uk','vi','xh','zu','eo','ro','qya','tlh','vul','af','de','fr','es','pt','it','ru','ja','zh','ko','nl','sv'])

print('CURRENT TRANSLATION STATUS')
print('='*60)
print(f'HP keys total: {len(hp_keys)}')
print()
print(f'{"Lang":<6} {"Done":>4} {"Missing":>7} {"%"}')
print('-'*60)
for code in langs:
    with open(f'static/i18n/{code}.json') as f:
        data = json.load(f)
    done = sum(1 for k in hp_keys if get_value(data, k) is not None and get_value(data, k) != get_value(en_data, k))
    missing = len(hp_keys) - done
    pct = done / len(hp_keys) * 100
    print(f'{code:<6} {done:>4} {missing:>7} {pct:>5.1f}%')
