#!/usr/bin/env bash
# Rebuild web.assets_web JS/CSS attachments after an avea_till upgrade (new bundle hashes).
set -euo pipefail

CONTAINER="${1:?usage: avea_regenerate_web_assets.sh <container> <database>}"
DATABASE="${2:?usage: avea_regenerate_web_assets.sh <container> <database>}"

docker exec -i "$CONTAINER" odoo shell -d "$DATABASE" --no-http --log-level=error <<'PY'
bundle = env["ir.qweb"]._get_asset_bundle("web.assets_web", css=True, js=True)
js_att = bundle.js()
css_att = bundle.css()
env.cr.commit()
print(f"JS  {js_att.url}  id={js_att.id}")
print(f"CSS {css_att.url}  id={css_att.id}")
PY
