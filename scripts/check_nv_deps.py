import urllib.request, json, re

NV_MODS = {
    '64722DADC53CB75E': 'NV-System',
    '65F93D3655B7D63C': 'Northcom - Retro Night Vision',
    '65B77DB66391F6F3': 'NVG-Sights',
    '66E01B8D63D29498': 'Northcom Photonics',
    '663EEED7D9BCA814': 'ARMA-RY NIGHT VISION',
    '66F4B3456A31C2A1': 'RHS Peripheral NVGs',
}

BASE = 'https://reforger.armaplatform.com/workshop'
PATTERN = re.compile(r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL)

for mod_id, mod_name in NV_MODS.items():
    url = f'{BASE}/{mod_id}'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            html = r.read().decode('utf-8', errors='ignore')
        m = PATTERN.search(html)
        if not m:
            print(f'{mod_name}: no __NEXT_DATA__')
            continue
        data = json.loads(m.group(1))
        asset = data['props']['pageProps']['asset']
        deps = asset.get('dependencies', [])
        dep_names = [d.get('asset', {}).get('name', '?') for d in deps]
        size_bytes = asset.get('currentVersionSize', 0)
        size_mb = size_bytes / (1024 * 1024)
        print(f'{mod_name} ({mod_id}) [{size_mb:.0f} MB]')
        if dep_names:
            for d in dep_names:
                print(f'  dep: {d}')
        else:
            print(f'  (no dependencies)')
    except Exception as e:
        print(f'{mod_name}: ERROR {e}')
