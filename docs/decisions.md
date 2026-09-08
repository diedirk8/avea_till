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

Additional Charges on Receive Stock (see ADR-009) are posted as ordinary vendor-bill expense lines only. They are included in the supplier invoice total but are never allocated into inventory valuation or product cost from this screen.

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
---

# ADR-007

## Combo Price exclusive quantity allocation

Status

Accepted

Reason

Multiple Combo Price promotions that share a product (e.g. one bag of food paired with different treats) each matched against the full cart independently. One shared unit was counted for every matching promo, so `1× shared + 2× partners` produced two combo discounts.

Decision

In POS `combo_promotions.js`:

- Maintain one `availableQty` pool for the cart while applying Combo Price programs.
- Rank eligible programs by highest customer saving per complete set (`catalogIncl − combo_price`), then by lower program id.
- Allocate as many complete sets as the pool allows for each program in that order, then subtract component quantities from the pool.
- Leftover units remain at normal retail. VAT/accounting for combo discount lines is unchanged (tax-included discount matching native loyalty).

---

# ADR-008

## Stock Workspace pricing uses Cost EX Tax and Retail INC Tax

Status

Accepted

Reason

Shop owners think in cost-before-tax and shelf price-including-tax. Calculating markup or margin against the tax-inclusive retail price understates profitability and confuses pricing decisions.

Decision

- Cost = `product.template.standard_price` (EX tax)
- Retail = `product.template.list_price` (INC tax)
- Retail EX tax is derived with the product's sales taxes (`taxes_id`) via `account.tax.compute_all` — never a hard-coded tax rate
- Markup % = (Retail EX − Cost) / Cost; Margin % = (Retail EX − Cost) / Retail EX
- Stock Workspace edits `product.template` / related sellerinfo / orderpoints / on-hand qty directly; no parallel product or stock tables
- Stock Count remains a later dedicated workspace; Phase 5 ships a placeholder entry point only
- Receive Stock opens a compact **Current vs New** pricing popup when the line cost differs from the product cost (Keep / Update Cost Only / Update Cost & Pricing)

---

# ADR-009

## Receive Stock additional charges are bill expenses, not inventory cost

Status

Accepted

Reason

Supplier invoices often include shipping, handling, or similar charges that must match the paper total and the vendor bill, without changing product cost or stock valuation yet. Proper Landed Costs allocation is a later Stock feature.

Decision

- Capture charges as `avea.stock.receive.charge` lines (Description + Amount EX tax)
- Include charge tax using the company purchase tax / fiscal position (same convention as product receive lines)
- Include charges in Receive Stock totals and the optional invoice-total check
- After the PO-based vendor bill is created and before `action_post`, append ordinary invoice lines:
  - no product / no purchase order line
  - expense account (prefer Shipping `610060`, else a Shipping-named expense, else any expense)
  - company purchase taxes
  - flag `account.move.line.avea_additional_charge = True`
- Accounting entries follow standard Odoo vendor-bill posting: debit expense (+ input tax), credit payable
- Do **not** allocate into inventory valuation, AVCO, or `standard_price` from Receive Stock
- Keep `charge_kind` / `avea_additional_charge` so a future Landed Costs workflow can select these bill lines without rewriting Receive Stock

---

# ADR-010

## Business Performance ranking methodology

Status

Accepted

Reason

Business owners need commercially meaningful answers — not naive “top sellers by quantity” or “highest margin %” lists that mislead when sample sizes, discounts, refunds, or price points differ.

Decision

Performance is a **separate workspace** under Business Overview. Business Overview itself stays unchanged.

### Data source

- Native `pos.order.line` rows from **paid** POS orders in the selected reporting period (`reporting_period.py` windows, same as Business Overview).
- Same line filter as Sales Ledger: real products only, exclude service/combo parent lines, include refunds as negative quantities/amounts.
- **Revenue EX tax** = Σ `price_subtotal` (already net of line discounts and promotions).
- **Unit cost** = `product.template._avea_get_cost_ex_tax()` (Avea commercial cost, falling back to `standard_price`).
- **Gross profit** = Σ (`price_subtotal` − unit cost × qty) per line.
- **Categories** aggregate underlying sale lines — never average product margins.

### Top Performing (products and categories)

Rank by **performance score**:

```
performance_score = revenue_ex_tax × sqrt(units_positive / period_units_positive)
```

Where `units_positive` counts only qty > 0 on each line, and `period_units_positive` is the sum across all qualifying rows in that ranking set.

Only rows with `revenue_ex_tax > 0` and at least one unit sold qualify. Refunds reduce net totals but do not appear as “top performers” on their own.

This balances high-volume/low-value and lower-volume/high-value strengths without arbitrary formulas such as quantity + revenue.

### Most Profitable (products and categories)

Rank by **gross profit contribution** (absolute currency), not margin percentage.

Only rows with positive gross profit in the period qualify.

### Presentation

- Reuse Avea workspace shell, hero, period selector, and card styling from Business Overview.
- Show supporting columns: Qty, Revenue EX Tax; add Gross Profit on profitability tables.
- Limit each list to eight rows (same practical limit as Business Overview top products).

---

# ADR-011

## Standalone Avea Settings workspace

Status

Accepted

Reason

Avea is evolving into a standalone product. Business owners should configure Avea in Avea — not through Odoo's General Settings screens or POS invoice workflows.

Decision

### Settings surface

- Add a top-level **Settings** item in Avea navigation.
- Use the same Avea workspace shell and visual language as Business Overview and Performance.
- Do **not** add these controls to Odoo General Settings → Avea Dashboard.
- Store business-level settings on `res.company` underneath, exposed through a transient `avea.business.settings` workspace that can grow with future sections.

### Initial section: Receipts & Email

Business-level controls:

1. **Automatically email receipt to customer** (ON/OFF)
2. **Sender name**
3. **Sender email**

When ON, after a successfully completed POS sale:

- If a customer is selected and has a valid email address, Avea automatically emails a simple **Avea receipt** (not an invoice).
- No cashier action, no payment-screen email choice, and no Odoo invoice generated/downloaded/opened from POS.

When OFF, no automatic email is sent.

### Receipt content and sender

- Reuse Avea/Odoo POS order data and a dedicated QWeb email template aligned with printed receipt information: business details, date/time, order number, products, quantities, prices, discounts/promotions, tax, total, and payment method.
- Email is sent as the **business** (`avea_receipt_sender_name` / `avea_receipt_sender_email`), not the cashier/session user.
- Use Odoo `mail.template` and `mail.mail` underneath; Avea owns the user-facing wording and layout.
- The email body stays a simple Avea summary. The attachment is the **same POS `OrderReceipt` component** used for printing, rendered in POS after payment and attached as a PDF (no second receipt template).

### POS behaviour

- Hide the POS **Invoice** toggle from the Avea payment screen.
- Force `to_invoice = False` on POS sync so invoice workflow is not exposed or triggered from Avea POS.

### Tests

Cover setting ON/OFF, customer with/without email, no customer, successful completed sale, receipt contents, business sender identity, cashier not used as sender, and no invoice on POS.
