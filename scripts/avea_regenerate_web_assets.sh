#!/usr/bin/env bash
# Rebuild web.assets_web JS/CSS attachments after an avea_till upgrade (new bundle hashes).
set -euo pipefail

CONTAINER="${1:?usage: avea_regenerate_web_assets.sh <container> <database>}"
DATABASE="${2:?usage: avea_regenerate_web_assets.sh <container> <database>}"

REGEN_LOG=$(mktemp)
trap 'rm -f "$REGEN_LOG"' EXIT
docker exec -i "$CONTAINER" odoo shell -d "$DATABASE" --no-http --log-level=error <<'PY' 2>"$REGEN_LOG" | tee -a "$REGEN_LOG"
bundle = env["ir.qweb"]._get_asset_bundle("web.assets_web", css=True, js=True)
js_att = bundle.js()
css_att = bundle.css()
env.cr.commit()
print(f"JS  {js_att.url}  id={js_att.id}")
print(f"CSS {css_att.url}  id={css_att.id}")
print(f"CSS_STORE {css_att.store_fname}")
PY
CSS_PATH=$(grep '^CSS_STORE ' "$REGEN_LOG" | tail -1 | cut -d' ' -f2-)
CSS_FILE="/var/lib/odoo/.local/share/Odoo/filestore/${DATABASE}/${CSS_PATH}"
test -n "$CSS_PATH"
if docker exec "$CONTAINER" grep -q "Internal Error" "$CSS_FILE"; then
  echo "error: web.assets_web.min.css contains Sass Internal Error (fix SCSS before deploy)" >&2
  docker exec "$CONTAINER" grep -o "Internal Error[^\\\\]*" "$CSS_FILE" | head -1 >&2 || true
  exit 1
fi
echo "ok: web.assets_web.min.css compiled cleanly"
