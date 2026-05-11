"""
Extract the backbone mod list from the reference server preset JSON.
Strips excluded (map-specific / game-mode) mods and writes backbone.json.
"""
import json
from pathlib import Path

PRESET_SRC = Path(r'D:\Longbow\scenarios\TheIslandCPVEFinal.json')
BACKBONE_OUT = Path(r'D:\Longbow\scenarios\backbone.json')

EXCLUDE_IDS = {
    '61B514B96692C049',  # ConflictPVERemixedVanilla2.0
    '628729E87E79DA7F',  # LinearConflictPVE
    '61E57C95FF956A54',  # North Carolina Conflict
    '60EEF465FD67ECF8',  # North Carolina Back Country
    '67362D59F44F8251',  # North Carolina - Conflict PvE
    '66EE3582A17A8FB7',  # SH-ExtremeDynamicRange
    '60E2F3F9883D688C',  # Stay Alive Core
    '5EE4F56A883654EB',  # Stay Alive
}

with open(PRESET_SRC) as f:
    preset = json.load(f)

all_mods = preset['mods']
backbone = [m for m in all_mods if m['modId'].upper() not in EXCLUDE_IDS]
excluded = [m for m in all_mods if m['modId'].upper() in EXCLUDE_IDS]

with open(BACKBONE_OUT, 'w') as f:
    json.dump({'mods': backbone}, f, indent=2)

print(f'Source : {len(all_mods)} mods')
print(f'Excluded ({len(excluded)}):')
for m in excluded:
    print(f'  - {m["name"]} ({m["modId"]})')
print(f'Backbone: {len(backbone)} mods')
print(f'Written -> {BACKBONE_OUT}')
