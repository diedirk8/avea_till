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