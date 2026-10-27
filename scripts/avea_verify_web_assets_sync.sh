#!/usr/bin/env bash
# Fail if DEV and PROD web.assets_web min CSS blobs differ (layout drift).
set -euo pipefail

SSH_HOST="${PETSEMPIRE_SSH_HOST:-178.105.141.142}"
SSH_USER="${PETSEMPIRE_SSH_USER:-root}"
DEV_CONTAINER="${DEV_CONTAINER:-odoo-dev}"
PROD_CONTAINER="${PROD_CONTAINER:-odoo-odoo-1}"
DEV_DB="${DEV_DB:-petsempire_dev}"
PROD_DB="${PROD_DB:-petsempire}"

if [[ -z "${PETSEMPIRE_SSH_PRIVATE_KEY:-}" ]]; then
  echo "error: PETSEMPIRE_SSH_PRIVATE_KEY is not set." >&2
  exit 1
fi

KEYFILE="$(mktemp)"
trap 'rm -f "$KEYFILE"' EXIT
printf '%s\n' "$PETSEMPIRE_SSH_PRIVATE_KEY" > "$KEYFILE"
chmod 600 "$KEYFILE"

SSH=(ssh -i "$KEYFILE" -o BatchMode=yes -o ConnectTimeout=20 -o StrictHostKeyChecking=accept-new
  "${SSH_USER}@${SSH_HOST}")

"${SSH[@]}" "DEV_CONTAINER=${DEV_CONTAINER} PROD_CONTAINER=${PROD_CONTAINER} DEV_DB=${DEV_DB} PROD_DB=${PROD_DB} bash -s" <<'EOF'
set -euo pipefail
lookup() {
  local db=$1 ext=$2
  docker exec odoo-db-1 psql -U odoo -d "$db" -t -A -c \
    "SELECT store_fname FROM ir_attachment WHERE url LIKE '%/web.assets_web.min.${ext}' ORDER BY id DESC LIMIT 1;"
}
DEV_CSS=$(lookup "$DEV_DB" css)
PROD_CSS=$(lookup "$PROD_DB" css)
DEV_PATH=/var/lib/odoo/.local/share/Odoo/filestore/${DEV_DB}/$DEV_CSS
PROD_PATH=/var/lib/odoo/.local/share/Odoo/filestore/${PROD_DB}/$PROD_CSS
DEV_MD5=$(docker exec "$DEV_CONTAINER" md5sum "$DEV_PATH" | awk '{print $1}')
PROD_MD5=$(docker exec "$PROD_CONTAINER" md5sum "$PROD_PATH" | awk '{print $1}')
echo "dev css  $DEV_CSS  md5=$DEV_MD5"
echo "prod css $PROD_CSS md5=$PROD_MD5"
if [[ "$DEV_MD5" != "$PROD_MD5" ]]; then
  echo "error: DEV and PROD web.assets_web.min.css filestore blobs differ (run avea_sync_prod_assets_from_dev.sh)." >&2
  exit 1
fi
echo "ok: DEV and PROD CSS blobs match."
EOF
