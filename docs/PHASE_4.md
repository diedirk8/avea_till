# AVEA DASHBOARD — PHASE 4

Phase 4 is the current development phase. Work on DEV first; production only after approval.

## Priorities

1. **Receive Stock — COMPLETE**
2. **Promotions** — in progress on DEV (`avea.promotion` wrapping Odoo Loyalty; includes Combo Price)
3. **Stock Count**
4. **Yoco Neo Touch**
5. **Products Sold**
6. **Customer Accounts**
7. **Reports / Dashboard Improvements**

Do not reopen completed Phase 3 functionality except for bug fixes.

## Receive Stock — Complete

Simple Avea Stock workflow wrapping standard Odoo Purchase → Stock Receipt → Vendor Bill → optional Payment.

- Top-level **Stock** menu with Receive Stock and Return Stock.
- Full/partial receiving.
- Supplier, invoice number/reference, invoice date and received date.
- Product, quantity received and EX-VAT unit cost.
- Native Odoo line discounts.
- Odoo purchase taxes/VAT and accounting remain the source of truth.
- Optional supplier invoice/document upload attached to the vendor bill.
- Optional Mark as Paid using the existing Avea supplier-payment pattern.
- Saved drafts survive refresh/closing and can be resumed; nothing posts until Receive Stock is pressed.
- Completion screen confirms the transaction instead of redirecting to native Odoo Purchase.
- Simple Return Stock workflow using Odoo returns and vendor credit notes.
- Landed costs are not part of the Receive Stock screen; future Stock features must not prevent a later landed-cost workflow.
- Preserve the company's periodic valuation, AVCO and Anglo-Saxon-off configuration.

## Promotions — Priority #2 (DEV)

Avea Promotions (`avea.promotion`) wrap Odoo Discount & Loyalty for a shop-owner-friendly setup screen.

Deal types: % off, Fixed amount off, Buy X Get Y, Spend X Save, **Combo Price**, Extra Loyalty Points.

**Combo Price:** unlimited dynamic combo product lines (product + qty) sold together for one fixed price. POS matches complete sets with **exclusive quantity allocation** across competing Combo Price promotions (highest saving per set first, then program id); leftovers stay at normal retail. Documented in `PHASE_4_PROMOTIONS_SCOPE.md`.

## Stock Count — Priority #3

Build a simple Avea stock-count workflow rather than exposing Odoo Inventory Adjustment complexity.

- User selects a product category.
- Show **all active stockable products** in that category, including products whose current Odoo stock quantity is 0.
- Physical counted quantity is entered separately from Odoo's current quantity; do not assume the system quantity is the count.
- Clearly show system quantity versus physical count and apply resulting adjustments through Odoo's standard inventory mechanisms.
- Mobile-friendly design.
- Avoid excessively long lists: show approximately **5 products per page** with clear **Next 5 / Previous 5** navigation.
- Keep the workflow simple and Avea-branded; hide locations, quants, stock moves and other unnecessary Odoo concepts.
