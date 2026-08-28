/** @odoo-module **/

import { Component } from "@odoo/owl";
import { ReceiptHeader } from "@point_of_sale/app/screens/receipt_screen/receipt/receipt_header/receipt_header";

export class CashUpReceipt extends Component {
    static template = "avea_till.CashUpReceipt";
    static components = { ReceiptHeader };
    static props = {
        receipt: Object,
        order: Object,
    };
}
