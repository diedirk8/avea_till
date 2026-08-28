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
| **Opening Cash** | The cash amount intended to remain in the till for the next operating period |
| **Cash Up** | The cashier's end-of-shift/end-of-day till count and close workflow |
| **Cash to Safe** | The cash above Opening Cash that is physically removed from the till and transferred to Company Safe |
| **Company Safe / Company Cash** | Cash held outside POS tills by the business |
| **Petty Cash** | A separate company cash fund used for small operational expenses |

Do not call the Avea Dashboard a "Till Dashboard".

Do not rename existing technical till identifiers unless specifically required.

---

## Status

| Priority | Status |
|----------|--------|
| **P0 — Bugs / UX** | Completed. Session Dashboard / Cash Ledger in `0a8d782c3cdeb08fcf591fa68f3aa711290753ae`; Customer Credit Dashboard mobile and Issue Credit in `19.0.2.27.0`. |
| **P1 — Improvements** | Completed on `develop` (`19.0.2.28.0`) — Business Overview landing page and Avea navigation. **Not in production.** |
| **P2 — Major Features** | Specified — **not implemented** |
| **P3 — Future** | Specified — **not implemented** |

---

## P0 — Bugs / UX

P0 is the operational Session Dashboard / Cash Ledger / existing-screen quality pass.

Completed work landed in commit `0a8d782c3cdeb08fcf591fa68f3aa711290753ae` unless noted otherwise.

### Products Sold — completed

- Replace “Top Products This Session” with **Products Sold**.
- Show **ALL** products sold during the session. Do not limit to “top” products.
- Show: Product / Quantity Sold / Sales Value.
- Product names must wrap naturally on mobile. Do not truncate names such as `[10614] GE - Fu....`.
- Quantity and Sales Value must remain clearly readable.
- If there are many products, use sensible scrolling / pagination rather than making the Session Dashboard excessively long.
- Preserve existing sales calculations unless an actual bug is found.

### Full Mobile Responsiveness — completed

Audit all Avea screens, tables, forms, buttons, dialogs, JS/OWL and SCSS.

Fix clipping, overflow, wrapping, touch targets and mobile layouts.

Do not break or degrade desktop.

Customer Credit Dashboard at ~390px:

- **Dashboard** navigation button is fully readable (not clipped).
- Recent Activity **Amount** values are fully readable (not truncated as `+R 10...`).
- Reason wrapping is unchanged.

### Avea Dashboard Usability — completed

- Clear current business / session context.
- Clear cash position and cash activity.
- Clear next actions.
- Remove unnecessary technical terminology where appropriate.
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

### Customer Credit Dashboard actions — completed

Add **Issue Credit** as a prominent Customer Credit Dashboard action.

Use the **existing** Issue Credit workflow. Do not rebuild Store Credit or create a second issue path.

---

## P1 — Improvements

**Status: completed on development (`develop` / `petsempire_dev`, `19.0.2.28.0`). Do not deploy until requested.**

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

### Business Reporting

Deeper reporting for owners/accountants and other authorised financial users. Reports answer:

> Let me investigate it.

Do not duplicate Business Overview.

Include:

- Sales reports
- Sales by period
- Sales by product
- Sales by category
- Sales by payment method
- Product performance
- Refund analysis
- Cash analysis
- Comparisons
- Custom date-range analysis
- PDF / print output where useful
- Clean A4-friendly layouts for printed reports

Reports should use the company's configured tax terminology and currency. Do not hard-code VAT, South Africa, Rand, or other country-specific assumptions.

### Operations

Owner-facing operational shortcuts that simplify common business tasks without exposing unnecessary Odoo accounting complexity.

#### Add Operational Expense

Simple workflow for entering an operational expense:

- Supplier
- Date
- Document reference
- Expense account
- Description / label
- Amount
- Paid From

Paid From should use configured company cash/bank journals such as Company Safe, Petty Cash or Bank. It must not be coupled to a POS till/session for ordinary operational expenses.

Use Odoo's normal accounting mechanisms underneath. Do not create a parallel accounting system.

#### Simple Cash Transfer

- FROM account → TO account
- Amount, date, reason, notes
- Automatic accounting entries
- Intended for movements between company cash/bank accounts, such as Company Safe → Bank or Company Safe → Petty Cash
- Separate from POS Cash In / Cash Out
- Must not be used for the daily POS till cash drop, because doing so could duplicate the till-side accounting movement

#### Cash Up

Provide a simple cashier-facing end-of-shift/end-of-day workflow for counting and closing the current POS till.

The cashier should have a dedicated Avea permission such as **Can Cash Up Own Till**. This permission must allow the cashier to cash up their own/current POS session without granting unrestricted accounting or general Cash In/Out access.

Cash Up should:

