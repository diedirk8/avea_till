# -*- coding: utf-8 -*-
from odoo import Command
from odoo.tests import tagged
from odoo.addons.point_of_sale.tests.common import TestPoSCommon


@tagged("post_install", "-at_install", "avea_till")
class TestAveaCustomerCentre(TestPoSCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = cls.env["res.users"].create(
            {
                "name": "Avea Customer Manager",
                "login": "avea_customer_mgr@dev.local",
                "email": "avea_customer_mgr@dev.local",
                "company_id": cls.env.company.id,
                "company_ids": [Command.set([cls.env.company.id])],
                "group_ids": [
                    Command.set([cls.env.ref("avea_till.group_avea_manager").id])
                ],
            }
        )

    def test_create_from_workspace_sets_customer_rank(self):
        partner = (
            self.env["res.partner"]
            .with_context(avea_customer_workspace=True)
            .create({"name": "Avea Centre Customer"})
        )
        self.assertGreater(partner.customer_rank, 0)

    def test_product_shell_uses_avea_customer_form(self):
        partner = self.env["res.partner"].create(
            {"name": "Shell Customer", "customer_rank": 1}
        )
        view_id = partner.with_user(self.manager).get_formview_id()
        expected = self.env.ref("avea_till.view_avea_customer_form").id
        self.assertEqual(view_id, expected)
