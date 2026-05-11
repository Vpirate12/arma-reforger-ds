import json, re, urllib.request

PATTERN = re.compile(r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL)
BASE = 'https://reforger.armaplatform.com/workshop'

with open(r'D:\Longbow\scenarios\WIP\PVE_North_Carolina_v1.3.json') as f:
    data = json.load(f)

mods = data['game']['mods']
print(f'Checking {len(mods)} mods...\n')

total = 0
missing = []

for mod in mods:
    mod_id = mod['modId']
    name = mod['name']
    url = f'{BASE}/{mod_id}'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            html = r.read().decode('utf-8', errors='ignore')
        m = PATTERN.search(html)
        if not m:
            missing.append(name)
            continue
        asset = json.loads(m.group(1))['props']['pageProps']['asset']
        size = asset.get('currentVersionSize', 0)
        total += size
        gb = size / (1024**3)
        print(f'  {name}: {gb:.2f} GB ({size:,} bytes)')
    except Exception as e:
        missing.append(f'{name} ({e})')

print(f'\nTotal: {total / (1024**3):.2f} GB ({total:,} bytes)')
if missing:
    print(f'\nCould not fetch ({len(missing)}):')
    for m in missing:
        print(f'  {m}')
