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
