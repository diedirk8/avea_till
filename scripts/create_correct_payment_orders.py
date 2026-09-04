"""Create varied paid POS orders on an open DEV session for Correct Payment tests."""
from odoo import fields

admin = env.ref("base.user_admin")  # noqa: F821
env = env(user=admin)  # noqa: F821
Session = env["pos.session"]
Product = env["product.product"]
Partner = env["res.partner"]
Order = env["pos.order"]

session = Session.search(
    [("state", "=", "opened"), ("config_id.name", "ilike", "Till 2")], limit=1
)
if not session:
    session = Session.search([("state", "=", "opened")], limit=1)
print("Using session", session.id, session.name)

methods = {}
for m in session.config_id.payment_method_ids:
    kind = m._avea_tender_kind()
    if kind in ("cash", "card", "eft") and kind not in methods:
        methods[kind] = m
        print("  ", kind, m.id, m.name)

products = Product.search(
    [
        ("available_in_pos", "=", True),
        ("sale_ok", "=", True),
        ("list_price", ">", 1),
        ("list_price", "<", 400),
    ],
    limit=30,
)
print("Products", [(p.id, p.display_name, p.lst_price) for p in products[:6]])
p1, p2, p3 = products[0], products[1], products[2]
partners = Partner.search([("customer_rank", ">", 0)], limit=5)
cust_a = partners[0] if partners else Partner.browse()
cust_b = partners[1] if len(partners) > 1 else Partner.browse()
walk_in = Partner.browse()
cash, card, eft = methods.get("cash"), methods.get("card"), methods.get("eft")


def make_order(label, partner, product, qty, method, overpay=False):
    price = product.lst_price
    taxes = product.taxes_id.compute_all(
        price,
        currency=session.config_id.currency_id,
        quantity=qty,
        product=product,
        partner=partner or False,
    )
    total = taxes["total_included"]
    subtotal = taxes["total_excluded"]
    line_vals = {
        "product_id": product.id,
        "qty": qty,
        "price_unit": price,
        "price_subtotal": subtotal,
        "price_subtotal_incl": total,
        "tax_ids": [(6, 0, product.taxes_id.ids)],
    }
    order = Order.create(
        {
            "session_id": session.id,
            "partner_id": partner.id if partner else False,
            "company_id": session.config_id.company_id.id,
            "amount_tax": total - subtotal,
            "amount_total": total,
            "amount_paid": 0,
            "amount_return": 0,
            "lines": [(0, 0, line_vals)],
        }
    )
    # Round up overpay to a clean note above total
    if overpay:
        tender_amt = float(int(total // 100 + 1) * 100)
        if tender_amt <= total:
            tender_amt = total + 50.0
    else:
        tender_amt = total
    payments = [
        (
            0,
            0,
            {
                "payment_method_id": method.id,
                "amount": tender_amt,
                "payment_date": fields.Datetime.now(),
            },
        )
    ]
    if overpay and cash:
        payments.append(
            (
                0,
                0,
                {
                    "payment_method_id": cash.id,
                    "amount": -(tender_amt - total),
                    "is_change": True,
                    "payment_date": fields.Datetime.now(),
                },
            )
        )
    order.write(
        {
            "payment_ids": payments,
            "amount_paid": total,
            "amount_return": max(tender_amt - total, 0),
            "state": "paid",
        }
    )
    order._avea_till_create_cash_movement()
    pays = [(p.payment_method_id.name, p.amount, p.is_change) for p in order.payment_ids]
    print(
        f"CREATED {label} #{order.id} total={total} method={method.name} "
        f"partner={partner.name if partner else 'walk-in'} payments={pays} "
        f"can={order.avea_can_correct_payment} block={order._avea_payment_correction_block_reason()}"
    )
    return order


created = []
if cash:
    created.append(make_order("CASH_EXACT", cust_a, p1, 1, cash))
    created.append(make_order("CASH_CHANGE", walk_in, p2, 1, cash, overpay=True))
if card:
    created.append(make_order("CARD", cust_b, p1, 2, card))
if eft:
    created.append(make_order("EFT", walk_in, p3, 1, eft))

print("Created", len(created))
env.cr.commit()
print("COMMITTED")