- Identify the current till and POS session
- Show **Opening Cash**
- Show **Expected Cash**
- Allow the cashier to record **Counted Cash**
- Calculate the **Difference**
- Calculate **Cash to Safe** as the cash above Opening Cash that should physically be removed from the till
- Clearly tell the cashier the amount that remains as Opening Cash and the amount that goes into the Safe
- Produce a clean, thermal-printer-friendly printed **Cash-Up Summary** to accompany the cash transfer
- Preserve Odoo's native POS session closing and cash-difference accounting integrity
- Support multiple tills without mixing till accountability
- Remain country- and currency-agnostic

The intended physical workflow is:

**Cashier → Cash Up → Cash to Safe + Cash-Up Summary → Company Safe**

The Company Safe is separate from POS Till Cash and Petty Cash.

Cash Up must be designed as a controlled cashier workflow, not as unrestricted access to Odoo Cash In / Cash Out. The exact relationship between the Avea Cash Up action and Odoo's native POS session closing must be determined from the actual Odoo 19 implementation before coding.

### POS Till Cash → Company Safe Architecture

The target future cash model is:

- **POS Till Cash** — only physical cash belonging to a specific till
- **Company Safe / Company Cash** — physical company cash held outside tills
- **Petty Cash** — separate small cash fund
- **Bank** — actual bank money

Each POS/till must remain independently accountable where multiple tills exist.

The target physical/accounting movement for the daily cash removal is:

**POS Till Cash ↓ → Company Safe / Company Cash ↑**

Do not create duplicate accounting movements. Do not use the general Transfer Money workflow for the same physical till cash movement already recorded by POS Cash Out/Cash Up.

Before implementation, inspect Odoo 19's actual POS Cash In/Out and session-closing accounting behavior and choose the safest implementation. If Odoo's native Cash Out requires a suspense/reclassification step, Avea may simplify that underneath the workflow, but must not expose unnecessary accounting mechanics to cashiers.

Historical POS cash/suspense balances must **not** be automatically rewritten or cleaned up as part of this feature. Historical reconciliation is a separate accounting task requiring approval.

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

---

## P3 — Future

**Status: specified only. Do not implement yet.**

- **Business Owner Workspace** — later owner-facing workspace beyond the P1 Business Overview.
- **Future Cash Office** — receive/verify cash bags, record bag custody, reconcile physical deposits into Company Safe, and provide an audit trail. This is deliberately separate from the cashier Cash Up feature in P2.
- **Future Cash Reconciliation** — broader reconciliation workflows for tills, company cash/safe and bank deposits.
- **POS Receipt Email** — allow a completed POS transaction receipt to be emailed to the customer, reusing the existing Odoo POS receipt/order data without creating a duplicate accounting transaction. Handle missing or invalid email addresses cleanly, allow an appropriate re-send flow where practical, and keep the existing 80mm thermal receipt printing unchanged. Use a simple Avea cashier-facing workflow rather than exposing unnecessary Odoo accounting terminology.

### POS Payment Mistake Prevention & Correction

Busy cashiers can occasionally select the wrong tender, for example recording a card payment as cash or cash as card. Avea should reduce these mistakes without requiring extra training.

#### Payment Selection Safety

Improve the cashier-facing payment workflow so Cash, Card, EFT and other configured payment methods are clearly differentiated and difficult to mis-select under pressure.

- Make the selected payment method unmistakable.
- Give Cash and Card appropriately distinct confirmation/workflows rather than treating them as visually interchangeable buttons.
- Require a clear final confirmation before an irreversible payment is recorded where appropriate.
- Keep the workflow fast for normal transactions.
- Do not introduce unnecessary accounting terminology.
- Preserve Odoo's native payment and session accounting behaviour.

#### Correct Payment Method

Provide an authorised Avea workflow for correcting an honest payment-method mistake on a completed POS transaction without refunding and re-selling the entire transaction.

Example:

> R2,050 sale recorded as **Cash**, actually paid by **Card** → correct the payment to **Card**.

The correction must:

- Leave the sale, products, quantities, taxes and total unchanged.
- Correct the POS payment method/tender itself, not merely create an unrelated manual accounting entry.
- Correct the open POS session's expected cash and payment-method totals so Cash Up remains accurate.
- Correct the underlying accounting/payment journal entries using Odoo's normal mechanisms.
- Never create duplicate cash movements.
- Preserve a clear audit trail showing the original payment method, corrected method, user, date/time and reason.
- Initially require an appropriate manager/authorised permission rather than allowing unrestricted cashier corrections.
- Work safely with open sessions first; handling corrections after session close requires a separate deliberate workflow.
- Be fully tested against Cash Up, session closing, cash/card totals and accounting before deployment.

The preferred outcome is that a normal cashier mistake can be corrected in a few seconds instead of requiring a refund, re-sale, camera review and merchant-terminal investigation.

---

## Development rules

- Inspect the existing implementation before changing anything.
- Make targeted changes rather than rebuilding working functionality.
- Store Credit is complete and working — do not rebuild it.
- Preserve Cash Ledger, Cash In/Out, running balance, POS integration and Customer Credit.
- Keep work inside the requested priority.
- Follow [docs/vision.md](vision.md) and [docs/coding-standards.md](coding-standards.md).
