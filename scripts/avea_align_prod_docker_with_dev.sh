#!/usr/bin/env bash
# Align production Odoo addon mounts with dev (live git checkout for avea_till).
# Edits /opt/odoo/docker-compose.yml and odoo.conf on the server, then recreates prod.
set -euo pipefail

SSH_HOST="${PETSEMPIRE_SSH_HOST:-178.105.141.142}"
SSH_USER="${PETSEMPIRE_SSH_USER:-root}"

if [[ -z "${PETSEMPIRE_SSH_PRIVATE_KEY:-}" ]]; then
  echo "error: PETSEMPIRE_SSH_PRIVATE_KEY is not set." >&2
  exit 1
fi

KEYFILE="$(mktemp)"
trap 'rm -f "$KEYFILE"' EXIT
printf '%s\n' "$PETSEMPIRE_SSH_PRIVATE_KEY" > "$KEYFILE"
chmod 600 "$KEYFILE"

ssh -i "$KEYFILE" -o BatchMode=yes -o ConnectTimeout=20 -o StrictHostKeyChecking=accept-new \
  "${SSH_USER}@${SSH_HOST}" 'bash -s' <<'EOF'
set -euo pipefail
COMPOSE=/opt/odoo/docker-compose.yml
CONF=/opt/odoo/config/odoo.conf
MARKER="avea_till live git (aligned with dev)"

if ! grep -q "/mnt/custom-addons/avea_till" "$COMPOSE" 2>/dev/null; then
  python3 - <<'PY'
from pathlib import Path
path = Path("/opt/odoo/docker-compose.yml")
text = path.read_text()
needle = "      - ./addons:/mnt/extra-addons\n"
insert = (
    "      - ./addons:/mnt/extra-addons\n"
    "      - ./custom_addons:/mnt/custom-addons\n"
    "      - ./dev/avea_till/avea_dashboard:/mnt/custom-addons/avea_till\n"
)
if needle not in text:
    raise SystemExit("unexpected docker-compose.yml layout")
path.write_text(text.replace(needle, insert, 1))
print("updated docker-compose.yml volumes")
PY
fi

python3 - <<'PY'
from pathlib import Path
path = Path("/opt/odoo/config/odoo.conf")
lines = path.read_text().splitlines()
out = []
for line in lines:
    if line.startswith("addons_path ="):
        out.append("addons_path = /mnt/custom-addons,/mnt/extra-addons,/usr/lib/python3/dist-packages/odoo/addons")
    else:
        out.append(line)
path.write_text("\n".join(out) + "\n")
print("updated odoo.conf addons_path")
PY

cd /opt/odoo
docker compose up -d odoo
docker exec odoo-odoo-1 md5sum /mnt/custom-addons/avea_till/static/src/scss/_avea_catalogue_list_pane.scss
echo "$MARKER"
EOF
