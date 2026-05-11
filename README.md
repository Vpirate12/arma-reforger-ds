# Arma Reforger Dedicated Server

A Docker-based Arma Reforger dedicated server stack with a web UI for scenario management.

## Stack

| Service | Description | Port |
|---|---|---|
| `scenario-manager` | Flask web UI — switch scenarios, upload configs, check mods | 5000 |
| `portainer` | Container inspection and log viewer | 9000 |
| `ds-*` | Arma Reforger DS — one container per scenario, started on demand | 2001/udp, 17777/udp, 19999/tcp |

## Quick Start

### 1. Prerequisites

- Docker Desktop (Windows) or Docker Engine + Compose (Linux)
- Steam account that owns Arma Reforger
- Arma Reforger scenario configs (`.json` files)

### 2. Configure

```bash
cd docker/
cp .env.example .env
# Edit .env: set USERNAME, SECRET_KEY, PUBLIC_IP
# Add PASSWRD and STEAM_GUARD_CODE for first run only
```

### 3. Start the management stack

```bash
docker compose up -d portainer scenario-manager
```

### 4. First-time DS setup

Each DS service uses a Docker Compose profile matching its scenario name.
Start a server for the first time — it will download the DS binary (~2 GB) and
all mods from the Bohemia Interactive CDN:

```bash
docker compose --profile ipc-everon up ds-ipc-everon
```

After the DS binary is downloaded to the `arma_serverdata` volume, remove
`PASSWRD` from `.env` — subsequent restarts skip SteamCMD entirely.

### 5. Switch scenarios via web UI

Open `http://localhost:5000`, log in, and click **Activate** on any scenario card.
The current DS container is stopped and the new one started automatically.

Pre-create containers that have never been started so the UI can manage them:

```bash
docker compose --profile ipc-ruha up --no-start
docker compose --profile ipc-kunar up --no-start
# etc.
```

### 6. Add a new scenario

1. Build your scenario config with `scripts/build_testing_scenarios.py`
2. Upload the `.json` via the scenario-manager web UI
3. Add a new service to `docker/docker-compose.yml` following the existing pattern
4. Pre-create the container: `docker compose --profile <name> up --no-start`

## Repository Structure

```
docker/             Docker stack — Dockerfile, compose, entrypoint
scenario-manager/   Flask web UI — scenario switching, mod checking
scripts/            Build and validation tools for scenario configs
```

## scripts/

| Script | Purpose |
|---|---|
| `build_testing_scenarios.py` | Generate server.json configs from backbone |
| `extract_backbone.py` | Extract shared config from a reference scenario |
| `check_*_deps.py` | Validate mod dependencies per scenario type |
| `check_mod_sizes.py` | Report mod download sizes |
| `stage_console.py` | Stage configs for console (cross-platform) players |
| `strip_ipc.py` | Strip IPC-specific mods for vanilla-compatible configs |

## CPU Affinity (Windows / Docker Desktop)

All DS services are pinned to CCD0 of a Ryzen 9 7950X via:

```yaml
cpuset: "0-7,16-23"
cpu_shares: 2048
```

Adjust `cpuset` to match your CPU topology (`lscpu --extended` inside WSL2).

## Credits

Inspired by [soda3x/ArmaReforgerServerTool](https://github.com/soda3x/ArmaReforgerServerTool),
a Windows GUI for managing Arma Reforger dedicated servers. This project takes a
different approach — container-based, platform-agnostic, and web UI driven.
