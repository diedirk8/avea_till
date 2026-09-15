# Stock Workspace

Implemented on DEV in `19.0.3.9.0`. Do not deploy to production until approved.

## Purpose

Avea’s main interface for products, pricing and stock. Odoo `product.template` / inventory / tax / supplier / POS fields remain the source of truth — no parallel catalogue.

## Catalogue

- Menu: **Avea Dashboard → Stock** (Products)
- Banner + **+ New Stock Item**, header actions **Receive Stock** / **Stock Take**
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

## Receive Stock additional charges

Compact **Additional Charges** block in the left Totals panel (before the invoice-total check):

- Lines: Description + Amount (EX tax)
- Multiple lines allowed
- Included in Ex-tax / Tax / Total and the optional invoice-total comparison
- Posted on the supplier bill as expense lines (prefer Shipping `610060`), with company purchase tax
- **Not** allocated into inventory or product cost (future Landed Costs can select `avea_additional_charge` bill lines)

See ADR-009.

## Stock Take (`19.0.3.9.65`, DEV only)

Physical inventory counting workflow — not a direct stock-quantity editor. Layout follows common retail POS stock-count patterns (Lightspeed / Hike): compact setup, scan/search while counting, review differences, then complete.

**Principle:** scoped count → review → complete via native Odoo `stock.quant` inventory adjustment. Only products included in the stock take are adjusted.

**Entry:** Stock menu → **Stock Take**, or **Stock Take** button on the catalogue header.

**Start screen:**

| Option | What it does |
|--------|----------------|
| **Full Count** | All tracked stock products |
| **Partial Count** | Products matching one or more filters (category, supplier, name, SKU, stock status) |

Partial counts: search/filter to find products, tick items to add them, then search again for more — selected products are kept in the **Selected for count** list until you start.

**Lifecycle:** Draft → Counting → Review → Applied

**Counting UX:** blind count (expected qty hidden until review), progress bar, scan/search product, enter qty, **Count** (or Enter). Save & Exit resumes later.

**Safety:** partial stock takes never touch products outside the selected scope; incomplete counts cannot be completed; applied stock takes cannot be applied twice.

**Key files:**

- `models/stock/stock_take.py` — `avea.stock.take` + `avea.stock.take.line`
- `models/stock/stock_mixin.py` — `_avea_apply_inventory_count()`
- `views/stock/stock_take_views.xml`
- `static/src/js/stock/stock_take.js` + `stock_take.xml`
- `tests/test_stock_take.py`

## Key files

- `models/stock/product_template.py`
- `views/stock/stock_product_views.xml`
- `static/src/js/stock/stock_catalogue.js`
- `static/src/scss/stock/stock_workspace.scss`
