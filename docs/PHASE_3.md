# Phase 3

This is the source-of-truth feature list for **Avea Dashboard Phase 3**.

Implement only the priority currently in progress. Do not start later priorities until they are explicitly requested.

If a cashier or business owner needs training to understand an Avea screen, we have failed.

---

## Terminology

Use these terms consistently:

| Term | Meaning |
|------|---------|
| **Avea Dashboard** | The product / module |
| **Business Overview** | The main Avea screen opened from the Avea module — how the business is doing |
| **Session Dashboard** | Dashboard for one POS session |
| **Cash Ledger** | Cash / till ledger functionality |
| **POS Session** | Odoo's underlying POS session |

Do not call the Avea Dashboard a "Till Dashboard".

Do not rename existing technical till identifiers unless specifically required.

---

## Status

| Priority | Status |
|----------|--------|
| P0 | Done |
| P1 | Specified — **not implemented** |
| P2 / P3 | Not started |

---

## P0 — Session operations (done)

P0 made the existing Session Dashboard and Cash Ledger usable during a busy retail day.

- **P0.1 Products Sold** — Session Dashboard lists all products sold in the session (not a top-N list), with Product, Quantity Sold and Sales Value. Names wrap on mobile. Long lists use pagination / scrolling.
- **P0.2 Mobile responsiveness** — Full pass of the existing Avea interface (Session Dashboard, Cash Ledger, Cash In / Cash Out, Store Credit, Customer Credit, forms, lists, tables, buttons, dialogues, navigation, custom JS/OWL). Desktop must not get worse.
- **P0.3 Avea usability** — A cashier/manager can see which POS session is relevant, who is using it, cash position, cash in, cash out, what happened recently, and what to do next.
- **P0.4 Session Dashboard hierarchy** — At a glance: sales, transactions, payment information, cash activity, cash position, Products Sold, and anything requiring attention. Details stay in the Cash Ledger / drill-down, not duplicated as a second session dump.

Store Credit was already complete. P0 did not rebuild it, the Cash Ledger, Cash In/Out, running balance, POS integration or Customer Credit.

---

## P1 — Main Avea Dashboard: Business Overview

**Status: specified only. Do not implement yet.**

The main Avea Dashboard opened from the Avea module should become the **business-owner overview**.

It answers:

> How is my business doing?

It is **not** a Session Dashboard. It is **not** a till screen. It is the first screen a business owner should see when they open Avea.

### Period views

Add three simple clickable period views:

**TODAY | THIS WEEK | THIS MONTH**

Each view must aggregate **all POS sessions** within that period.

### What to show

Show useful retail KPIs, including:

- Sales
- Transactions
- Cash activity
- Product performance
- Other useful retail metrics

Keep the screen obvious. Prefer a small set of numbers a business owner can read in seconds over an ERP report dump.

### Period comparison

Each period must compare against the appropriate previous period:

| Current period | Compare against |
|----------------|-----------------|
| Today | Previous day |
| This week | Previous week |
| This month | Previous month |

Show the change clearly, for example:

- This Week: R50,000
- Previous Week: R43,000
- Change: +16.3%

The comparison must be visible without extra clicks or a separate report.

### Sessions remain separate

The **Sessions** area stays a separate operational / detail area:

```
Sessions → select POS session → Session Dashboard
```

The Session Dashboard answers:

> What happened in this particular POS session?

Do **not** duplicate the business overview inside the Session Dashboard.

Do **not** turn the Session Dashboard into a date-range business report.

### Constraints

- Targeted changes. Do not rebuild Cash Ledger, Store Credit, Customer Credit, or POS integration to deliver this overview.
- Preserve existing session-level sales and cash calculations unless a real bug is found.
- The overview must work on desktop, tablet and mobile.
- If a first-time user cannot tell that this screen is about the whole business (not one till session), the design has failed.

---

## Later (not P1)

These were explicitly out of scope for P0 and are **not** part of this P1 specification:

- Reports
- Receive Stock
- Promotions
- Customer Accounts
- Simple Cash Transfer
- Bills / Expenses
- Cash reconciliation

Do not implement them under P1.

---

## Development rules

- Inspect the existing implementation before changing anything.
- Make targeted changes rather than rebuilding working functionality.
- Store Credit is complete and working — do not rebuild it.
- Preserve Cash Ledger, Cash In/Out, running balance, POS integration and Customer Credit.
- Follow [docs/vision.md](vision.md) and [docs/coding-standards.md](coding-standards.md).
