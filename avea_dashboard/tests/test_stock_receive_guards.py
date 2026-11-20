# -*- coding: utf-8 -*-
from odoo import Command, fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install", "avea_stock")
class TestAveaStockReceiveGuards(TransactionCase):
    """Receive Stock must refuse duplicate invoices, total mismatches, and zero cost."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.currency = cls.company.currency_id
        cls.partner = cls.env["res.partner"].create(
            {
                "name": "Avea Guard Test Supplier",
                "supplier_rank": 1,
                "company_id": cls.company.id,
                "is_company": True,
            }
        )
        cls.other = cls.env["res.partner"].create(
            {
                "name": "Avea Guard Other Supplier",
                "supplier_rank": 1,
                "company_id": cls.company.id,
                "is_company": True,
            }
        )
        cls.product = cls.env["product.product"].create(
            {
                "name": "Avea Guard Test Product",
                "type": "consu",
                "is_storable": True,
                "list_price": 19.0,
                "standard_price": 7.265,
                "avea_cost_ex_tax": 7.265,
                "purchase_ok": True,
                "sale_ok": True,
                "company_id": cls.company.id,
            }
        )

    def _create_receive(self, **vals):
        values = {
            "partner_id": self.partner.id,
            "invoice_number": "GUARD-001",
            "invoice_date": fields.Date.today(),
            "received_date": fields.Date.today(),
            "company_id": self.company.id,
            "currency_id": self.currency.id,
            "mark_as_paid": False,
            "line_ids": [
                Command.create(
                    {
                        "product_id": self.product.id,
                        "quantity": 1.0,
                        "price_unit": 7.265,
                        "avea_pricing_choice": "keep",
                    }
                )
            ],
        }
        values.update(vals)
        return self.env["avea.stock.receive"].create(values)

    def test_zero_cost_is_rejected(self):
        receive = self._create_receive(
            line_ids=[
                Command.create(
                    {
                        "product_id": self.product.id,
                        "quantity": 1.0,
                        "price_unit": 0.0,
                        "avea_pricing_choice": "keep",
                    }
                )
            ]
        )
        with self.assertRaises(ValidationError) as error:
            receive._avea_check_receive(self.partner)
        self.assertIn("greater than zero", str(error.exception))

    def test_full_discount_zero_cost_is_rejected(self):
        receive = self._create_receive(
            line_ids=[
                Command.create(
                    {
                        "product_id": self.product.id,
                        "quantity": 1.0,
                        "price_unit": 10.0,
                        "discount": 100.0,
                        "avea_pricing_choice": "keep",
                    }
                )
            ]
        )
        with self.assertRaises(ValidationError) as error:
            receive._avea_check_receive(self.partner)
        self.assertIn("greater than zero", str(error.exception))

    def test_invoice_total_mismatch_blocks_receive(self):
        receive = self._create_receive(invoice_total=1.0)
        self.assertTrue(receive.totals_mismatch)
        with self.assertRaises(ValidationError) as error:
            receive._avea_check_receive(self.partner)
        self.assertIn("does not match", str(error.exception))

    def test_matching_invoice_total_is_allowed(self):
        receive = self._create_receive()
        receive.invoice_total = receive.amount_total
        self.assertFalse(receive.totals_mismatch)
        receive._avea_check_receive(self.partner)

    def test_duplicate_invoice_number_for_same_supplier_is_rejected(self):
        self._create_receive(state="done", invoice_number="INV-DUP-77")
        second = self._create_receive(invoice_number="inv-dup-77")
        with self.assertRaises(ValidationError) as error:
            second._avea_check_receive(self.partner)
        self.assertIn("already been received", str(error.exception))

    def test_same_invoice_number_for_another_supplier_is_allowed(self):
        self._create_receive(state="done", invoice_number="INV-SHARE-1")
        other_receive = self._create_receive(
            partner_id=self.other.id,
            invoice_number="INV-SHARE-1",
        )
        other_receive._avea_check_receive(self.other)

    def test_pricing_wizard_rejects_zero_cost(self):
        receive = self._create_receive()
        line = receive.line_ids
        wizard = (
            self.env["avea.stock.receive.pricing.wizard"]
            .with_context(default_line_id=line.id)
            .create({"line_id": line.id})
        )
        wizard.new_cost = 0.0
        with self.assertRaises(UserError) as error:
            wizard.action_update_cost_only()
        self.assertIn("greater than zero", str(error.exception))
