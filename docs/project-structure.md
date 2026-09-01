# Project Structure

## Purpose

This document describes the structure of the **Avea Dashboard** module and explains where new functionality should be added.

The module is an umbrella application. Each major feature (Till, Customer Credit, Loyalty, etc.) lives in its own logical area so the project scales cleanly.

---

# Repository Structure

```
avea_dashboard/                    ← repository root
│
├── docs/
├── README.md
├── .gitignore
└── avea_dashboard/                ← Odoo addon (technical name: avea_dashboard)
    ├── __init__.py
    ├── __manifest__.py
    ├── migrations/
    ├── models/
    │   ├── till/                  ← Till / cash ledger feature
    │   ├── credit/                ← Customer Credit feature
    │   ├── operations/            ← Account balances, expenses, transfers
    │   └── stock/                 ← Receive Stock and Return Stock
    ├── security/
    │   ├── till/
    │   ├── credit/
    │   ├── operations/
    │   └── stock/
    ├── static/
    │   └── src/
    │       ├── scss/              ← shared + feature stylesheets
    │       ├── till/
    │       └── credit/
    └── views/
        ├── menu.xml               ← root application menu
        ├── till/
        └── credit/
```

---

# Feature-Oriented Architecture

Each feature area owns its models, views, security, and static assets.

```
Feature (e.g. credit/)
├── models/          Business logic
├── views/           Menus, forms, lists, actions
├── security/        Access rights and record rules
├── wizards/         (future) Transient workflows
├── reports/         (future) Report templates and logic
└── services/        (future) Shared non-model helpers
```

### Current features

| Feature | Model namespace | Description |
|---------|-----------------|-------------|
| Till | `avea.till.*` | Session Dashboard, Cash Ledger, till movements |
| Customer Credit | `avea.credit.*` | Store credit foundation (placeholders) |
| Operations | `avea.operational.*` / `avea.money.*` | Account balances, operational expense, money transfer |
| Stock | `avea.stock.*` | Receive Stock and Return Stock |

### Adding a new feature

1. Create `models/<feature>/`, `views/<feature>/`, and `security/<feature>/`.
2. Register imports in the feature and root `__init__.py` files.
3. Add data files to `__manifest__.py` (security before views, views before menus).
4. Add a menu section under `views/<feature>/<feature>_menu.xml`.
5. Use a dedicated model namespace: `avea.<feature>.*`.

---

# Folder Responsibilities

## models/

Business logic only. No UI code.

Organised by feature subdirectory. Shared cross-feature code may live in `models/common/` if needed later.

## views/

Presentation only (XML). Organised by feature subdirectory.

- `views/menu.xml` — root application menu
- `views/<feature>/<feature>_menu.xml` — feature navigation

## security/

Access rights and record rules, split by feature. Never hardcode security in Python.

## static/

Icons, SCSS, and JavaScript. Feature-specific assets live under `static/src/<feature>/`.

## migrations/

Database migration scripts for module upgrades (e.g. module renames).

## docs/

Project documentation and architecture decisions.

---

# Naming Conventions

| Item | Pattern | Example |
|------|---------|---------|
| Module | `avea_dashboard` | — |
| Feature models | `avea.<feature>.<model>` | `avea.till.movement` |
| XML record IDs | `<feature>_avea_*` or `view_avea_<feature>_*` | `view_avea_credit_ledger_form` |
| Menu IDs | `menu_avea_<feature>_*` | `menu_avea_credit_ledger` |
| Shared UI classes | `o_avea_workspace*` | Cash Ledger workspace shell |

Model namespaces describe **what the code does**, not the module name. The Till feature keeps `avea.till.*` even though the application is called Avea Dashboard.

---

# Design Philosophy

Business logic belongs in Python.

Presentation belongs in XML.

Configuration belongs in data files.

Documentation belongs in the docs folder.

Extend Odoo rather than replace it. Reuse existing models wherever possible.
