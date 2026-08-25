# Phase 3

This is the **single source of truth** for the Avea Dashboard Phase 3 bug and feature list.

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
| **P0 — Bugs / UX** | Mostly done in `0a8d782c3cdeb08fcf591fa68f3aa711290753ae`. Remaining Customer Credit Dashboard items below are **open**. |
| **P1 — Improvements** | Specified — **not implemented** |
| **P2 — Major Features** | Specified — **not implemented** |
| **P3 — Future** | Specified — **not implemented** |

---

## P0 — Bugs / UX

P0 is the operational Session Dashboard / Cash Ledger / existing-screen quality pass.

Completed work landed in commit `0a8d782c3cdeb08fcf591fa68f3aa711290753ae` unless marked **open**.

### Products Sold — completed

- Replace “Top Products This Session” with **Products Sold**.
- Show **ALL** products sold during the session. Do not limit to “top” products.
- Show: Product / Quantity Sold / Sales Value.
- Product names must wrap naturally on mobile. Do not truncate names such as `[10614] GE - Fu....`.
- Quantity and Sales Value must remain clearly readable.
- If there are many products, use sensible scrolling / pagination rather than making the Session Dashboard excessively long.
- Preserve existing sales calculations unless an actual bug is found.

### Full Mobile Responsiveness — completed, with remaining items

Audit all Avea screens, tables, forms, buttons, dialogs, JS/OWL and SCSS.

Fix clipping, overflow, wrapping, touch targets and mobile layouts.

Do not break or degrade desktop.

**Remaining (open):**

- Customer Credit Dashboard on mobile: the **Dashboard** button is clipped.
- Customer Credit Dashboard on mobile: **Amount** values are truncated.
- Reason wrapping on that screen is already working and **must not be changed**.

### Avea Dashboard Usability — completed

- Clear current business / session context.
- Clear cash position and cash activity.
- Clear next actions.
- Remove unnecessary clicks and confusing technical terminology where appropriate.
- Keep existing functionality intact.

### Session Dashboard Usability — completed

Improve information hierarchy. At a glance:

- Sales
- Transactions
- Payments
- Cash
- Products Sold
- Attention items

Do not simply make the dashboard prettier.

### Remaining P0 — Customer Credit Dashboard actions (open)

Add **Issue Credit** as a prominent Customer Credit Dashboard action.

Use the **existing** Issue Credit workflow. Do not rebuild Store Credit or create a second issue path.

---

## P1 — Improvements

**Status: specified only. Do not implement yet.**

### Main Avea Dashboard — Business Overview

The main Avea Dashboard opened from the Avea module should become the business-owner overview.

It answers:

> How is my business doing?

Add three simple clickable period views:

**TODAY | THIS WEEK | THIS MONTH**

Each view must aggregate **all POS sessions** within that period.

Show useful KPIs such as:

- Sales
- Transactions
- Cash activity
- Product performance
- Other useful retail metrics

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

Keep the screen obvious. Prefer a small set of numbers a business owner can read in seconds over an ERP report dump.

### Sessions — Separate Detail Area

The **Sessions** area is a separate operational / detail area:

```
Sessions → select POS session → Session Dashboard
```

The Session Dashboard remains the detailed per-session view. It answers:

> What happened in this particular POS session?

Do **not** duplicate the business overview inside the Session Dashboard.

Do **not** turn the Session Dashboard into a date-range business report.

### Visual Consistency

Avea screens should feel like one retail product: shared layout, type, colour, cards, tables, buttons and empty states across Business Overview, Session Dashboard, Cash Ledger and Customer Credit.

Do not restyle Odoo globally. Keep the existing Avea workspace language and extend it.

### Business Reporting

Simple business reporting that supports the overview — period sales, products, cash activity — without becoming a full ERP reporting suite.

Do not implement the P2/P3 report-like features (promotions analysis, customer account statements beyond what already exists, cash reconciliation) under this item.

---

## P2 — Major Features

**Status: specified only. Do not implement yet.**

### Simple Receive Stock

One simple Avea workflow:

- Supplier
- Products
- Quantities
- Cost
- Date
- Invoice / reference

Automatically create the vendor bill.

Inventory and accounting must be correct.

### Promotions

Simplify / wrap Odoo promotions, coupons, rewards and barcode functionality so a retailer can use them without ERP training.

### Customer Accounts

- Account balance
- Purchases
- Payments
- Debits / credits
- Outstanding balance
- Statements / history

**Store Credit is COMPLETE and working. Do not rebuild it.** Customer Accounts must build alongside it, not replace it.

### Simple Cash Transfer

- FROM account → TO account
- Amount, date, reason, notes
- Automatic accounting entries
- Appears appropriately in the Cash Ledger
- Separate from POS Cash In / Cash Out
- Designed for cash safe → bank deposits

---

## P3 — Future

**Status: specified only. Do not implement yet.**

- **Business Owner Workspace** — later owner-facing workspace beyond the P1 Business Overview.
- **Simple Bills / Expenses**
- **Future Cash Reconciliation**

---

## Development rules

- Inspect the existing implementation before changing anything.
- Make targeted changes rather than rebuilding working functionality.
- Store Credit is complete and working — do not rebuild it.
- Preserve Cash Ledger, Cash In/Out, running balance, POS integration and Customer Credit.
- Keep work inside the requested priority.
- Follow [docs/vision.md](vision.md) and [docs/coding-standards.md](coding-standards.md).
