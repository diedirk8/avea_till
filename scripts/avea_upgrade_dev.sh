#!/usr/bin/env bash
# Upgrade avea_till on Pets Empire DEV (petsempire_dev). Never touches production.
set -euo pipefail

SSH_HOST="${PETSEMPIRE_SSH_HOST:-178.105.141.142}"
SSH_USER="${PETSEMPIRE_SSH_USER:-root}"
GIT_BRANCH="${AVEA_GIT_BRANCH:-develop}"
DEV_REPO="/opt/odoo/dev/avea_till"
DEV_CONTAINER="odoo-dev"
DEV_DB="petsempire_dev"
MODULE="avea_till"

if [[ -z "${PETSEMPIRE_SSH_PRIVATE_KEY:-}" ]]; then
  echo "error: PETSEMPIRE_SSH_PRIVATE_KEY is not set (add it as a Cloud Agent runtime secret)." >&2
  exit 1
fi

KEYFILE="$(mktemp)"
trap 'rm -f "$KEYFILE"' EXIT
printf '%s\n' "$PETSEMPIRE_SSH_PRIVATE_KEY" > "$KEYFILE"
chmod 600 "$KEYFILE"

SSH=(ssh -i "$KEYFILE" -o BatchMode=yes -o ConnectTimeout=20 -o StrictHostKeyChecking=accept-new
  "${SSH_USER}@${SSH_HOST}")

echo "==> Pull ${GIT_BRANCH} on ${SSH_HOST}"
"${SSH[@]}" "set -e
  cd ${DEV_REPO}
  git fetch origin ${GIT_BRANCH}
  git checkout ${GIT_BRANCH}
  git pull origin ${GIT_BRANCH}
  echo \"commit: \$(git rev-parse --short HEAD)\"
  grep '\"version\"' avea_dashboard/__manifest__.py | head -1
"

echo "==> Upgrade ${MODULE} on ${DEV_DB}"
"${SSH[@]}" "set -e
  docker exec ${DEV_CONTAINER} odoo -u ${MODULE} -d ${DEV_DB} --stop-after-init --log-level=warn
  bash ${DEV_REPO}/scripts/avea_regenerate_web_assets.sh ${DEV_CONTAINER} ${DEV_DB}
  docker restart ${DEV_CONTAINER}
"

echo "==> Installed version"
"${SSH[@]}" "docker exec odoo-db-1 psql -U odoo -d ${DEV_DB} -t -c \"SELECT state, latest_version FROM ir_module_module WHERE name='${MODULE}';\""
echo "==> Done (DEV only)."
