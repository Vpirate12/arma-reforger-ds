import urllib.request, json, re

# All IPC mods present across the two configs
IPC_IDS = {
    '64DCE52D2F882ED2': 'IPC Higher AI Skill',
    '6550E750653AA699': 'IPCAutonomousCaptureAI - dev',
    '65766E0A71C84C76': 'IPC Modern Faction',
    '673CF3A982325F14': 'IPC Ruha PVE',
}

# All other mod IDs in v1.3 to check whether any depend on IPC mods
with open(r'D:\Longbow\scenarios\Production\PVE_North_Carolina_v1.3.json') as f:
    data = json.load(f)

other_mods = {
    m['modId'].upper(): m['name']
    for m in data['game']['mods']
    if m['modId'].upper() not in IPC_IDS
}

BASE = 'https://reforger.armaplatform.com/workshop'
PATTERN = re.compile(r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL)

print(f'Checking {len(other_mods)} non-IPC mods for IPC dependencies...\n')
found_any = False

for mod_id, mod_name in other_mods.items():
    url = f'{BASE}/{mod_id}'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            html = r.read().decode('utf-8', errors='ignore')
        m = PATTERN.search(html)
        if not m:
            continue
        asset = json.loads(m.group(1))['props']['pageProps']['asset']
        for dep in asset.get('dependencies', []):
            dep_id = (dep.get('asset', {}).get('id') or '').upper()
            if dep_id in IPC_IDS:
                print(f'  DEPENDENCY: {mod_name} depends on {IPC_IDS[dep_id]}')
                found_any = True
    except Exception as e:
        print(f'  WARN: could not fetch {mod_name}: {e}')

if not found_any:
    print('No other mods depend on IPC mods — safe to remove all.')
