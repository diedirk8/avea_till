# -*- coding: utf-8 -*-
from odoo.tests import tagged
from odoo.addons.point_of_sale.tests.common import TestPoSCommon


@tagged("post_install", "-at_install", "avea_till")
class TestAveaSettingsPrintedReceipt(TestPoSCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.basic_config.company_id

    def test_printed_receipt_settings_workspace_opens(self):
        action = self.env[
            "avea.printed.receipt.settings"
        ].action_open_avea_printed_receipt_settings()
        self.assertEqual(action["res_model"], "avea.printed.receipt.settings")
        settings = self.env["avea.printed.receipt.settings"].browse(action["res_id"])
        self.assertEqual(settings.company_id, self.company)
        self.assertEqual(settings.display_name, "Printed Receipt")

    def test_preview_off_by_default(self):
        settings = self.env["avea.printed.receipt.settings"].create(
            {"company_id": self.company.id}
        )
        preview = settings.printed_receipt_preview_html
        self.assertIn("Customization is off", preview)

    def test_printed_logo_size_reflected_in_preview(self):
        settings = self.env["avea.printed.receipt.settings"].create(
            {"company_id": self.company.id}
        )
        settings.avea_customize_printed_receipt = True
        settings.avea_print_receipt_logo_size = "extra_large"
        settings.invalidate_recordset(["printed_receipt_preview_html"])
        preview = settings.printed_receipt_preview_html
        self.assertIn("max-height: 96px", preview)

        settings.avea_print_receipt_logo_max_height = 110
        settings.invalidate_recordset(["printed_receipt_preview_html"])
        preview = settings.printed_receipt_preview_html
        self.assertIn("max-height: 110px", preview)

    def test_preview_reflects_settings_changes(self):
        settings = self.env["avea.printed.receipt.settings"].create(
            {"company_id": self.company.id}
        )
        settings.avea_customize_printed_receipt = True
        settings.invalidate_recordset(["printed_receipt_preview_html"])
        preview = settings.printed_receipt_preview_html
        self.assertIn("SAMPLE-0001", preview)
        self.assertIn("Premium Dog Food 2kg", preview)

        settings.avea_print_receipt_show_products = False
        settings.invalidate_recordset(["printed_receipt_preview_html"])
        preview = settings.printed_receipt_preview_html
        self.assertNotIn("Premium Dog Food 2kg", preview)

        settings.avea_print_receipt_layout = "compact"
        settings.invalidate_recordset(["printed_receipt_preview_html"])
        preview = settings.printed_receipt_preview_html
        self.assertIn("avea-print-receipt--compact", preview)

    def test_save_settings_persists_to_company(self):
        settings = self.env["avea.printed.receipt.settings"].create(
            {"company_id": self.company.id}
        )
        settings.avea_customize_printed_receipt = True
        settings.avea_print_receipt_show_sku = True
        settings.avea_print_receipt_layout = "compact"
        action = settings.action_save_settings()
        self.assertEqual(action["tag"], "display_notification")
        self.assertTrue(self.company.avea_customize_printed_receipt)
        self.assertTrue(self.company.avea_print_receipt_show_sku)
        self.assertEqual(self.company.avea_print_receipt_layout, "compact")

    def test_pos_settings_rpc_returns_live_company_values(self):
        self.company.write(
            {
                "avea_customize_printed_receipt": True,
                "avea_print_receipt_layout": "detailed",
                "avea_print_receipt_show_sku": True,
            }
        )
        settings = self.company.get_avea_print_receipt_pos_settings()
        self.assertTrue(settings["customize"])
        self.assertEqual(settings["layout"], "detailed")
        self.assertTrue(settings["show_sku"])

    def test_pos_loads_printed_receipt_fields(self):
        fields_list = self.company._load_pos_data_fields(self.basic_config)
        self.assertIn("avea_customize_printed_receipt", fields_list)
        self.assertIn("avea_print_receipt_layout", fields_list)
