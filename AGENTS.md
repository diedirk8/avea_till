# Cloud Agent instructions (avea_till / avea_dashboard)

## Auto-upgrade DEV after module changes

Whenever you change anything under `avea_dashboard/` (Python, XML, JS, SCSS, migrations, manifest version):

1. Commit and push to `develop` (or the branch you are working on).
2. **Always** run the DEV upgrade before you finish the task:

   ```bash
   bash scripts/avea_upgrade_dev.sh
   ```

3. Report the git commit, manifest version, and `ir_module_module.latest_version` from the script output.

### Rules

- **DEV only** by default: database `petsempire_dev`, container `odoo-dev`, code at `/opt/odoo/dev/avea_till`.
- **Do not upgrade production** (`petsempire`, `odoo-odoo-1`) unless the user explicitly asks in that conversation.
- Requires runtime secret `PETSEMPIRE_SSH_PRIVATE_KEY` (SSH user defaults to `root`; override with `PETSEMPIRE_SSH_USER` if needed).
- After upgrade, remind the user to hard-refresh the browser on dev (`http://178.105.141.142:8070`) if they test UI assets.
