/** @odoo-module **/

import { Orderline } from "@point_of_sale/app/components/orderline/orderline";
import { patch } from "@web/core/utils/patch";
import {
    aveaPrintShow,
    getPrintReceiptCompany,
    isAveaPrintCustomizeEnabled,
} from "./print_receipt_settings";

patch(Orderline.prototype, {
    get lineScreenValues() {
        const values = super.lineScreenValues;
        if (!values || this.props.mode !== "receipt") {
            return values;
        }
        const company = getPrintReceiptCompany(this.line.order_id);
        if (!isAveaPrintCustomizeEnabled(company)) {
            return values;
        }
        if (!aveaPrintShow(company, "avea_print_receipt_show_quantity", null)) {
            values.unitPart = "";
            values.decimalPart = "";
        }
        if (!aveaPrintShow(company, "avea_print_receipt_show_unit_price", null)) {
            values.displayPriceUnit = false;
        }
        if (!aveaPrintShow(company, "avea_print_receipt_show_discounts", null)) {
            values.discount = false;
        }
        if (!aveaPrintShow(company, "avea_print_receipt_show_products", null)) {
            values.price = false;
            values.name = "";
        } else if (values.name) {
            const product = this.line.product_id;
            const reference = product?.default_code?.trim();
            let plainName = values.name.trim();
            const bracketMatch = plainName.match(/^\[([^\]]+)\]\s*(.*)$/);
            if (bracketMatch) {
                plainName = bracketMatch[2].trim() || plainName;
            } else if (reference && plainName.startsWith(`[${reference}]`)) {
                plainName = plainName.slice(reference.length + 2).trim() || plainName;
            }
            values.name = plainName;
        }
        values.aveaSkuLabel = false;
        return values;
    },
});
