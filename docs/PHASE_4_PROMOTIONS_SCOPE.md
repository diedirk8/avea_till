# Phase 4 — Promotions v1 Scope

## Goal

Create a deliberately simple Avea Promotions interface for small-business retail. Avea should be the easy front end; Odoo remains the underlying pricing, promotion, discount, loyalty, and accounting engine wherever practical.

## Promotion setup

Keep configuration to the essentials:

1. **What products?**
   - Specific products
   - Product category
   - All products
   - For **Combo Price**, a dynamic unlimited list of combo products with quantities
2. **When?**
   - Start date
   - End date
   - Open ended (no end date until deactivated)
3. **What is the deal?**
   - Percentage off
   - Fixed amount off
   - Buy X, Get Y
   - Spend X, Save R / %
   - **Combo Price** — any number of products sold together for one fixed price (no artificial maximum product count)
   - Extra loyalty points
4. **Promo code** — optional
5. Promotions should normally apply automatically when their conditions are met.

## Combo Price

- Shop owners build a combo as: selected products + required quantities = one combo price.
- Combo product lines are unlimited; users can keep adding products.
- POS recognises complete combinations in the cart and charges the configured combo price.
- Multiple complete combos in one cart are supported (e.g. 2× each required product → 2 combos).
- Quantities beyond complete sets remain at normal retail price.
- Native Odoo loyalty cannot express multi-product fixed combo pricing with per-line quantities, so Avea applies the combo discount in POS while still publishing a loyalty program shell for till availability, dates and promo codes.

## POS experience

The cashier should not need to understand promotion rules. Eligible promotions should trigger automatically where possible. Promo codes can be entered/scanned when a promotion requires one.

## Principles

- Keep the UI extremely simple: **Products → Dates → Deal → Save**.
- Do not expose Odoo's complex pricelist/promotion configuration unless genuinely necessary.
- Reuse Odoo 19 Community's native Discount & Loyalty / POS promotion capabilities where they satisfy the requirement.
- Do not build every advanced promotion feature from other POS systems into v1.
- Extra loyalty earning is treated as a promotion reward, separate from price discounts.

## Deferred unless needed

Tiered quantity pricing, complex customer groups, time-of-day rules, stacking/priority configuration, advanced coupon campaigns, and other complex promotion combinations can be added later based on actual business needs.
