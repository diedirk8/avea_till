# -*- coding: utf-8 -*-
from odoo.exceptions import AccessError
from odoo.tests import tagged
from odoo.addons.point_of_sale.tests.common import TestPoSCommon


@tagged("post_install", "-at_install", "avea_till")
class TestPosPartnerAccess(TestPoSCommon):
    """POS cashiers must load/search customers without accounting field access."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.config = cls.basic_config
        cls.pos_user = cls.env["res.users"].create(
            {
                "name": "POS Cashier Partner Access",
                "login": "pos_partner_access_test@dev.local",
                "email": "pos_partner_access_test@dev.local",
                "group_ids": [
                    (
                        6,
                        0,
                        [
                            cls.env.ref("base.group_user").id,
                            cls.env.ref("point_of_sale.group_pos_user").id,
                        ],
                    )
                ],
            }
        )
        cls.test_partner = cls.env["res.partner"].create(
            {
                "name": "POS QA Searchable Customer",
                "email": "pos-qa-search@dev.local",
                "phone": "555-0100",
            }
        )

    def test_pos_partner_fields_exclude_accounting_credit(self):
        fields_list = self.env["res.partner"]._load_pos_data_fields(self.config)
        self.assertNotIn("credit", fields_list)
        self.assertIn("avea_customer_account_balance", fields_list)

    def test_pos_user_can_search_partners(self):
        partner_model = self.env["res.partner"].with_user(self.pos_user)
        result = partner_model.get_new_partner(
            self.config.id,
            [("name", "ilike", "POS QA Searchable")],
            0,
        )
        partners = result["res.partner"]
        self.assertTrue(partners)
        self.assertEqual(partners[0]["name"], self.test_partner.name)
        self.assertIn("avea_customer_account_balance", partners[0])

    def test_pos_user_can_read_customer_account_balance(self):
        partner = self.test_partner.with_user(self.pos_user)
        balance = partner.avea_customer_account_balance
        self.assertEqual(balance, 0.0)

    def test_pos_user_cannot_read_accounting_credit_field(self):
        partner = self.test_partner.with_user(self.pos_user)
        with self.assertRaises(AccessError):
            partner.credit
