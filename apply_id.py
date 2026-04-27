import json

# Apply the translations
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

# nsFw field label in providers section — translate to natural Indonesian
# "NSFW" is an English technical term, but UI labels should be localized
# Standard Indonesian translation for age-restricted/not-safe content
apply('id', {
    'providers.nsfw': 'Konten Dewasa',
    'billing_page.col_status': 'Status',  # Status is standard borrowed term; keep as-is but ensure marked as translated
})

print('Translations applied successfully.')

with open(D + 'id.json') as f:
    idj = json.load(f)

with open(D + 'en.json') as f:
    en = json.load(f)

# Verify the 2 keys now differ
for key in ['providers.nsfw', 'billing_page.col_status']:
    parts = key.split('.')
    idv = idj
    for p in parts:
        idv = idv[p]
    env = en
    for p in parts:
        env = env[p]
    print(f'{key}: EN="{env}" ID="{idv}" different={idv!=env}')
