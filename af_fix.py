import json

D = '/working/aisbf/static/i18n/'
path = D + 'af.json'
with open(path, 'r', encoding='utf-8') as f:
    data = json.load(f)

# The correct key (from TRANSLATIONS_TODO) is resets_on_1st, but Afrikaans has resets_on_1ste
# We need to use the correct English key and give it the Afrikaans value

# First, let me check what the structure is
if 'usage_page' in data:
    print('usage_page keys:', list(data['usage_page'].keys()))
    
# The correct key is resets_on_1st (not 1ste) - this is already set to English
# We need to keep it as English - or translate it

# Actually, let me check what value the EN has for this key
with open('/working/aisbf/static/i18n/en.json', 'r', encoding='utf-8') as f:
    en = json.load(f)

# Check the key from TRANSLATIONS_TODO - it should be resets_on_1st
en_val = en['usage_page']['resets_on_1st']
print(f'English usage_page.resets_on_1st: {en_val}')

# The Afrikaans has resets_on_1ste which is different
af_val = data['usage_page']['resets_on_1ste']
print(f'Afrikaans usage_page.resets_on_1ste: {af_val}')

# The issue is that resets_on_1st (without 'e') is set to English "Resets on the 1st"
# And this is what's being detected as untranslated
# We need to update it to the Afrikaans translation

data['usage_page']['resets_on_1st'] = "Terugstelling op die 1ste"

# Remove the old key
del data['usage_page']['resets_on_1ste']

with open(path, 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print('Fixed: Updated usage_page.resets_on_1st to Afrikaans')
