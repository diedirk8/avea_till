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
DEV_JS=$(lookup "$DEV_DB" js)
PROD_JS=$(lookup "$PROD_DB" js)
DEV_CSS=$(lookup "$DEV_DB" css)
PROD_CSS=$(lookup "$PROD_DB" css)
DEV_JS_PATH=/var/lib/odoo/.local/share/Odoo/filestore/${DEV_DB}/$DEV_JS
PROD_JS_PATH=/var/lib/odoo/.local/share/Odoo/filestore/${PROD_DB}/$PROD_JS
DEV_CSS_PATH=/var/lib/odoo/.local/share/Odoo/filestore/${DEV_DB}/$DEV_CSS
PROD_CSS_PATH=/var/lib/odoo/.local/share/Odoo/filestore/${PROD_DB}/$PROD_CSS
DEV_JS_MD5=$(docker exec "$DEV_CONTAINER" md5sum "$DEV_JS_PATH" | awk '{print $1}')
PROD_JS_MD5=$(docker exec "$PROD_CONTAINER" md5sum "$PROD_JS_PATH" | awk '{print $1}')
DEV_CSS_MD5=$(docker exec "$DEV_CONTAINER" md5sum "$DEV_CSS_PATH" | awk '{print $1}')
PROD_CSS_MD5=$(docker exec "$PROD_CONTAINER" md5sum "$PROD_CSS_PATH" | awk '{print $1}')
echo "dev js   $DEV_JS   md5=$DEV_JS_MD5"
echo "prod js  $PROD_JS  md5=$PROD_JS_MD5"
echo "dev css  $DEV_CSS  md5=$DEV_CSS_MD5"
echo "prod css $PROD_CSS md5=$PROD_CSS_MD5"
if [[ "$DEV_JS_MD5" != "$PROD_JS_MD5" ]]; then
  echo "error: DEV and PROD web.assets_web.min.js blobs differ (run avea_sync_prod_assets_from_dev.sh after dev asset regen)." >&2
  exit 1
fi
if [[ "$DEV_CSS_MD5" != "$PROD_CSS_MD5" ]]; then
  echo "error: DEV and PROD web.assets_web.min.css blobs differ (run avea_sync_prod_assets_from_dev.sh)." >&2
  exit 1
fi
echo "ok: DEV and PROD JS/CSS blobs match."
EOF
