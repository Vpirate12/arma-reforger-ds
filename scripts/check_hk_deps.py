import json, re, urllib.request

HK_IDS = {'5EE21381726E8B4C', '60E53A3903DD5F3E'}  # HK_Series, HK417_Magazines

with open(r'D:\Longbow\scenarios\WIP\PVE_North_Carolina_v1.3.json') as f:
    data = json.load(f)

other_mods = {m['modId'].upper(): m['name'] for m in data['game']['mods'] if m['modId'].upper() not in HK_IDS}

PATTERN = re.compile(r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL)
BASE = 'https://reforger.armaplatform.com/workshop'
found = False

for mod_id, name in other_mods.items():
    req = urllib.request.Request(f'{BASE}/{mod_id}', headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            html = r.read().decode('utf-8', errors='ignore')
        m = PATTERN.search(html)
        if not m:
            continue
        asset = json.loads(m.group(1))['props']['pageProps']['asset']
        for dep in asset.get('dependencies', []):
            did = (dep.get('asset', {}).get('id') or '').upper()
            if did in HK_IDS:
                print(f'DEPENDENCY: {name} depends on {did}')
                found = True
    except:
        pass

print('No dependencies found — safe to remove.' if not found else 'Dependencies found above.')
