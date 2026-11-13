# Cloud Agent instructions (avea_till / avea_dashboard)

## Auto-upgrade DEV after module changes

Whenever you change anything under `avea_dashboard/` (Python, XML, JS, SCSS, migrations, manifest version):

1. Commit and push to `develop` (or the branch you are working on).
2. **Always** run upgrades before you finish the task (do not stop at commit/push only):

   ```bash
   bash scripts/avea_upgrade_dev.sh
   bash scripts/avea_upgrade_prod.sh
   ```

3. Report the git commit, manifest version, and `ir_module_module.latest_version` from the script output for each environment.

**Layout / CSS:** After `avea_upgrade_prod.sh`, prod uses dev’s compiled `web.assets_web` JS/CSS blobs. Do **not** rsync prod addon code without `-u avea_till` on prod (leaves module `to upgrade` and breaks OWL view registration). Always run **both** upgrade scripts when shipping UI changes.

### Rules

- **DEV only** by default: database `petsempire_dev`, container `odoo-dev`, code at `/opt/odoo/dev/avea_till`.
- **Production** after every deployable change: `bash scripts/avea_upgrade_prod.sh` (rsync dev checkout → `/opt/odoo/addons/avea_till`, `-u avea_till` on `petsempire`, then sync compiled web assets from dev).
- Requires runtime secret `PETSEMPIRE_SSH_PRIVATE_KEY` (SSH user defaults to `root`; override with `PETSEMPIRE_SSH_USER` if needed).
- After upgrade, remind the user to hard-refresh the browser on dev (`http://178.105.141.142:8070`) if they test UI assets.
