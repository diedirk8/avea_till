#!/usr/bin/env bash
# Deploy develop to Pets Empire PRODUCTION (petsempire). Requires explicit intent.
set -euo pipefail

SSH_HOST="${PETSEMPIRE_SSH_HOST:-178.105.141.142}"
SSH_USER="${PETSEMPIRE_SSH_USER:-root}"
GIT_BRANCH="${AVEA_GIT_BRANCH:-develop}"
DEV_REPO="/opt/odoo/dev/avea_till"
PROD_ADDON="/opt/odoo/addons/avea_till"
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

echo "==> Pull ${GIT_BRANCH} and rsync to ${PROD_ADDON}"
"${SSH[@]}" "set -e
  cd ${DEV_REPO}
  git fetch origin ${GIT_BRANCH}
  git checkout ${GIT_BRANCH}
  git pull origin ${GIT_BRANCH}
  echo \"commit: \$(git rev-parse --short HEAD)\"
  rsync -a --delete ${DEV_REPO}/avea_dashboard/ ${PROD_ADDON}/
  grep '\"version\"' ${PROD_ADDON}/__manifest__.py | head -1
"

echo "==> Upgrade ${MODULE} on ${PROD_DB}"
"${SSH[@]}" "set -e
  docker exec ${PROD_CONTAINER} odoo -u ${MODULE} -d ${PROD_DB} --stop-after-init --log-level=warn
  bash ${DEV_REPO}/scripts/avea_regenerate_web_assets.sh ${PROD_CONTAINER} ${PROD_DB}
  docker restart ${PROD_CONTAINER}
"

echo "==> Installed version"
"${SSH[@]}" "docker exec odoo-db-1 psql -U odoo -d ${PROD_DB} -t -c \"SELECT state, latest_version FROM ir_module_module WHERE name='${MODULE}';\""
echo "==> Done (PRODUCTION)."
