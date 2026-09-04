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

---

# ADR-005

## Receive Stock wraps Odoo Purchase / Stock / Accounting

Status

Accepted

Reason

Pets Empire already receives stock with purchase orders, one-step receipts into WH/Stock, vendor bills on received quantities, periodic AVCO, and 15% tax-excluded purchase VAT.

Decision

Avea Stock (`avea.stock.*`) is a simple workspace over that existing flow:

- Confirm a purchase order for the quantities physically received now
- Validate the incoming receipt
- Create and post the vendor bill from the PO
- Optionally pay with the Operational Expense statement-line pattern

Do not create a parallel stock or accounting ledger. Do not change periodic valuation, AVCO, or Anglo-Saxon settings. Landed costs stay out of Receive Stock so they can be a later Stock feature.

---

# ADR-006

## Correct Payment eligibility is server-authoritative

Status

Accepted

Reason

Re-implementing Correct Payment rules in the POS Ticket Screen caused legitimate open-session Cash/Card/EFT orders (including cash-with-change and some `done` orders) to be hidden while other similar orders remained available. The POS `avea_can_correct_payment` flag was also unreliable when Odoo 19 loads `pos.order` with an empty field list.

Decision

- Keep hard eligibility in `pos.order._avea_payment_correction_block_reason` / `avea_get_payment_correction_options` / `avea_correct_payment_method`.
- Split tender means more than one distinct payment **method** among non-change lines. Cash change lines are not a second tender.
- On correction, consolidate to one exact tender at `amount_total`, remove change/duplicate same-method lines, sync `avea.till.movement`, and post an audit message.
- POS UI may soft-hide obvious cases only; it must not invent stricter rules than the server.