import json

IPC_IDS = {
    '64DCE52D2F882ED2',  # IPC Higher AI Skill
    '6550E750653AA699',  # IPCAutonomousCaptureAI - dev
    '65766E0A71C84C76',  # IPC Modern Faction
    '673CF3A982325F14',  # IPC Ruha PVE
}

files = [
    r'D:\Longbow\scenarios\Production\PVE_North_Carolina_v1.3.json',
    r'D:\Longbow\scenarios\Production\PVE_North_Carolina_v1.0_Console.json',
]

for path in files:
    with open(path, 'r') as f:
        data = json.load(f)
    mods = data['game']['mods']
    before = len(mods)
    removed = [m['name'] for m in mods if m['modId'].upper() in IPC_IDS]
    data['game']['mods'] = [m for m in mods if m['modId'].upper() not in IPC_IDS]
    after = len(data['game']['mods'])
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)
    name = path.split('\\')[-1]
    print(f'{name}: {before} -> {after} mods')
    for r in removed:
        print(f'  removed: {r}')
