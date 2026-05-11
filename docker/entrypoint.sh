#!/bin/bash
set -e

export HOME=/home/steam

ARMA_APP_ID="1874900"
STEAMCMD="/home/steam/steamcmd/steamcmd.sh"
ADDONS_DIR="${DATA_DIR}/addons"
CONFIG_PATH="/config/server.json"
PATCHED_CONFIG="/tmp/server.json"

echo "=== Arma Reforger DS entrypoint ==="

mkdir -p "${ADDONS_DIR}"

# Build login args — fall back to anonymous if no credentials supplied
if [ -n "${USERNAME}" ]; then
    LOGIN_ARGS="${USERNAME} ${PASSWRD:+${PASSWRD}} ${STEAM_GUARD_CODE:+${STEAM_GUARD_CODE}}"
else
    LOGIN_ARGS="anonymous"
fi

# ── 1. Install / update DS binary ────────────────────────────────────────────
if [ -f "${SERVER_DIR}/ArmaReforgerServer" ]; then
    echo "[INSTALL] DS binary present — skipping."
else
    echo "[INSTALL] DS binary not found — downloading (app ${ARMA_APP_ID})..."
    "${STEAMCMD}" \
        +force_install_dir "${SERVER_DIR}" \
        +login ${LOGIN_ARGS} \
        +app_update "${ARMA_APP_ID}" validate \
        +quit
    echo "[INSTALL] Done."
fi

# ── 2. Patch config: bindAddress must be 0.0.0.0 inside the container ────────
# The host config uses the LAN IP which doesn't exist in the container network.
python3 - <<'EOF'
import json, os, sys
src = os.environ.get("CONFIG_PATH", "/config/server.json")
dst = os.environ.get("PATCHED_CONFIG", "/tmp/server.json")
with open(src) as f:
    cfg = json.load(f)
cfg["bindAddress"] = "0.0.0.0"
with open(dst, "w") as f:
    json.dump(cfg, f, indent=2)
print(f"[CONFIG] bindAddress patched → 0.0.0.0 (written to {dst})")
EOF

# ── 3. Start the dedicated server ─────────────────────────────────────────────
# The DS binary downloads mods from BI's CDN automatically on first start
# using the modId list in server.json. SteamCMD cannot download these —
# they are on BI's workshop infrastructure, not Steam Workshop.
echo "[START] Launching ArmaReforgerServer..."
echo "        Config    : ${PATCHED_CONFIG}"
echo "        Addons    : ${ADDONS_DIR}"
echo "        (First run will download mods from BI CDN — may take 30-60 min)"

cd "${SERVER_DIR}"
exec ./ArmaReforgerServer \
    -config "${PATCHED_CONFIG}" \
    -addonsDir "${ADDONS_DIR}" \
    -maxFPS 60 \
    -logStats 60000
