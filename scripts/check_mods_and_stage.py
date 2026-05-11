"""
Run Check Mods (BFS dep discovery + DFS topo sort) on scenario files
and write the results to the WIP folder.
"""
import json, re, urllib.request
from collections import deque
from pathlib import Path

WORKSHOP_BASE = 'https://reforger.armaplatform.com/workshop'
PATTERN = re.compile(r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL)

SOURCE_FILES = [
    r'D:\Longbow\scenarios\Testing\ipc_everon.json',
    r'D:\Longbow\scenarios\Testing\ipc_ruha.json',
    r'D:\Longbow\scenarios\Testing\ipc_kunar.json',
    r'D:\Longbow\scenarios\Testing\ipc_novka.json',
    r'D:\Longbow\scenarios\Testing\coe2_arland.json',
    r'D:\Longbow\scenarios\Testing\coe2_cain.json',
    r'D:\Longbow\scenarios\Testing\coe2_eden.json',
    r'D:\Longbow\scenarios\Production\PVE_North_Carolina_v1.3.json',
    r'D:\Longbow\scenarios\Production\PVE_North_Carolina_v1.0_Console.json',
]
WIP_DIR = Path(r'D:\Longbow\scenarios\WIP')
WIP_DIR.mkdir(exist_ok=True)


def fetch_page_data(mod_id):
    url = f'{WORKSHOP_BASE}/{mod_id}'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            html = r.read().decode('utf-8', errors='ignore')
    except Exception as e:
        print(f'  WARN: could not fetch {mod_id}: {e}')
        return mod_id, [], {}
    m = PATTERN.search(html)
    if not m:
        return mod_id, [], {}
    try:
        asset = json.loads(m.group(1))['props']['pageProps']['asset']
        name = asset.get('name', mod_id)
        dep_ids, dep_names = [], {}
        for dep in asset.get('dependencies', []):
            a = dep.get('asset', {})
            did = (a.get('id') or '').upper()
            dname = a.get('name', did)
            if did and did != mod_id.upper():
                dep_ids.append(did)
                dep_names[did] = dname
        return name, dep_ids, dep_names
    except Exception as e:
        print(f'  WARN: parse error for {mod_id}: {e}')
        return mod_id, [], {}


def resolve(mods):
    working = {m['modId'].upper(): dict(m) for m in mods}
    added, graph = [], {}
    queue = deque(working.keys())
    total = len(working)

    while queue:
        mod_id = queue.popleft()
        if mod_id in graph:
            continue
        name, dep_ids, dep_names = fetch_page_data(mod_id)
        graph[mod_id] = dep_ids
        print(f'  [{len(graph)}/{total}] {name}  ({len(dep_ids)} dep(s))')
        for did in dep_ids:
            if did not in working:
                dname = dep_names.get(did, did)
                working[did] = {'modId': did, 'name': dname, 'required': False}
                added.append(working[did])
                queue.append(did)
                total += 1
                print(f'    + auto-added: {dname}')

    sorted_mods, visited, in_stack = [], set(), set()

    def visit(mid):
        if mid in visited:
            return
        if mid in in_stack:
            print(f'  WARN: circular dependency at {mid}')
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

    return sorted_mods, added


for src_path in SOURCE_FILES:
    src = Path(src_path)
    print(f'\n=== {src.name} ===')
    with open(src) as f:
        data = json.load(f)

    mods = data['game']['mods']
    print(f'Starting with {len(mods)} mods...')

    sorted_mods, added = resolve(mods)
    data['game']['mods'] = sorted_mods

    dest = WIP_DIR / src.name
    with open(dest, 'w') as f:
        json.dump(data, f, indent=2)

    print(f'\nResult: {len(sorted_mods)} mods  ({len(added)} auto-added)')
    if added:
        for m in added:
            print(f'  + {m["name"]}')
    print(f'Written -> {dest}')
