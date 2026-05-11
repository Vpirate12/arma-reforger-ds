import json, re, urllib.request
from collections import deque
from pathlib import Path

WORKSHOP_BASE = 'https://reforger.armaplatform.com/workshop'
PATTERN = re.compile(r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL)
SRC = Path(r'D:\Longbow\scenarios\WIP\PVE_North_Carolina_v1.0_Console.json')
WIP_DIR = Path(r'D:\Longbow\scenarios\WIP')

def fetch(mod_id):
    req = urllib.request.Request(f'{WORKSHOP_BASE}/{mod_id}', headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            html = r.read().decode('utf-8', errors='ignore')
        m = PATTERN.search(html)
        if not m:
            return mod_id, [], {}, 0
        asset = json.loads(m.group(1))['props']['pageProps']['asset']
        name = asset.get('name', mod_id)
        size = asset.get('currentVersionSize', 0)
        dep_ids, dep_names = [], {}
        for dep in asset.get('dependencies', []):
            a = dep.get('asset', {})
            did = (a.get('id') or '').upper()
            dname = a.get('name', did)
            if did and did != mod_id.upper():
                dep_ids.append(did)
                dep_names[did] = dname
        return name, dep_ids, dep_names, size
    except Exception as e:
        print(f'  WARN: {mod_id}: {e}')
        return mod_id, [], {}, 0

with open(SRC) as f:
    data = json.load(f)

mods = data['game']['mods']
print(f'Starting: {len(mods)} mods\n')

working = {m['modId'].upper(): dict(m) for m in mods}
added, graph, sizes = [], {}, {}
queue = deque(working.keys())
total_count = len(working)

while queue:
    mod_id = queue.popleft()
    if mod_id in graph:
        continue
    name, dep_ids, dep_names, size = fetch(mod_id)
    graph[mod_id] = dep_ids
    sizes[mod_id] = size
    print(f'  [{len(graph)}/{total_count}] {name}  ({size/(1024**2):.0f} MB)')
    for did in dep_ids:
        if did not in working:
            dname = dep_names.get(did, did)
            working[did] = {'modId': did, 'name': dname, 'required': False}
            added.append(working[did])
            queue.append(did)
            total_count += 1
            print(f'    + auto-added: {dname}')

sorted_mods, visited, in_stack = [], set(), set()

def visit(mid):
    if mid in visited: return
    if mid in in_stack:
        print(f'  WARN: circular dep at {mid}')
        return
    in_stack.add(mid)
    for dep in graph.get(mid, []):
        visit(dep)
    in_stack.discard(mid)
    visited.add(mid)
    if mid in working:
        sorted_mods.append(working[mid])

for mid in list(working.keys()):
    visit(mid)

data['game']['mods'] = sorted_mods
dest = WIP_DIR / SRC.name
with open(dest, 'w') as f:
    json.dump(data, f, indent=2)

total_bytes = sum(sizes.values())
print(f'\nResult : {len(sorted_mods)} mods  ({len(added)} auto-added)')
print(f'Size   : {total_bytes/(1024**3):.2f} GB')
print(f'PS5    : 25 GB limit — {"UNDER" if total_bytes < 25*(1024**3) else "OVER"}')
if added:
    for m in added:
        print(f'  + {m["name"]}')
print(f'\nWritten -> {dest}')
