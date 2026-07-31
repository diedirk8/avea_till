# Development Environment

## Overview

This project uses separate Production and Development Odoo instances on the same server.

The purpose is to allow safe module development without interrupting the live business.

---

## Server

| Item | Value |
|------|------|
| Operating System | Ubuntu |
| Docker | Docker Compose |
| Odoo Version | 19 Enterprise |
| PostgreSQL | Version 16 |

---

## Production

| Setting | Value |
|---------|------|
| URL | http://178.105.141.142:8069 (also http://pos.petsempire.co.za) |
| Database | petsempire |
| Purpose | Live business |
| `web.base.url` | `http://pos.petsempire.co.za` |
| `report.url` | *(unset — uses `web.base.url`)* |

---

## Development

| Setting | Value |
|---------|------|
| URL | http://178.105.141.142:8070 |
| Database | petsempire_dev |
| Purpose | Development and testing |
| Container | `odoo-dev` (port 8070 → internal 8069) |

### PDF report performance (important)

PDF generation in Docker relies on **wkhtmltopdf** fetching CSS and other assets over HTTP from the URL returned by `_get_report_url()`. By default this falls back to `web.base.url`.

On the development instance, `web.base.url` is the **external** host address (`http://178.105.141.142:8070`). The `odoo-dev` container **cannot reach its own external URL** (Docker hairpin / routing). wkhtmltopdf then hits network timeouts on every asset request, causing multi-minute PDF delays and log messages such as:

```
wkhtmltopdf: Exit with code 1 due to network error: TimeoutError
```

Production is unaffected because `web.base.url` is `http://pos.petsempire.co.za`, which the production container can reach normally.

**Required development setting** — set the `report.url` system parameter so wkhtmltopdf uses the in-container Odoo URL:

| Parameter | Development value | Notes |
|-----------|-------------------|-------|
| `web.base.url` | `http://178.105.141.142:8070` | Keep as the browser-facing URL |
| `report.url` | `http://127.0.0.1:8069` | Internal URL for wkhtmltopdf asset loading |

Set once per development database (Settings → Technical → System Parameters, or run the standard setup script):

```bash
/opt/odoo/config/init-dev-report-url.sh
```

Or via Odoo shell:

```python
env['ir.config_parameter'].sudo().set_param('report.url', 'http://127.0.0.1:8069')
```

Run `init-dev-report-url.sh` after creating or restoring a development database.

After this, PDF generation should complete in a few seconds, matching production behaviour. Excel exports are unaffected (they do not use wkhtmltopdf).

**Verified connectivity from inside `odoo-dev`:**

| URL | Result |
|-----|--------|
| `http://178.105.141.142:8070` | Timeout (unreachable from container) |
| `http://127.0.0.1:8069` | OK (~instant) |
| `http://localhost:8069` | OK (~instant) |

Both containers use **wkhtmltopdf 0.12.6.1 (with patched qt)** — the binary is not the difference.

---

## Repository Structure

```
/opt/odoo
├── addons
├── custom_addons
├── dev
│   └── avea_dashboard
└── config
```

---

## Development Workflow

1. Develop in VS Code using Remote SSH.
2. Run `/opt/odoo/config/init-dev-report-url.sh` on new or restored dev databases.
3. Test changes on the Development instance.
4. Commit changes to Git.
5. Push to the `develop` branch.
6. Deploy to Production only after testing.

---

## VS Code Extensions

- Python
- Pylance
- XML (Red Hat)
- Error Lens
- Material Icon Theme

---

## Notes

- Never test unfinished features on the Production instance.
- Always verify new functionality on `petsempire_dev` first.