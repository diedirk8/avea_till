# Avea Dashboard

Modular retail dashboard for Odoo 19 POS — till management, customer credit, and future retail features.

## Module

| Item | Value |
|------|-------|
| Technical name | `avea_dashboard` |
| Application name | Avea Dashboard |
| Version | 19.0.2.0.0 |

## Features

- **Till** — Session Dashboard, Cash Ledger, till movements
- **Customer Credit** — foundation (placeholders for future development)

## Upgrade from `avea_till`

If upgrading an existing installation that used the previous module name `avea_till`:

1. Replace the addon directory with `avea_dashboard`.
2. Update your Odoo `addons_path` if needed.
3. Upgrade the module: `-u avea_dashboard`

A migration script renames database records automatically. Model names (`avea.till.*`, `avea.credit.*`) and business data are unchanged.

## Development

See [docs/development-environment.md](docs/development-environment.md) and [docs/project-structure.md](docs/project-structure.md).
