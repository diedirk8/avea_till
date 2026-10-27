#!/usr/bin/env bash
# Copy compiled web.assets_web JS/CSS from DEV filestore into PROD filestore
# at PROD's current attachment paths (no module upgrade, no ir_attachment updates).
set -euo pipefail

SSH_HOST="${PETSEMPIRE_SSH_HOST:-178.105.141.142}"
SSH_USER="${PETSEMPIRE_SSH_USER:-root}"
PROD_CONTAINER="${PROD_CONTAINER:-odoo-odoo-1}"
DEV_CONTAINER="${DEV_CONTAINER:-odoo-dev}"
PROD_DB="${PROD_DB:-petsempire}"
DEV_DB="${DEV_DB:-petsempire_dev}"

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

echo "==> Sync addon files (git -> prod addons, same tree dev container uses)"
"${SSH[@]}" "set -e
  rsync -a --delete /opt/odoo/dev/avea_till/avea_dashboard/ /opt/odoo/addons/avea_till/
  echo \"commit: \$(cd /opt/odoo/dev/avea_till && git rev-parse --short HEAD)\"
"

echo "==> Copy latest web.assets_web.min.js/.css blobs DEV -> PROD (prod URLs unchanged)"
"${SSH[@]}" "PROD_CONTAINER=${PROD_CONTAINER} DEV_CONTAINER=${DEV_CONTAINER} PROD_DB=${PROD_DB} DEV_DB=${DEV_DB} bash -s" <<'EOF'
set -euo pipefail
lookup() {
  local db=$1 ext=$2
  docker exec odoo-db-1 psql -U odoo -d "$db" -t -A -c \
    "SELECT store_fname FROM ir_attachment WHERE url LIKE '%/web.assets_web.min.${ext}' ORDER BY id DESC LIMIT 1;"
}
DEV_JS=$(lookup "$DEV_DB" js)
DEV_CSS=$(lookup "$DEV_DB" css)
PROD_JS=$(lookup "$PROD_DB" js)
PROD_CSS=$(lookup "$PROD_DB" css)
echo "dev js  $DEV_JS"
echo "dev css $DEV_CSS"
echo "prod js  $PROD_JS"
echo "prod css $PROD_CSS"
test -n "$DEV_JS" && test -n "$DEV_CSS" && test -n "$PROD_JS" && test -n "$PROD_CSS"
DEV_JS_PATH=/var/lib/odoo/.local/share/Odoo/filestore/${DEV_DB}/$DEV_JS
DEV_CSS_PATH=/var/lib/odoo/.local/share/Odoo/filestore/${DEV_DB}/$DEV_CSS
PROD_JS_PATH=/var/lib/odoo/.local/share/Odoo/filestore/${PROD_DB}/$PROD_JS
PROD_CSS_PATH=/var/lib/odoo/.local/share/Odoo/filestore/${PROD_DB}/$PROD_CSS
docker exec "$DEV_CONTAINER" test -f "$DEV_JS_PATH"
docker exec "$DEV_CONTAINER" test -f "$DEV_CSS_PATH"
docker exec "$PROD_CONTAINER" test -f "$PROD_JS_PATH"
docker exec "$PROD_CONTAINER" test -f "$PROD_CSS_PATH"
docker cp "$DEV_CONTAINER:$DEV_JS_PATH" /tmp/avea_dev_web.js
docker cp "$DEV_CONTAINER:$DEV_CSS_PATH" /tmp/avea_dev_web.css
docker cp /tmp/avea_dev_web.js "$PROD_CONTAINER:$PROD_JS_PATH"
docker cp /tmp/avea_dev_web.css "$PROD_CONTAINER:$PROD_CSS_PATH"
rm -f /tmp/avea_dev_web.js /tmp/avea_dev_web.css
echo -n "prod css o_avea_customer_list count: "
docker exec "$PROD_CONTAINER" grep -c o_avea_customer_list "$PROD_CSS_PATH" || true
docker restart "$PROD_CONTAINER"
EOF

echo "==> Done. Hard-refresh production (Ctrl+Shift+R) on Customers and Stock."
