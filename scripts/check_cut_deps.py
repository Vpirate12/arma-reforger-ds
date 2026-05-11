import json, re, urllib.request

CUT_IDS = {
    '66ECB040A9CB447C',  # WCS and RHS Arsenal Lite
    '6602C1EC7E5A4A87',  # WCS_Clothing_Assets
    '6152CB0BD0684837',  # WCS_Clothing
    '60ED3CC6E7E40221',  # Sikorsky H60 Project
    '64E57DE0D6C617B1',  # BetterBlackhawkHandling
}

with open(r'D:\Longbow\scenarios\WIP\PVE_North_Carolina_v1.0_Console.json') as f:
    mods = json.load(f)['game']['mods']

other_mods = {m['modId'].upper(): m['name'] for m in mods if m['modId'].upper() not in CUT_IDS}

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
            if did in CUT_IDS:
                dep_name = dep.get('asset', {}).get('name', did)
                print(f'DEPENDENCY: {name} depends on {dep_name}')
                found = True
    except:
        pass

print('No dependencies found — safe to remove.' if not found else 'See dependencies above.')
