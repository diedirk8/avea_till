#!/usr/bin/env bash
# Deploy develop to Pets Empire PRODUCTION (petsempire). Requires explicit intent.
set -euo pipefail

SSH_HOST="${PETSEMPIRE_SSH_HOST:-178.105.141.142}"
SSH_USER="${PETSEMPIRE_SSH_USER:-root}"
GIT_BRANCH="${AVEA_GIT_BRANCH:-develop}"
DEV_REPO="/opt/odoo/dev/avea_till"
DEV_AVEA_ADDON="${DEV_REPO}/avea_dashboard"
PROD_CONTAINER="odoo-odoo-1"
PROD_DB="petsempire"
MODULE="avea_till"

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

bash "$(dirname "$0")/avea_verify_product_shell_layout.sh"

echo "==> Pull ${GIT_BRANCH} (prod container mounts ${DEV_AVEA_ADDON} -> /mnt/custom-addons/avea_till)"
"${SSH[@]}" "set -e
  cd ${DEV_REPO}
  git fetch origin ${GIT_BRANCH}
  git checkout ${GIT_BRANCH}
  git pull origin ${GIT_BRANCH}
  echo \"commit: \$(git rev-parse --short HEAD)\"
  grep '\"version\"' ${DEV_AVEA_ADDON}/__manifest__.py | head -1
  docker exec ${PROD_CONTAINER} python3 -c \"import ast; ast.literal_eval(open('/mnt/custom-addons/avea_till/__manifest__.py').read()); print('manifest parse ok')\"
"

echo "==> Upgrade ${MODULE} on ${PROD_DB}"
"${SSH[@]}" "set -e
  docker exec ${PROD_CONTAINER} odoo -u ${MODULE} -d ${PROD_DB} --stop-after-init --log-level=warn
"

echo "==> Rebuild web.assets_web on DEV, then copy blobs to PROD (prod URLs unchanged)"
"${SSH[@]}" "bash ${DEV_REPO}/scripts/avea_regenerate_web_assets.sh odoo-dev petsempire_dev"
AVEA_SYNC_PROD_ADDON_CODE=0 bash "$(dirname "$0")/avea_sync_prod_assets_from_dev.sh"
bash "$(dirname "$0")/avea_verify_web_assets_sync.sh"
bash "$(dirname "$0")/avea_verify_product_shell_layout.sh" --compiled

echo "==> Installed version"
"${SSH[@]}" "docker exec odoo-db-1 psql -U odoo -d ${PROD_DB} -t -c \"SELECT state, latest_version FROM ir_module_module WHERE name='${MODULE}';\""
echo "==> Done (PRODUCTION)."
