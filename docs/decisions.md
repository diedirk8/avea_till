# Architecture Decisions

This document records important design decisions made during development.

---

# ADR-001

## Separate Development Environment

Status

Accepted

Reason

Development should never interrupt the live business.

Decision

Create a dedicated development Odoo instance on port 8070 using a cloned production database.

---

# ADR-002

## Dedicated Till Movement Model

Status

Accepted

Reason

Manual cash movements do not naturally belong to POS payments.

Decision

Create a dedicated model:

```
avea.till.movement
```

The cash ledger will combine POS data with manual movements.

---

# ADR-003

## Reuse Existing Odoo Models

Status

Accepted

Reason

Duplicating accounting information creates maintenance problems.

Decision

Reference existing Odoo models whenever possible.

Only create new models when genuinely required.

---

# ADR-004

## Module Rename: avea_till → avea_dashboard

Status

Accepted

Reason

The product has evolved from a till-only module into a broader retail dashboard. Customer Credit is the first of many planned features. The technical module name should reflect the product identity.

Decision

Rename the Odoo module from `avea_till` to `avea_dashboard`.

Keep feature-scoped model namespaces unchanged:

- `avea.till.*` for cash drawer / POS till operations
- `avea.credit.*` for customer credit

Rationale

- Model names are independent of the module name in Odoo.
- Renaming `avea.till.movement` would require migrating production ledger data in the `avea_till_movement` table.
- Feature namespaces (`avea.till.*`, `avea.credit.*`) accurately describe domain concepts.
- A migration script updates `ir_module_module` and `ir_model_data` on upgrade.

Structure

Organise code by feature (`models/till/`, `models/credit/`, etc.) within the single `avea_dashboard` application module.