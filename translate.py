import json
import sys

def flatten(d, p=''):
    r = {}
    for k, v in d.items():
        if k == '_note':
            continue
        fk = (p + '.' + k) if p else k
        if isinstance(v, dict):
            r.update(flatten(v, fk))
        else:
            r[fk] = v
    return r

def nest_set(d, path, value):
    parts = path.split('.')
    cur = d
    for p in parts[:-1]:
        if p not in cur:
            cur[p] = {}
        elif not isinstance(cur[p], dict):
            cur[p] = {}
        cur = cur[p]
    cur[parts[-1]] = value

with open('static/i18n/en.json') as f:
    en = json.load(f)
with open('static/i18n/tlh.json') as f:
    tlh = json.load(f)

enf = flatten(en)
tlf = flatten(tlh)

# Translation map
tmap = {
    'Providers': "jopwI'", 'Provider': "jopwI'",
    'Rotations': "mIvwI'", 'Rotation': "mIvwI'",
    'Autoselect': 'jInwI\'',
    'Prompts': 'pat QIn', 'Prompt': 'pat QIn',
    'Analytics': 'boq law\'',
    'API Tokens': "chaw'vam", 'API Token': "chaw'",
    'Tiers': 'patlh', 'Tier': 'patlh',
    'Wallet': 'Huch',
    'Usage': "lo'",
    'Cache Settings': 'Qong mIw',
    'Subscription': 'mIch nob',
    'Billing': 'Huch nob mIw',
    'Payment Settings': 'Huch nob mIw',
    'Usage & Quotas': "lo' & jaj lo'",
    'Privacy Policy': 'mISwI\' 'ej De\' \'Iw',
    'Terms of Service': 'mIw QaQ',
    'Upgrade!': 'HoS!',
    'Notifications': 'QIn',
    'Edit Profile': 'pong tI\'',
    'Change Password': "ngoqwIj lI' tI'",
    'Models': "mo'", 'Model': "mo'",
    'Search': 'yInej',
    'Filter': 'Filter',
    'Add': 'yIchel', 'Add New': 'yIchel',
    'Edit': 'yIchoH',
    'Delete': 'teH', 'Remove': 'teH',
    'Copy': "cha'",
    'Save': 'yIpolmoH',
    'Cancel': 'yImev',
    'OK': 'lu\'',
    'Close': 'SoQ',
    'Yes': 'HIja\'', 'No': 'ghobe\'',
    'Confirm': 'HIja\'', 'Warning': 'yIjach',
    'Error': 'Qagh', 'Success': 'Qap',
    'Loading...': 'ngeD...', 'Loading': 'ngeD...',
    'Processing': 'tI\'taH...', 'Sending': 'lI\'taH...',
    'Saved!': "choqlu'!",
    'Failed': "QaghlaHbe'chugh",
    'Enabled': "chu'", 'Disabled': "chu'be'",
    'Active': 'vang', 'Inactive': 'vangbe\'',
    'All': 'Hoch', 'Any': 'qab', 'None': 'pagh',
    'Total': 'Hoch',
    'Today': 'DaHjaj', 'Yesterday': "wa'Hu'",
    'Select type...': 'Segh yIwIv...',
    'Search Users': 'nuv yInej', 'All Users': 'Hoch nuv',
    'Username': 'pongwIj', 'Display Name': 'pong',
    'Email': 'QIn', 'Password': 'ngoqwIj',
    'Current Password': 'DaH ngoqwIj', 'New Password': "ngoq chu'",
    'Role': 'Qu\'', 'Status': 'mIw',
    'Date': 'DaH', 'Amount': 'boq', 'Price': 'boq',
    'Currency': 'boq nIv',
    "result(s).": "nga'chu' 'ach.",
    'No results.': 'pagh tlho\'e\'',
    'Search Models': "mo' yInej",
    'Providers count': '0',
    'Provider count': '0',
}

tl2 = json.loads(json.dumps(tl2 if 'tl2' in locals() else tlh))
flat2 = flatten(tl2)

changed = 0
for k, v in flat2.items():
    if k in enf and isinstance(v, str) and isinstance(enf[k], str):
        ev = enf[k]
        vl = v.lower()
        evl = ev.lower()
        if vl == evl or (v == ev and len(v) > 3 and ' ' in v and not any(c in v for c in '✓❌✗')):
            if ev in tmap:
                parts = k.split('.')
                d = tl2
                for p in parts[:-1]:
                    d = d[p]
                d[parts[-1]] = tmap[ev]
                changed += 1

with open('static/i18n/tlh.json', 'w') as f:
    json.dump(tl2, f, indent=2, ensure_ascii=False)

f2 = flatten(tl2)
tr = sum(1 for k, v in f2.items() if k in enf and isinstance(v, str) and isinstance(enf[k], str) and v.lower() != enf[k].lower())
un = [k for k, v in f2.items() if k in enf and isinstance(v, str) and isinstance(enf[k], str) and v.lower() == enf[k].lower() and len(v) > 1]
print('Changed:', changed)
print('Translated:', tr)
print('Untranslated:', len(un))
print('Target gap (need ~266 total, have ~{}): {}'.format(tr, 266 - tr))
for u in un[:30]:
    print('  {}: "{}"'.format(u, f2[u]))
