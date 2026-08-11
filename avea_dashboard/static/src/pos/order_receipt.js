/** @odoo-module **/

import { OrderReceipt } from "@point_of_sale/app/screens/receipt_screen/receipt/order_receipt";
import { usePos } from "@point_of_sale/app/hooks/pos_hook";
import { patch } from "@web/core/utils/patch";
import {
    formatStoreCreditAmount,
    getStoreCreditRemainingBalance,
    getStoreCreditUsedOnOrder,
    isAveaCreditEnabled,
} from "./store_credit";

patch(OrderReceipt.prototype, {
    setup() {
        super.setup(...arguments);
        this.pos = usePos();
    },

    get storeCreditUsed() {
        if (!this.order.getPartner() || !isAveaCreditEnabled(this.pos)) {
            return 0;
        }
        return getStoreCreditUsedOnOrder(this.order, this.pos);
    },

    get showStoreCreditReceiptInfo() {
        return this.storeCreditUsed > 0;
    },

    get storeCreditRemainingBalance() {
        if (!this.showStoreCreditReceiptInfo) {
            return 0;
        }
        return getStoreCreditRemainingBalance(this.order, this.pos);
    },

    formatStoreCreditAmount(amount) {
        return formatStoreCreditAmount(this.pos, amount, this.order.getPartner());
    },
});
