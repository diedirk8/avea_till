# Phase 4 — Promotions v1 Scope

## Goal

Create a deliberately simple Avea Promotions interface for small-business retail. Avea should be the easy front end; Odoo remains the underlying pricing, promotion, discount, loyalty, and accounting engine wherever practical.

## Promotion setup

Keep configuration to the essentials:

1. **What products?**
   - Specific products
   - Product category
   - All products
2. **When?**
   - Start date
   - End date
3. **What is the deal?**
   - Percentage off
   - Fixed amount off
   - Buy X, Get Y
   - Spend X, Save R / %
   - Extra loyalty points
4. **Promo code** — optional
5. Promotions should normally apply automatically when their conditions are met.

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
