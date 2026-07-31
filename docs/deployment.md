# Deployment

## Branch Strategy

Development takes place on the `develop` branch.

Production is updated only after successful testing.

---

# Deployment Process

1. Commit changes.
2. Push to GitHub.
3. Pull latest changes on the production server.
4. Ensure the addon directory is named `avea_dashboard` (replacing the old `avea_till` folder if upgrading).
5. Update the module: `-u avea_dashboard`
6. Verify functionality.
7. Resume normal operation.

---

# Module Rename (19.0.2.0.0)

When upgrading from `avea_till` to `avea_dashboard`:

1. Stop Odoo.
2. Replace `/opt/odoo/addons/avea_till` with the new `avea_dashboard` directory.
3. Confirm `addons_path` includes the parent directory.
4. Start Odoo and upgrade: `-u avea_dashboard -d <database>`

The migration script handles database record renames automatically. Test on `petsempire_dev` before production.

---

# Before Deployment

Confirm:

- No Python errors.
- No XML errors.
- Module upgrades successfully.
- Development testing completed.

---

# Rollback

If a deployment fails:

1. Restore the previous Git commit.
2. Upgrade the module.
3. Verify production functionality.

---

# Principle

Production stability is more important than releasing new features.

Every deployment should be reversible.