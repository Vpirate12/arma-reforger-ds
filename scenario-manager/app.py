import os
import json
import re
import secrets
import socket
import sqlite3
import urllib.parse
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

# OAuth configuration
_OAUTH_BASE = os.environ.get('OAUTH_BASE_URL', 'http://localhost:5000')
DISCORD_CLIENT_ID     = os.environ.get('DISCORD_CLIENT_ID')
DISCORD_CLIENT_SECRET = os.environ.get('DISCORD_CLIENT_SECRET')
DISCORD_GUILD_ID      = os.environ.get('DISCORD_GUILD_ID')
DISCORD_REDIRECT_URI  = f"{_OAUTH_BASE}/auth/discord/callback"
GOOGLE_CLIENT_ID      = os.environ.get('GOOGLE_CLIENT_ID')
GOOGLE_CLIENT_SECRET  = os.environ.get('GOOGLE_CLIENT_SECRET')
GOOGLE_REDIRECT_URI   = f"{_OAUTH_BASE}/auth/google/callback"
ALLOWED_GOOGLE_EMAILS = {e.strip() for e in os.environ.get('ALLOWED_GOOGLE_EMAILS', '').split(',') if e.strip()}

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

    # Base mods — applied to every scenario via sync
    c.execute('''CREATE TABLE IF NOT EXISTS base_mods
                 (id INTEGER PRIMARY KEY, mod_id TEXT UNIQUE NOT NULL,
                  name TEXT NOT NULL, added_at TEXT)''')

    # OAuth user tracking
    c.execute('''CREATE TABLE IF NOT EXISTS oauth_users
                 (id INTEGER PRIMARY KEY, provider TEXT NOT NULL,
                  provider_user_id TEXT NOT NULL, username TEXT NOT NULL,
                  email TEXT, UNIQUE(provider, provider_user_id))''')

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

        operating = data.get('operating', {})
        return {
            'name': filename.replace('.json', ''),
            'filename': filename,
            'mod_count': len(game_info.get('mods', [])),
            'map': map_name,
            'server_name': game_info.get('name', 'Unknown'),
            'max_players': game_info.get('maxPlayers', 'Unknown'),
            'ai_limit': operating.get('aiLimit', -1),
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

@app.route('/login/discord')
def login_discord():
    state = secrets.token_urlsafe(16)
    session['oauth_state'] = state
    params = {
        'client_id': DISCORD_CLIENT_ID,
        'redirect_uri': DISCORD_REDIRECT_URI,
        'response_type': 'code',
        'scope': 'identify email guilds',
        'state': state,
    }
    return redirect('https://discord.com/oauth2/authorize?' + urllib.parse.urlencode(params, quote_via=urllib.parse.quote))

@app.route('/auth/discord/callback')
def auth_discord_callback():
    code = request.args.get('code')
    state = request.args.get('state')
    if not code or state != session.pop('oauth_state', None):
        return redirect(url_for('login'))
    resp = http_requests.post('https://discord.com/api/oauth2/token', data={
        'client_id': DISCORD_CLIENT_ID,
        'client_secret': DISCORD_CLIENT_SECRET,
        'grant_type': 'authorization_code',
        'code': code,
        'redirect_uri': DISCORD_REDIRECT_URI,
    })
    token = resp.json().get('access_token')
    if not token:
        return render_template('login.html', error='Discord auth failed.')
    user = http_requests.get('https://discord.com/api/users/@me',
                             headers={'Authorization': f'Bearer {token}'}).json()
    discord_id = user.get('id')
    username = user.get('username', 'unknown')
    email = user.get('email')
    if not discord_id:
        return render_template('login.html', error='Could not retrieve Discord profile.')
    if DISCORD_GUILD_ID:
        guilds = http_requests.get('https://discord.com/api/users/@me/guilds',
                                   headers={'Authorization': f'Bearer {token}'}).json()
        if not isinstance(guilds, list) or not any(g.get('id') == DISCORD_GUILD_ID for g in guilds):
            return render_template('login.html', error='You must be a member of the Spare Time Gaming Discord server to access this.')
    conn = sqlite3.connect('scenarios.db')
    c = conn.cursor()
    c.execute('INSERT OR IGNORE INTO oauth_users (provider, provider_user_id, username, email) VALUES (?,?,?,?)',
              ('discord', discord_id, username, email))
    conn.commit()
    conn.close()
    session['user_id'] = f'discord:{discord_id}'
    session['username'] = username
    session['oauth_provider'] = 'discord'
    return redirect(url_for('dashboard'))

@app.route('/login/google')
def login_google():
    state = secrets.token_urlsafe(16)
    session['oauth_state'] = state
    params = {
        'client_id': GOOGLE_CLIENT_ID,
        'redirect_uri': GOOGLE_REDIRECT_URI,
        'response_type': 'code',
        'scope': 'openid email profile',
        'state': state,
        'access_type': 'online',
    }
    return redirect('https://accounts.google.com/o/oauth2/auth?' + urllib.parse.urlencode(params))

@app.route('/auth/google/callback')
def auth_google_callback():
    code = request.args.get('code')
    state = request.args.get('state')
    if not code or state != session.pop('oauth_state', None):
        return redirect(url_for('login'))
    resp = http_requests.post('https://oauth2.googleapis.com/token', data={
        'client_id': GOOGLE_CLIENT_ID,
        'client_secret': GOOGLE_CLIENT_SECRET,
        'grant_type': 'authorization_code',
        'code': code,
        'redirect_uri': GOOGLE_REDIRECT_URI,
    })
    token = resp.json().get('access_token')
    if not token:
        return render_template('login.html', error='Google auth failed.')
    user = http_requests.get('https://www.googleapis.com/oauth2/v2/userinfo',
                             headers={'Authorization': f'Bearer {token}'}).json()
    email = user.get('email')
    google_id = user.get('id')
    username = user.get('name') or email
    if not email or not google_id:
        return render_template('login.html', error='Could not retrieve Google profile.')
    if ALLOWED_GOOGLE_EMAILS and email not in ALLOWED_GOOGLE_EMAILS:
        return render_template('login.html', error='Your Google account is not authorized.')
    conn = sqlite3.connect('scenarios.db')
    c = conn.cursor()
    c.execute('INSERT OR IGNORE INTO oauth_users (provider, provider_user_id, username, email) VALUES (?,?,?,?)',
              ('google', google_id, username, email))
    conn.commit()
    conn.close()
    session['user_id'] = f'google:{google_id}'
    session['username'] = username
    session['oauth_provider'] = 'google'
    return redirect(url_for('dashboard'))

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

_A2S_HOST = os.environ.get('A2S_HOST', 'host.docker.internal')
_A2S_PORT = 17777

def _a2s_ready(timeout=1.5):
    """Return True if the DS server responds to an A2S_INFO query (fully up)."""
    A2S_INFO = b'\xFF\xFF\xFF\xFFTSource Engine Query\x00'
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(timeout)
        sock.sendto(A2S_INFO, (_A2S_HOST, _A2S_PORT))
        data, _ = sock.recvfrom(4096)
        if data[:4] != b'\xFF\xFF\xFF\xFF':
            return False
        if data[4:5] == b'\x41':  # challenge response — send reply
            sock.sendto(A2S_INFO + data[5:9], (_A2S_HOST, _A2S_PORT))
            data, _ = sock.recvfrom(4096)
        return data[4:5] == b'\x49'
    except Exception:
        return False
    finally:
        try:
            sock.close()
        except Exception:
            pass


def _scenario_to_container(scenario_name):
    """ipc_everon -> ds-ipc-everon"""
    return 'ds-' + scenario_name.replace('_', '-')

def _get_ds_containers():
    if not _docker_client:
        return []
    try:
        result = []
        any_running = False
        containers = list(_docker_client.containers.list(all=True))
        for c in containers:
            if c.name.startswith('ds-') and c.status == 'running':
                any_running = True
                break
        a2s_up = _a2s_ready() if any_running else False
        for c in containers:
            if c.name.startswith('ds-'):
                restart_count = c.attrs.get('RestartCount', 0)
                state         = c.attrs.get('State', {})
                exit_code     = state.get('ExitCode', 0)

                if c.status == 'restarting':
                    health = 'crash_loop'
                elif c.status == 'running' and restart_count >= 3 and exit_code != 0:
                    health = 'crash_loop'
                elif c.status == 'running':
                    health = 'green' if a2s_up else 'yellow'
                else:
                    health = 'red'

                result.append({
                    'container_name': c.name,
                    'scenario': c.name[3:].replace('-', '_'),
                    'status': c.status,
                    'health': health,
                    'restart_count': restart_count,
                    'exit_code': exit_code,
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

@app.route('/api/containers/reset/<scenario>', methods=['POST'])
@login_required
def api_containers_reset(scenario):
    """Stop then start a container to clear its restart count."""
    if not _docker_client:
        return jsonify({'error': 'Docker socket unavailable'}), 503
    container_name = _scenario_to_container(scenario)
    try:
        c = _docker_client.containers.get(container_name)
        logger.info(f"User {session.get('username')} resetting crash-looping container {container_name}")
        c.stop(timeout=15)
        c.start()
        return jsonify({'success': True, 'container': container_name})
    except _docker_lib.errors.NotFound:
        return jsonify({'error': f'Container {container_name} not found'}), 404
    except Exception as e:
        logger.error(f"Reset error: {e}")
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

def _fetch_mod_scenarios(mod_id):
    """Fetch scenario paths from the workshop /scenarios page for a mod."""
    url = f"{WORKSHOP_BASE_URL}/{mod_id}/scenarios"
    try:
        resp = http_requests.get(url, timeout=15, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        resp.raise_for_status()
    except Exception as e:
        logger.warning(f"Could not fetch scenarios page for mod {mod_id}: {e}")
        return []

    # Try __NEXT_DATA__ JSON first
    match = re.search(r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>', resp.text, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(1))
            page_props = data['props']['pageProps']
            raw = page_props.get('scenarios') or page_props.get('asset', {}).get('scenarios', [])
            ids = [s.get('scenarioId') or s.get('id', '') for s in raw if isinstance(s, dict)]
            ids = [i for i in ids if i]
            if ids:
                return ids
        except Exception:
            pass

    # Fall back: scrape scenario ID pattern directly from HTML
    return list(dict.fromkeys(
        re.findall(r'\{[0-9A-Fa-f]+\}[^\s<"\']+\.conf', resp.text)
    ))


@app.route('/api/mods/scenarios', methods=['POST'])
@login_required
def api_mods_scenarios():
    """Return scenario IDs provided by a list of mod IDs."""
    data = request.get_json()
    mod_ids = data.get('ids', [])
    results = []
    seen = set()
    for mod_id in mod_ids:
        mod_id = mod_id.strip().upper()
        if not mod_id:
            continue
        for scen_id in _fetch_mod_scenarios(mod_id):
            if scen_id not in seen:
                seen.add(scen_id)
                results.append({'modId': mod_id, 'scenarioId': scen_id})
    return jsonify(results)


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

# ---------------------------------------------------------------------------
# Base mods management
# ---------------------------------------------------------------------------

@app.route('/api/base-mods', methods=['GET'])
@login_required
def api_base_mods_list():
    conn = sqlite3.connect('scenarios.db')
    c = conn.cursor()
    c.execute('SELECT mod_id, name, added_at FROM base_mods ORDER BY id')
    rows = [{'modId': r[0], 'name': r[1], 'addedAt': r[2]} for r in c.fetchall()]
    conn.close()
    return jsonify(rows)

@app.route('/api/base-mods', methods=['POST'])
@login_required
def api_base_mods_add():
    data = request.get_json()
    mod_id = (data.get('modId') or '').strip().upper()
    name = (data.get('name') or '').strip()
    if not mod_id or not name:
        return jsonify({'error': 'modId and name required'}), 400
    try:
        conn = sqlite3.connect('scenarios.db')
        c = conn.cursor()
        c.execute('INSERT INTO base_mods (mod_id, name, added_at) VALUES (?, ?, ?)',
                  (mod_id, name, datetime.now().isoformat()))
        conn.commit()
        conn.close()
        logger.info(f"User {session.get('username')} added base mod {name} ({mod_id})")
        return jsonify({'success': True})
    except sqlite3.IntegrityError:
        return jsonify({'error': 'Mod already in base list'}), 409

@app.route('/api/base-mods/<mod_id>', methods=['DELETE'])
@login_required
def api_base_mods_remove(mod_id):
    mod_id = mod_id.upper()
    conn = sqlite3.connect('scenarios.db')
    c = conn.cursor()
    c.execute('DELETE FROM base_mods WHERE mod_id = ?', (mod_id,))
    deleted = c.rowcount
    conn.commit()
    conn.close()
    if not deleted:
        return jsonify({'error': 'Mod not found'}), 404
    logger.info(f"User {session.get('username')} removed base mod {mod_id}")
    return jsonify({'success': True})

@app.route('/api/scenarios/sync-base-mods', methods=['POST'])
@login_required
def api_sync_base_mods():
    conn = sqlite3.connect('scenarios.db')
    c = conn.cursor()
    c.execute('SELECT mod_id, name FROM base_mods')
    base_mods = [{'modId': r[0], 'name': r[1], 'version': '', 'required': False}
                 for r in c.fetchall()]
    conn.close()

    if not base_mods:
        return jsonify({'success': True, 'updated': 0, 'message': 'No base mods configured'})

    base_mod_ids = {m['modId'].upper() for m in base_mods}
    updated = []
    errors = []

    for filename in os.listdir(app.config['UPLOAD_FOLDER']):
        if not filename.endswith('.json'):
            continue
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        try:
            with open(filepath, 'r') as f:
                data = json.load(f)
            if 'game' not in data or 'mods' not in data['game']:
                continue
            existing_ids = {m.get('modId', '').upper() for m in data['game']['mods']}
            to_add = [m for m in base_mods if m['modId'].upper() not in existing_ids]
            if to_add:
                data['game']['mods'] = to_add + data['game']['mods']
                with open(filepath, 'w') as f:
                    json.dump(data, f, indent=2)
                updated.append(filename)
        except Exception as e:
            errors.append(f"{filename}: {str(e)}")

    logger.info(f"User {session.get('username')} synced base mods to {len(updated)} scenario(s)")
    return jsonify({'success': True, 'updated': len(updated),
                    'updatedFiles': updated, 'errors': errors})


# Health check
@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok'}), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
