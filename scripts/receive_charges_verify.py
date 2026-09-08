#!/usr/bin/env python3
"""DEV verify: Receive Stock additional charges accounting.

Run:
  docker exec -i odoo-dev odoo shell -d petsempire_dev --no-http \\
    < /opt/odoo/dev/avea_till/scripts/receive_charges_verify.py
"""
from odoo import Command, fields
from odoo.tools.float_utils import float_compare

admin = env.ref("base.user_admin")  # noqa: F821
env = env(user=admin)  # noqa: F821

company = env.company
currency = company.currency_id
tax = company.account_purchase_tax_id
assert tax, "Company purchase tax required"

partner = env["res.partner"].search(
    [("name", "=", "Avea Charge Verify Supplier")], limit=1
)
if not partner:
    partner = env["res.partner"].create(
        {
            "name": "Avea Charge Verify Supplier",
            "supplier_rank": 1,
            "company_id": company.id,
            "is_company": True,
        }
    )

product = env["product.product"].search(
    [("name", "=", "Avea Charge Verify Product")], limit=1
)
if not product:
    product = env["product.product"].create(
        {
            "name": "Avea Charge Verify Product",
            "type": "consu",
            "is_storable": True,
            "list_price": 115.0,
            "standard_price": 80.0,
            "purchase_ok": True,
            "sale_ok": True,
            "company_id": company.id,
            "supplier_taxes_id": [Command.set(tax.ids)],
        }
    )

standard_before = product.standard_price
qty_before = product.qty_available
invoice_no = "CHG-VERIFY-%s" % fields.Datetime.now().strftime("%H%M%S")

receive = env["avea.stock.receive"].create(
    {
        "partner_id": partner.id,
        "invoice_number": invoice_no,
        "invoice_date": fields.Date.today(),
        "received_date": fields.Date.today(),
        "company_id": company.id,
        "currency_id": currency.id,
        "mark_as_paid": False,
        "line_ids": [
            Command.create(
                {
                    "product_id": product.id,
                    "quantity": 2.0,
                    "price_unit": 80.0,
                    "avea_pricing_choice": "keep",
                }
            )
        ],
        "charge_ids": [
            Command.create({"name": "Shipping", "amount": 50.0}),
            Command.create({"name": "Handling", "amount": 20.0}),
        ],
    }
)

assert receive.charge_count == 2
assert float_compare(receive.amount_charges_untaxed, 70.0, precision_digits=2) == 0
product_untaxed = sum(receive.line_ids.mapped("price_subtotal"))
assert (
    float_compare(
        receive.amount_untaxed,
        product_untaxed + receive.amount_charges_untaxed,
        precision_digits=2,
    )
    == 0
)
receive.invoice_total = receive.amount_total
assert not receive.totals_mismatch

receive.action_receive_stock()
receive.invalidate_recordset()
assert receive.state == "done", receive.state
bill = receive.bill_id
assert bill and bill.state == "posted"

charge_lines = bill.invoice_line_ids.filtered("avea_additional_charge")
assert len(charge_lines) == 2
assert set(charge_lines.mapped("name")) == {"Shipping", "Handling"}
assert not charge_lines.product_id
assert all(line.account_id.account_type == "expense" for line in charge_lines)
assert float_compare(bill.amount_total, receive.amount_total, precision_digits=2) == 0

expense_debit = sum(
    bill.line_ids.filtered("avea_additional_charge").mapped("debit")
)
assert float_compare(expense_debit, 70.0, precision_digits=2) == 0

product.invalidate_recordset()
assert float_compare(product.standard_price, standard_before, precision_digits=2) == 0
assert float_compare(product.qty_available, qty_before + 2.0, precision_digits=2) == 0

print("OK receive", receive.id)
print("OK bill", bill.name, "total", bill.amount_total)
print(
    "OK charges",
    [(line.name, line.price_unit, line.account_id.code, line.account_id.display_name)
     for line in charge_lines],
)
print("OK tax lines", bill.line_ids.filtered("tax_line_id").mapped(
    lambda line: (line.name, line.debit or line.credit)
))
print("OK product cost unchanged", product.standard_price)
env.cr.rollback()
print("RESULT: PASS (rolled back)")
