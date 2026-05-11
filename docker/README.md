# Arma Reforger DS — Docker Deployment

A containerized deployment of the Arma Reforger Dedicated Server managed via
Portainer and the Scenario Manager web UI. Each scenario config runs in its own
container sharing a single mod volume, so swapping maps is a one-click operation.

## Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (Windows/Linux/Mac)
- Enable "Start Docker Desktop when you sign in" for auto-start on boot
- A Steam account (for mod downloads — not needed to play simultaneously)

## Quick Start

### 1. Configure credentials

```bash
cp .env.example .env
# Edit .env with your Steam credentials, SECRET_KEY, and PUBLIC_IP
```

### 2. Start management services

```bash
docker compose up -d portainer scenario-manager
```

- **Scenario Manager**: http://localhost:5000
- **Portainer**: http://localhost:9000

### 3. First run — download DS + mods (takes 30–60 min)

```bash
docker compose --profile ipc-everon up ds-ipc-everon
```

Watch the logs — SteamCMD will download the DS binary anonymously, then download
all workshop mods using your Steam credentials. Subsequent starts skip the download.

### 4. Switch scenarios

Use the Scenario Manager UI at http://localhost:5000 — click **Activate** on any
scenario card to stop the current server and start the selected one.

Or via Portainer at http://localhost:9000 for manual container management.

## Architecture

```
docker-compose.yml
  portainer           — admin UI at :9000 (always running, auto-restart)
  scenario-manager    — scenario switching UI at :5000 (always running, auto-restart)
  ds-ipc-everon  ┐
  ds-ipc-ruha    │   IPC PVE branch (one at a time)
  ds-ipc-kunar   │
  ds-ipc-novka   ┘
  ds-coe2-arland ┐
  ds-coe2-cain   │   COE2 Random Patrols branch (one at a time)
  ds-coe2-eden   ┘

Shared volumes:
  arma_game      — DS binary (downloaded once, ~2 GB)
  arma_workshop  — all workshop mods (downloaded once, ~20–60 GB depending on list)
  arma_saves_*   — per-scenario save data (persists across container restarts)

Ports (only one DS runs at a time):
  2001/udp   — game
  17777/udp  — A2S query (server browser)
  19999/tcp  — RCON
```

## Adding a New Scenario

1. Add a new config to `D:\Longbow\scenarios\Testing\` using `build_testing_scenarios.py`
2. Add a new service to `docker-compose.yml` following the existing pattern
3. `docker compose build ds-<new-scenario>`
4. Start it via Scenario Manager or Portainer

## Fallback to Longbow

Stop all DS containers, then launch `D:\Longbow\Longbow.exe` as normal.
Longbow manages the Windows-native DS process independently of Docker.

## Restart Behaviour

| Service | Policy | Behaviour |
|---|---|---|
| portainer | unless-stopped | Starts at boot, recovers from crashes |
| scenario-manager | unless-stopped | Starts at boot, recovers from crashes |
| ds-* | on-failure | Recovers from crashes, respects manual stops |
