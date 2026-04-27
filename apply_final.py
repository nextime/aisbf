import json

D = 'static/i18n/'

def apply(lang, translations):
    path = D + lang + '.json'
    with open(path) as f:
        data = json.load(f)
    def set_nested(d, key, value):
        parts = key.split('.')
        c = d
        for p in parts[:-1]:
            c = c.setdefault(p, {})
        c[parts[-1]] = value
    for key, value in translations.items():
        set_nested(data, key, value)
    with open(path, 'w') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# Translate the 2 remaining HP keys to natural Indonesian
apply('id', {
    'providers.nsfw': 'Konten Dewasa',  # NSFW content label
    'billing_page.col_status': 'Keadaan',  # Column header for status (more natural than "Status")
})

print('Applied Indonesian translations.')

# Verification
with open(D + 'id.json') as f:
    idj = json.load(f)
with open(D + 'en.json') as f:
    en = json.load(f)

both_translated = True
for key in ['providers.nsfw', 'billing_page.col_status']:
    parts = key.split('.')
    idv = idj
    for p in parts:
        idv = idv[p]
    env = en
    for p in parts:
        env = env[p]
    is_diff = idv != env
    print(f'{key}: ID="{idv}" EN="{env}" OK={is_diff}')
    if not is_diff:
        both_translated = False

total_done = json.load(open(D + 'id.json'))
print(f'\nBoth keys properly translated: {both_translated}')
