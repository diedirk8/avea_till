# Deployment

## Branch Strategy

Development takes place on the `develop` branch.

Production is updated only after successful testing.

---

# Deployment Process

1. Commit changes.
2. Push to GitHub.
3. Pull latest changes on the production server.
4. Update the module.
5. Verify functionality.
6. Resume normal operation.

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