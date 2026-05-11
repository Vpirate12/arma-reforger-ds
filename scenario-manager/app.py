import os
import json
import re
import sqlite3
from collections import deque
from datetime import datetime
from functools import wraps
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from werkzeug.middleware.proxy_fix import ProxyFix
import logging
import requests as http_requests

try:
    import docker as _docker_lib
    _docker_client = _docker_lib.from_env()
    _docker_client.ping()
    logger_tmp = logging.getLogger(__name__)
    logger_tmp.info("Docker socket connected.")
except Exception as _docker_err:
    _docker_lib = None
    _docker_client = None

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'change-this-in-production')

# Trust X-Forwarded-Proto from Cloudflare Tunnel so Flask sees HTTPS correctly
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

# Secure cookies when running behind Cloudflare Tunnel (HTTPS_ONLY=true)
if os.environ.get('HTTPS_ONLY', 'false').lower() == 'true':
    app.config['SESSION_COOKIE_SECURE'] = True
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

# Configuration
UPLOAD_FOLDER = os.environ.get('SCENARIOS_PATH', '/scenarios')
ALLOWED_EXTENSIONS = {'json'}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = MAX_FILE_SIZE

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Database initialization
def init_db():
    conn = sqlite3.connect('scenarios.db')
    c = conn.cursor()

    # Users table
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (id INTEGER PRIMARY KEY, username TEXT UNIQUE, password TEXT)''')

    # Active scenario tracking
    c.execute('''CREATE TABLE IF NOT EXISTS active_scenario
                 (id INTEGER PRIMARY KEY, scenario_name TEXT, updated_at TEXT)''')

    # Check Mods run tracking
    c.execute('''CREATE TABLE IF NOT EXISTS mod_checks
                 (id INTEGER PRIMARY KEY, filename TEXT, added_count INTEGER,
                  warning_count INTEGER, total_mods INTEGER, created_at TEXT)''')

    conn.commit()
    conn.close()

init_db()

# Helper functions
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def get_active_scenario():
    conn = sqlite3.connect('scenarios.db')
    c = conn.cursor()
    c.execute('SELECT scenario_name FROM active_scenario ORDER BY id DESC LIMIT 1')
    result = c.fetchone()
    conn.close()
    return result[0] if result else None

def set_active_scenario(scenario_name):
    conn = sqlite3.connect('scenarios.db')
    c = conn.cursor()
    c.execute('DELETE FROM active_scenario')
    c.execute('INSERT INTO active_scenario (scenario_name, updated_at) VALUES (?, ?)',
              (scenario_name, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def get_scenario_info(filename):
    """Extract scenario information from JSON file"""
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)

    try:
        with open(filepath, 'r') as f:
            data = json.load(f)

        # Extract game info from Arma Reforger config structure
        game_info = data.get('game', {})
        scenario_id = game_info.get('scenarioId', 'Unknown')

        # Extract map name from scenarioId path (e.g., "Missions/Arland PVE.conf" -> "Arland PVE")
        try:
            map_name = scenario_id.split('/')[-1].replace('.conf', '').replace('.pbo', '')
        except:
            map_name = 'Unknown'

        return {
            'name': filename.replace('.json', ''),
            'filename': filename,
            'mod_count': len(game_info.get('mods', [])),
            'map': map_name,
            'server_name': game_info.get('name', 'Unknown'),
            'max_players': game_info.get('maxPlayers', 'Unknown'),
            'size': os.path.getsize(filepath),
            'modified': datetime.fromtimestamp(os.path.getmtime(filepath)).isoformat()
        }
    except Exception as e:
        logger.error(f"Error reading scenario {filename}: {str(e)}")
        return None

def get_all_scenarios():
    """Get all scenarios from the folder"""
    scenarios = []

    if not os.path.exists(app.config['UPLOAD_FOLDER']):
        os.makedirs(app.config['UPLOAD_FOLDER'])

    for filename in os.listdir(app.config['UPLOAD_FOLDER']):
        if filename.endswith('.json'):
            info = get_scenario_info(filename)
            if info:
                info['is_active'] = (filename == get_active_scenario())
                scenarios.append(info)

    return sorted(scenarios, key=lambda x: x['name'])

# ---------------------------------------------------------------------------
# Mod dependency resolution (mirrors ModDependencyManager.cs logic)
# ---------------------------------------------------------------------------

WORKSHOP_BASE_URL = "https://reforger.armaplatform.com/workshop"

def _fetch_mod_page_data(mod_id):
    """Fetch workshop page for mod_id, return (name, dep_ids, dep_id_to_name)."""
    url = f"{WORKSHOP_BASE_URL}/{mod_id}"
    try:
        resp = http_requests.get(url, timeout=15, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        resp.raise_for_status()
    except Exception as e:
        logger.warning(f"Could not fetch workshop page for {mod_id}: {e}")
        return mod_id, [], {}

    match = re.search(
        r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>',
        resp.text, re.DOTALL)
    if not match:
        logger.warning(f"No __NEXT_DATA__ found for mod {mod_id}")
        return mod_id, [], {}

    try:
        data = json.loads(match.group(1))
        asset = data['props']['pageProps']['asset']
        name = asset.get('name', mod_id)
        dep_ids = []
        dep_names = {}
        for dep in asset.get('dependencies', []):
            dep_asset = dep.get('asset', {})
            dep_id = (dep_asset.get('id') or '').upper()
            dep_name = dep_asset.get('name', dep_id)
            if dep_id and dep_id != mod_id.upper():
                dep_ids.append(dep_id)
                dep_names[dep_id] = dep_name
        return name, dep_ids, dep_names
    except Exception as e:
        logger.warning(f"Failed to parse __NEXT_DATA__ for {mod_id}: {e}")
        return mod_id, [], {}


def resolve_mod_dependencies(mods):
    """BFS dependency discovery + DFS topological sort.

    mods: list of mod dicts (must have 'modId' and 'name').
    Returns (sorted_mods, added_mods, warnings).
    """
    working_set = {m['modId'].upper(): dict(m) for m in mods}
    added = []
    warnings = []
    graph = {}

    queue = deque(working_set.keys())
    while queue:
        mod_id = queue.popleft()
        if mod_id in graph:
            continue
        name, dep_ids, dep_names = _fetch_mod_page_data(mod_id)
        graph[mod_id] = dep_ids
        logger.info(f"CheckMods: {name} ({mod_id}): {len(dep_ids)} dep(s)")
        for dep_id in dep_ids:
            if dep_id not in working_set:
                dep_name = dep_names.get(dep_id, dep_id)
                new_mod = {'modId': dep_id, 'name': dep_name, 'required': False}
                working_set[dep_id] = new_mod
                added.append(new_mod)
                queue.append(dep_id)
                logger.info(f"CheckMods: auto-added missing dep {dep_name} ({dep_id})")

    sorted_mods = []
    visited = set()
    in_stack = set()

    def visit(mod_id):
        if mod_id in visited:
            return
        if mod_id in in_stack:
            warnings.append(f"Circular dependency involving mod {mod_id}")
            return
        in_stack.add(mod_id)
        for dep_id in graph.get(mod_id, []):
            visit(dep_id)
        in_stack.discard(mod_id)
        visited.add(mod_id)
        if mod_id in working_set:
            sorted_mods.append(working_set[mod_id])

    for mod_id in list(working_set.keys()):
        visit(mod_id)

    return sorted_mods, added, warnings


# Routes - Authentication
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        conn = sqlite3.connect('scenarios.db')
        c = conn.cursor()
        c.execute('SELECT id, password FROM users WHERE username = ?', (username,))
        user = c.fetchone()
        conn.close()

        if user and check_password_hash(user[1], password):
            session['user_id'] = user[0]
            session['username'] = username
            return redirect(url_for('dashboard'))
        else:
            return render_template('login.html', error='Invalid credentials')

    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# Routes - Dashboard
@app.route('/create')
@login_required
def create_scenario():
    return render_template('create.html', username=session.get('username'))

@app.route('/')
@login_required
def dashboard():
    scenarios = get_all_scenarios()
    active = get_active_scenario()
    return render_template('dashboard.html',
                         scenarios=scenarios,
                         active_scenario=active,
                         username=session.get('username'))

# API Routes
@app.route('/api/scenarios', methods=['GET'])
@login_required
def api_scenarios():
    scenarios = get_all_scenarios()
    return jsonify(scenarios)

@app.route('/api/scenarios/active', methods=['GET'])
@login_required
def api_active_scenario():
    active = get_active_scenario()
    return jsonify({'active': active})

@app.route('/api/scenarios/set-active', methods=['POST'])
@login_required
def api_set_active():
    data = request.get_json()
    scenario_name = data.get('scenario_name')

    # Validate that the scenario exists
    scenarios = [s['filename'] for s in get_all_scenarios()]
    if scenario_name not in scenarios:
        return jsonify({'error': 'Scenario not found'}), 404

    set_active_scenario(scenario_name)
    logger.info(f"User {session.get('username')} set active scenario to {scenario_name}")

    return jsonify({'success': True, 'active': scenario_name})

@app.route('/api/scenarios/upload', methods=['POST'])
@login_required
def api_upload():
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    file = request.files['file']

    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400

    if not allowed_file(file.filename):
        return jsonify({'error': 'Only JSON files allowed'}), 400

    try:
        # Validate JSON
        json.load(file)
        file.seek(0)

        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)

        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
        file.save(filepath)

        logger.info(f"User {session.get('username')} uploaded scenario {filename}")

        info = get_scenario_info(filename)
        return jsonify({'success': True, 'scenario': info}), 201

    except json.JSONDecodeError:
        return jsonify({'error': 'Invalid JSON file'}), 400
    except Exception as e:
        logger.error(f"Upload error: {str(e)}")
        return jsonify({'error': 'Upload failed'}), 500

@app.route('/api/scenarios/download/<filename>', methods=['GET'])
@login_required
def api_download(filename):
    """Download scenario JSON"""
    try:
        # Security: prevent directory traversal
        if '..' in filename or '/' in filename:
            return jsonify({'error': 'Invalid filename'}), 400

        filepath = os.path.join(app.config['UPLOAD_FOLDER'], secure_filename(filename))

        if not os.path.exists(filepath):
            return jsonify({'error': 'File not found'}), 404

        from flask import send_file
        logger.info(f"User {session.get('username')} downloaded scenario {filename}")
        return send_file(filepath, as_attachment=True, download_name=filename)

    except Exception as e:
        logger.error(f"Download error: {str(e)}")
        return jsonify({'error': 'Download failed'}), 500

@app.route('/api/scenarios/delete/<filename>', methods=['DELETE'])
@login_required
def api_delete(filename):
    """Delete scenario"""
    try:
        # Security: prevent directory traversal
        if '..' in filename or '/' in filename:
            return jsonify({'error': 'Invalid filename'}), 400

        filepath = os.path.join(app.config['UPLOAD_FOLDER'], secure_filename(filename))

        if not os.path.exists(filepath):
            return jsonify({'error': 'File not found'}), 404

        os.remove(filepath)
        logger.info(f"User {session.get('username')} deleted scenario {filename}")

        return jsonify({'success': True})

    except Exception as e:
        logger.error(f"Delete error: {str(e)}")
        return jsonify({'error': 'Delete failed'}), 500

@app.route('/api/scenarios/check-mods/<filename>', methods=['POST'])
@login_required
def api_check_mods(filename):
    """Resolve mod dependencies: auto-add missing deps and sort by load order."""
    try:
        if '..' in filename or '/' in filename:
            return jsonify({'error': 'Invalid filename'}), 400

        filepath = os.path.join(app.config['UPLOAD_FOLDER'], secure_filename(filename))
        if not os.path.exists(filepath):
            return jsonify({'error': 'File not found'}), 404

        with open(filepath, 'r') as f:
            scenario_data = json.load(f)

        if 'game' not in scenario_data or 'mods' not in scenario_data['game']:
            return jsonify({'error': 'Invalid scenario format'}), 400

        sorted_mods, added_mods, warnings = resolve_mod_dependencies(
            scenario_data['game']['mods'])

        scenario_data['game']['mods'] = sorted_mods

        with open(filepath, 'w') as f:
            json.dump(scenario_data, f, indent=2)

        conn = sqlite3.connect('scenarios.db')
        c = conn.cursor()
        c.execute('''INSERT INTO mod_checks
                    (filename, added_count, warning_count, total_mods, created_at)
                    VALUES (?, ?, ?, ?, ?)''',
                 (filename, len(added_mods), len(warnings),
                  len(sorted_mods), datetime.now().isoformat()))
        conn.commit()
        conn.close()

        logger.info(f"User {session.get('username')} ran Check Mods on {filename}: "
                   f"{len(added_mods)} dep(s) added, {len(warnings)} warning(s)")

        return jsonify({
            'success': True,
            'added_count': len(added_mods),
            'added_mods': [m['name'] for m in added_mods],
            'warnings': warnings,
            'total_mods': len(sorted_mods)
        })

    except json.JSONDecodeError:
        return jsonify({'error': 'Invalid JSON file'}), 400
    except Exception as e:
        logger.error(f"Check Mods error: {str(e)}")
        return jsonify({'error': f'Check Mods failed: {str(e)}'}), 500

# ---------------------------------------------------------------------------
# Docker container management
# ---------------------------------------------------------------------------

def _scenario_to_container(scenario_name):
    """ipc_everon -> ds-ipc-everon"""
    return 'ds-' + scenario_name.replace('_', '-')

def _get_ds_containers():
    if not _docker_client:
        return []
    try:
        result = []
        for c in _docker_client.containers.list(all=True):
            if c.name.startswith('ds-'):
                result.append({
                    'container_name': c.name,
                    'scenario': c.name[3:].replace('-', '_'),
                    'status': c.status,
                })
        return result
    except Exception as e:
        logger.error(f"Docker list error: {e}")
        return []

@app.route('/api/containers/status', methods=['GET'])
@login_required
def api_containers_status():
    if not _docker_client:
        return jsonify({'error': 'Docker socket unavailable'}), 503
    return jsonify(_get_ds_containers())

@app.route('/api/containers/activate', methods=['POST'])
@login_required
def api_containers_activate():
    if not _docker_client:
        return jsonify({'error': 'Docker socket unavailable'}), 503
    data = request.get_json()
    scenario = data.get('scenario')
    if not scenario:
        return jsonify({'error': 'scenario required'}), 400
    target_name = _scenario_to_container(scenario)
    stopped = None
    try:
        for c in _docker_client.containers.list(all=True):
            if c.name.startswith('ds-') and c.name != target_name and c.status == 'running':
                logger.info(f"Stopping container {c.name}")
                c.stop(timeout=30)
                stopped = c.name
        try:
            target = _docker_client.containers.get(target_name)
            if target.status != 'running':
                target.start()
        except _docker_lib.errors.NotFound:
            return jsonify({'error': f'Container {target_name} not found. Run: docker compose --profile {scenario.replace("_", "-")} up --no-start'}), 404
        set_active_scenario(scenario + '.json')
        logger.info(f"User {session.get('username')} activated {target_name} (stopped {stopped})")
        return jsonify({'activated': target_name, 'stopped': stopped})
    except Exception as e:
        logger.error(f"Activate error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/containers/logs/<scenario>', methods=['GET'])
@login_required
def api_containers_logs(scenario):
    if not _docker_client:
        return jsonify({'error': 'Docker socket unavailable'}), 503
    tail = request.args.get('tail', 100, type=int)
    container_name = _scenario_to_container(scenario)
    try:
        c = _docker_client.containers.get(container_name)
        logs = c.logs(tail=tail, timestamps=True).decode('utf-8', errors='replace')
        return jsonify({'container': container_name, 'logs': logs})
    except _docker_lib.errors.NotFound:
        return jsonify({'error': f'Container {container_name} not found'}), 404
    except Exception as e:
        logger.error(f"Logs error: {e}")
        return jsonify({'error': str(e)}), 500

# ---------------------------------------------------------------------------
# Scenario creator
# ---------------------------------------------------------------------------

@app.route('/api/mods/lookup', methods=['POST'])
@login_required
def api_mods_lookup():
    """Batch-look up mod IDs on the BI workshop. Returns list of {modId, name, error}."""
    data = request.get_json()
    ids = data.get('ids', [])
    if not ids:
        return jsonify([])
    results = []
    for mod_id in ids:
        mod_id = mod_id.strip().upper()
        if not mod_id:
            continue
        name, _dep_ids, _dep_names = _fetch_mod_page_data(mod_id)
        if name == mod_id:
            results.append({'modId': mod_id, 'name': None, 'error': 'Not found'})
        else:
            results.append({'modId': mod_id, 'name': name, 'error': None})
    return jsonify(results)

@app.route('/api/scenarios/create', methods=['POST'])
@login_required
def api_scenarios_create():
    """Build a server.json from form data and save to SCENARIOS_PATH."""
    data = request.get_json()

    filename = secure_filename((data.get('filename') or '').strip())
    if not filename:
        return jsonify({'error': 'Filename is required'}), 400
    if not filename.endswith('.json'):
        filename += '.json'

    server_name = (data.get('serverName') or '').strip()
    if not server_name:
        return jsonify({'error': 'Server name is required'}), 400

    scenario_id = (data.get('scenarioId') or '').strip()
    if not scenario_id:
        return jsonify({'error': 'Scenario ID is required'}), 400

    try:
        bind_port = int(data.get('bindPort', 2001))
        max_players = int(data.get('maxPlayers', 16))
        view_distance = int(data.get('viewDistance', 1200))
        ai_limit = int(data.get('aiLimit', -1))
    except (ValueError, TypeError):
        return jsonify({'error': 'Invalid numeric field'}), 400

    mods = data.get('mods', [])

    config = {
        'bindAddress': '0.0.0.0',
        'bindPort': bind_port,
        'publicAddress': '',
        'publicPort': bind_port,
        'a2s': {'address': '0.0.0.0', 'port': 17777},
        'rcon': {
            'address': '0.0.0.0',
            'port': 19999,
            'password': data.get('rconPassword', ''),
            'permission': 'monitor',
            'blacklist': [],
            'whitelist': [],
            'maxClients': 16
        },
        'game': {
            'name': server_name,
            'password': data.get('serverPassword', ''),
            'passwordAdmin': data.get('adminPassword', ''),
            'admins': [],
            'scenarioId': scenario_id,
            'maxPlayers': max_players,
            'visible': True,
            'crossPlatform': bool(data.get('crossPlatform', True)),
            'supportedPlatforms': ['PLATFORM_PC', 'PLATFORM_XBL', 'PLATFORM_PSN'],
            'gameProperties': {
                'serverMaxViewDistance': view_distance,
                'serverMinGrassDistance': 50,
                'networkViewDistance': 1000,
                'disableThirdPerson': bool(data.get('disableThirdPerson', False)),
                'fastValidation': True,
                'battlEye': bool(data.get('battlEye', True)),
                'VONDisableUI': False,
                'VONDisableDirectSpeechUI': False,
                'VONCanTransmitCrossFaction': False
            },
            'mods': [{'modId': m['modId'], 'name': m['name'], 'version': ''} for m in mods],
            'modsRequiredByDefault': True
        },
        'operating': {
            'lobbyPlayerSynchronise': True,
            'playerSaveTime': 120,
            'aiLimit': ai_limit,
            'slotReservationTimeout': 60,
            'disableNavmeshStreaming': [],
            'disableServerShutdown': False,
            'disableCrashReporter': False,
            'disableAI': False,
            'joinQueue': {'maxSize': 0}
        }
    }

    try:
        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        with open(filepath, 'w') as f:
            json.dump(config, f, indent=2)
        logger.info(f"User {session.get('username')} created scenario {filename}")
        return jsonify({'success': True, 'filename': filename})
    except Exception as e:
        logger.error(f"Create scenario error: {e}")
        return jsonify({'error': str(e)}), 500

# Health check
@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok'}), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
