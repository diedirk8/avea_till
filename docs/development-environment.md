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
| URL | http://178.105.141.142:8069 |
| Database | petsempire |
| Purpose | Live business |

---

## Development

| Setting | Value |
|---------|------|
| URL | http://178.105.141.142:8070 |
| Database | petsempire_dev |
| Purpose | Development and testing |

---

## Repository Structure

```
/opt/odoo
├── addons
├── custom_addons
├── dev
│   └── avea_till
└── config
```

---

## Development Workflow

1. Develop in VS Code using Remote SSH.
2. Test changes on the Development instance.
3. Commit changes to Git.
4. Push to the `develop` branch.
5. Deploy to Production only after testing.

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