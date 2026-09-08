# -*- coding: utf-8 -*-
from odoo import Command, fields
from odoo.tests import tagged
from odoo.tests.common import TransactionCase
from odoo.tools.float_utils import float_compare


@tagged("post_install", "-at_install", "avea_stock")
class TestAveaStockReceiveCharges(TransactionCase):
    """Additional charges stay on the vendor bill as expenses (not inventory)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.currency = cls.company.currency_id
        cls.partner = cls.env["res.partner"].create(
            {
                "name": "Avea Charge Test Supplier",
                "supplier_rank": 1,
                "company_id": cls.company.id,
                "is_company": True,
            }
        )
        cls.purchase_tax = cls.company.account_purchase_tax_id
        cls.product = cls.env["product.product"].create(
            {
                "name": "Avea Charge Test Product",
                "type": "consu",
                "is_storable": True,
                "list_price": 115.0,
                "standard_price": 100.0,
                "purchase_ok": True,
                "sale_ok": True,
                "company_id": cls.company.id,
                "supplier_taxes_id": [Command.set(cls.purchase_tax.ids)]
                if cls.purchase_tax
                else False,
            }
        )
        warehouse = cls.env["stock.warehouse"].search(
            [("company_id", "=", cls.company.id)], limit=1
        )
        if not warehouse:
            raise AssertionError("Warehouse required for Receive Stock tests")

    def _create_receive(self, *, product_qty=1.0, product_cost=100.0, charges=None):
        charge_cmds = []
        for name, amount in charges or []:
            charge_cmds.append(
                Command.create(
                    {
                        "name": name,
                        "amount": amount,
                    }
                )
            )
        return self.env["avea.stock.receive"].create(
            {
                "partner_id": self.partner.id,
                "invoice_number": "CHG-TEST-001",
                "invoice_date": fields.Date.today(),
                "received_date": fields.Date.today(),
                "company_id": self.company.id,
                "currency_id": self.currency.id,
                "mark_as_paid": False,
                "line_ids": [
                    Command.create(
                        {
                            "product_id": self.product.id,
                            "quantity": product_qty,
                            "price_unit": product_cost,
                            "avea_pricing_choice": "keep",
                        }
                    )
                ],
                "charge_ids": charge_cmds,
            }
        )

    def test_totals_include_charges_and_tax(self):
        receive = self._create_receive(
            charges=[("Shipping", 50.0), ("Handling", 20.0)],
        )
        product_untaxed = receive.line_ids.price_subtotal
        product_tax = receive.line_ids.price_tax
        charge_untaxed = sum(receive.charge_ids.mapped("price_subtotal"))
        charge_tax = sum(receive.charge_ids.mapped("price_tax"))

        self.assertAlmostEqual(charge_untaxed, 70.0, places=2)
        self.assertEqual(receive.charge_count, 2)
        self.assertAlmostEqual(
            receive.amount_untaxed,
            product_untaxed + charge_untaxed,
            places=2,
        )
        self.assertAlmostEqual(
            receive.amount_tax,
            product_tax + charge_tax,
            places=2,
        )
        self.assertAlmostEqual(
            receive.amount_total,
            receive.amount_untaxed + receive.amount_tax,
            places=2,
        )
        receive.invoice_total = receive.amount_total
        self.assertFalse(receive.totals_mismatch)

    def test_vendor_bill_posts_expense_charge_lines(self):
        receive = self._create_receive(charges=[("Shipping", 50.0)])
        standard_before = self.product.standard_price
        qty_before = self.product.qty_available

        receive.action_receive_stock()
        receive.invalidate_recordset()
        self.assertEqual(receive.state, "done")
        bill = receive.bill_id
        self.assertTrue(bill)
        self.assertEqual(bill.state, "posted")
        self.assertEqual(bill.move_type, "in_invoice")

        charge_lines = bill.invoice_line_ids.filtered("avea_additional_charge")
        self.assertEqual(len(charge_lines), 1)
        self.assertEqual(charge_lines.name, "Shipping")
        self.assertAlmostEqual(charge_lines.price_unit, 50.0, places=2)
        self.assertFalse(charge_lines.product_id)
        self.assertFalse(charge_lines.purchase_line_id)
        self.assertEqual(
            charge_lines.account_id.account_type,
            "expense",
            "Charges must hit an expense account, not stock valuation",
        )
        if self.purchase_tax:
            self.assertEqual(charge_lines.tax_ids, self.purchase_tax)

        self.assertEqual(
            float_compare(
                bill.amount_total,
                receive.amount_total,
                precision_rounding=self.currency.rounding,
            ),
            0,
            "Vendor bill total must match receive total including charges",
        )

        # Charge accounting: debit expense + tax, credit payable.
        expense_lines = bill.line_ids.filtered("avea_additional_charge")
        self.assertTrue(expense_lines)
        self.assertAlmostEqual(
            sum(expense_lines.mapped("debit")),
            50.0,
            places=2,
        )
        payable = bill.line_ids.filtered(
            lambda line: line.account_id.account_type == "liability_payable"
        )
        self.assertTrue(payable)
        self.assertAlmostEqual(
            sum(payable.mapped("credit")),
            bill.amount_total,
            places=2,
        )

        # Product cost / on-hand must not absorb the charge amount.
        self.product.invalidate_recordset()
        self.assertAlmostEqual(self.product.standard_price, standard_before, places=2)
        self.assertAlmostEqual(
            self.product.qty_available,
            qty_before + 1.0,
            places=2,
        )
