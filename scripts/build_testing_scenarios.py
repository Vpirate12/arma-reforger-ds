"""
Assemble IPC and COE2 Random Patrols scenario configs from backbone + layers.
Outputs to D:\\Longbow\\scenarios\\Testing\\ -- NOT Production.
"""
import json
import os
from pathlib import Path

BACKBONE = Path(r'D:\Longbow\scenarios\backbone.json')
TEMPLATE = Path(r'D:\Longbow\scenarios\Production\ipc_everon.json')
TESTING_DIR = Path(r'D:\Longbow\scenarios\Testing')
TESTING_DIR.mkdir(exist_ok=True)

SERVER_NAME = 'SpareTimeGaming @ TheIsland'
PUBLIC_IP = os.environ.get('PUBLIC_IP', '')

IPC_LAYER = [
    {'modId': '6550E750653AA699', 'name': 'IPCAutonomousCaptureAI - dev', 'required': False},
    {'modId': '64DCE52D2F882ED2', 'name': 'IPC Higher AI Skill',           'required': False},
    {'modId': '6910635C96A912D6', 'name': 'IPC Autonmous Capture Chopper', 'required': False},
    {'modId': '65766E0A71C84C76', 'name': 'IPC Modern Faction',            'required': False},
]

COE2_LAYER = [
    {'modId': '5ED61DC0AFE17E8E', 'name': 'Kex Scenario Core',   'required': False},
    {'modId': '65AD7C249E4ECDFB', 'name': 'ACE Captives Dev',    'required': False},
    {'modId': '60926835F4A7B0CA', 'name': 'COE2',                'required': False},
    {'modId': '68E22D4B54FE27EB', 'name': 'COE2 Random Patrols', 'required': False},
]

IPC_SCENARIOS = [
    {
        'filename': 'ipc_everon.json',
        'scenarioId': '{1B4745C0D4B6DB89}Missions/PVE_Everon_US_WZ.conf',
        'map_mods': [],
    },
    {
        'filename': 'ipc_ruha.json',
        'scenarioId': '{486415C3E2143685}Missions/PVE_Ruha_US.conf',
        'map_mods': [
            {'modId': '653CB36244ADBE0F', 'name': 'Ruha',         'required': False},
            {'modId': '673CF3A982325F14', 'name': 'IPC Ruha PVE', 'required': False},
        ],
    },
    {
        'filename': 'ipc_kunar.json',
        'scenarioId': '{E6B954FD300CA0D4}Missions/PVE_Kunar_US_Full.conf',
        'map_mods': [
            {'modId': '5C9691EA7FD7A79F', 'name': 'KunarProvince',  'required': False},
            {'modId': '657818864CAF5665', 'name': 'IPC Kunar PVE',  'required': False},
        ],
    },
    {
        'filename': 'ipc_novka.json',
        'scenarioId': '{ACE971637CC320CD}missions/PVE_Novka_US_WZ.conf',
        'map_mods': [
            {'modId': '6550CDE61DD51E14', 'name': 'Novka',     'required': False},
            {'modId': '6868DDECAC67453E', 'name': 'IPC Novka', 'required': False},
        ],
    },
]

COE2_SCENARIOS = [
    {
        'filename': 'coe2_arland.json',
        'scenarioId': '{A507A70F2F5BFC87}Missions/COE2_Arland_RP.conf',
        'map_mods': [],
    },
    {
        'filename': 'coe2_cain.json',
        'scenarioId': '{19D7F6D0ABEB2599}Missions/COE2_Cain_RP.conf',
        'map_mods': [],
    },
    {
        'filename': 'coe2_eden.json',
        'scenarioId': '{9BCFA00B6942A678}Missions/COE2_Eden_RP.conf',
        'map_mods': [],
    },
]

with open(BACKBONE) as f:
    backbone_mods = json.load(f)['mods']

with open(TEMPLATE) as f:
    template = json.load(f)

def build(scenario, layer):
    config = json.loads(json.dumps(template))
    config['game']['name'] = SERVER_NAME
    config['game']['scenarioId'] = scenario['scenarioId']
    config['game']['mods'] = backbone_mods + layer + scenario['map_mods']
    if PUBLIC_IP:
        config['game']['publicAddress'] = PUBLIC_IP
    dest = TESTING_DIR / scenario['filename']
    with open(dest, 'w') as f:
        json.dump(config, f, indent=2)
    print(f'  {scenario["filename"]:30s}  {len(config["game"]["mods"])} mods  {scenario["scenarioId"]}')

print('IPC PVE configs:')
for s in IPC_SCENARIOS:
    build(s, IPC_LAYER)

print('\nCOE2 Random Patrols configs:')
for s in COE2_SCENARIOS:
    build(s, COE2_LAYER)

print(f'\nAll 7 configs written to {TESTING_DIR}')
