# Stock Workspace

Implemented on DEV in `19.0.3.9.0`. Do not deploy to production until approved.

## Purpose

Avea’s main interface for products, pricing and stock. Odoo `product.template` / inventory / tax / supplier / POS fields remain the source of truth — no parallel catalogue.

## Catalogue

- Menu: **Avea Dashboard → Stock** (Products)
- Banner + **+ New Stock Item**, header actions **Receive Stock** / **Stock Count**
- Columns: Product, SKU, Barcode, Category, Supplier, Current Stock, Stock Status, Cost EX VAT, Markup %, Margin %, Retail Price INC VAT, Sell on POS, Track Stock
- Inline edit for pricing; **Open** / row open uses the Avea Stock Item form
- Search: name / SKU / barcode; filters for stock status, POS, track stock, active/archived; tags as brand/labels where used

## New / Edit Stock Item

One-page workspace (left setup + right live summary):

- Product (name, image, SKU, barcode, category, tags, active)
- Selling (Sell on POS, Cost EX VAT, Markup %, Margin %, Retail INC VAT, sales tax)
- Stock (Track Stock, current qty, status, low-stock threshold → orderpoint)
- Purchasing (supplier with create-in-place, supplier code/cost/UoM)
- Units & details (sales UoM, weight, volume)
- POS (POS categories)

## Pricing / tax (ADR-008)

| Field | Basis |
|-------|--------|
| Cost | EX VAT (`standard_price`) |
| Retail | INC VAT (`list_price`) |

Markup and margin use Retail EX VAT from the product’s `taxes_id` (never hard-coded 15%):

- Markup % = `(Retail EX − Cost) / Cost × 100`
- Margin % = `(Retail EX − Cost) / Retail EX × 100`

Example: Cost R100 EX, Retail R172.50 INC @ 15% included → Retail EX R150 → Markup 50%, Margin 33.33%.

## Stock status

- **In Stock** / **Low Stock** / **Out of Stock** / **Not Tracked**
- Low stock uses reorder min when set, otherwise default threshold of 5
- On-hand qty via Odoo `qty_available` (inventory adjustment inverse)

## Receive Stock pricing popup

When a line's EX-tax cost differs from the product cost, Avea opens a compact popup showing **Current vs New** for Cost, Retail, Markup % and Margin % (tax-aware).

Choices:

- **Keep Current Pricing** — leave the product unchanged
- **Update Cost Only** — set product cost to the receive cost; keep retail
- **Update Cost & Pricing** — set cost and retail (editable in the popup; markup/margin recalculate live)

If the cashier skips the popup, **Receive Stock** opens it for any undecided differing line before posting.

## Key files

- `models/stock/product_template.py`
- `views/stock/stock_product_views.xml`
- `static/src/js/stock/stock_catalogue.js`
- `static/src/scss/stock/stock_workspace.scss`
