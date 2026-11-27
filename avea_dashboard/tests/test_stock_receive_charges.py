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
                "avea_cost_ex_tax": 100.0,
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

    def _create_receive(
        self,
        *,
        product_qty=1.0,
        product_cost=100.0,
        charges=None,
        invoice_number="CHG-TEST-001",
    ):
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
                "invoice_number": invoice_number,
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

    def _add_bill_postage(self, receive, amount=200.0, name="Courier&Postage"):
        bill = receive.bill_id
        bill.button_draft()
        account = receive._avea_additional_charge_account()
        taxes = self.purchase_tax
        bill.write(
            {
                "invoice_line_ids": [
                    Command.create(
                        {
                            "name": name,
                            "quantity": 1.0,
                            "price_unit": amount,
                            "account_id": account.id,
                            "tax_ids": [Command.set(taxes.ids)] if taxes else False,
                            "display_type": "product",
                        }
                    )
                ]
            }
        )
        return bill

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
        avea_cost_before = self.product.product_tmpl_id.avea_cost_ex_tax
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
        self.assertAlmostEqual(
            self.product.product_tmpl_id.avea_cost_ex_tax, avea_cost_before, places=2
        )
        self.assertAlmostEqual(
            self.product.qty_available,
            qty_before + 1.0,
            places=2,
        )

    def test_postage_added_on_bill_is_included_in_receive_total(self):
        receive = self._create_receive(invoice_number="CHG-POST-001")
        receive.action_receive_stock()
        receive.invalidate_recordset()
        product_total = receive.amount_total
        self.assertFalse(receive.charge_ids)

        bill = self._add_bill_postage(receive, amount=200.0)
        receive.invalidate_recordset()
        self.assertEqual(
            float_compare(
                receive.amount_total,
                bill.amount_total,
                precision_rounding=self.currency.rounding,
            ),
            0,
            "Receive total must include postage added on the vendor bill",
        )
        self.assertGreater(receive.amount_total, product_total)
        self.assertAlmostEqual(receive.amount_charges_untaxed, 200.0, places=2)

        bill.action_post()
        receive.invalidate_recordset()
        postage = receive.charge_ids.filtered(lambda charge: charge.name == "Courier&Postage")
        self.assertEqual(len(postage), 1)
        self.assertAlmostEqual(postage.amount, 200.0, places=2)
        self.assertEqual(
            float_compare(
                receive.amount_total,
                bill.amount_total,
                precision_rounding=self.currency.rounding,
            ),
            0,
            "After posting, receive total must still match the paid bill",
        )
        extra = receive._avea_bill_extra_charge_lines()
        self.assertFalse(extra, "Synced postage must not be counted twice")
        self.assertAlmostEqual(receive.amount_untaxed, bill.amount_untaxed, places=2)
        self.assertAlmostEqual(receive.amount_tax, bill.amount_tax, places=2)

    def test_synced_postage_does_not_double_count_existing_charges(self):
        receive = self._create_receive(
            charges=[("Shipping", 50.0)],
            invoice_number="CHG-POST-002",
        )
        receive.action_receive_stock()
        bill = receive.bill_id
        posted_total = bill.amount_total
        receive._avea_sync_charges_from_bill()
        receive.invalidate_recordset()
        self.assertEqual(len(receive.charge_ids), 1)
        self.assertEqual(
            float_compare(
                receive.amount_total,
                posted_total,
                precision_rounding=self.currency.rounding,
            ),
            0,
        )
