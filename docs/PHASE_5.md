# AVEA DASHBOARD — PHASE 5

Phase 5 is planned for after Phase 4 priorities are complete.

## Grooming Booking & Management

Build a simple grooming booking/management system inspired by the practical workflow of ShakeYourTail, while following Avea's principle of hiding unnecessary Odoo complexity.

Planned areas include:

- Grooming bookings and calendar/availability.
- Customer and pet information.
- Grooming services, pricing and staff/groomer assignment.
- Booking status and relevant history.
- Customer communication/history where useful.
- Relevant payment/pricing information.
- A practical migration/import path from ShakeYourTail using business data the owner can legitimately access, without depending on ShakeYourTail voluntarily supplying a proprietary database dump.

## Product / Stock Tools

Phase 5 should also include simple Avea POS-style product management tools:

- **New Inventory Item** creation using a simple popup form rather than the full Odoo product form.
- POS-friendly fields and workflow.
- Markup calculation, including cost, markup percentage and selling price.
- When receiving stock, if the supplier's new EX-VAT cost differs from the product's current cost, prompt the user whether the product cost should be updated to the new price. Apply the product-cost update only if confirmed.

These tools must use Odoo as the underlying source of truth while keeping the Avea interface simple and retail-focused.

## Simple Business Accounting

Phase 5 should also move Avea toward a simple small-business accounting experience inspired by Zoho Books, QuickBooks and Xero, without exposing unnecessary Odoo accounting complexity.

The goal is not to build a separate accounting engine. Odoo's existing accounting engine remains the underlying source of truth, while Avea provides a simple, task-focused business-owner interface.

Planned areas include:

- Simple accounting dashboard.
- Income / Sales.
- Expenses.
- Purchases / Bills.
- Customers.
- Suppliers.
- Bank & Cash.
- Bank statement import.
- Bank transaction matching and reconciliation.
- VAT / tax overview appropriate to the business.
- Profit & Loss.
- Balance Sheet.
- General Ledger where useful.
- Simple accounting reports.
- Simple manual journal entries.
- Clear cash/bank transaction history.
- Hide technical Odoo concepts such as `account.move`, `account.move.line` and journal mechanics from normal users where practical.

### Accounting architecture

- Odoo `account` remains the accounting engine and source of truth.
- Avea provides the simplified business-owner UI.
- Mature Community/OCA modules should be used where they provide functionality Avea should not rebuild itself.
- OCA bank reconciliation is a candidate for the bank reconciliation layer, subject to licensing, compatibility and productisation review.
- Avea's existing Cash Control / POS cash workflows should remain separate from bank reconciliation unless deliberately integrated later.

### Product philosophy

> **If it requires accounting training to use, Avea should simplify it.**

This accounting layer must be designed as a reusable Avea capability for future customers, not specifically for Pets Empire.
