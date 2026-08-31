/** @odoo-module **/

import { TicketScreen } from "@point_of_sale/app/screens/ticket_screen/ticket_screen";
import { patch } from "@web/core/utils/patch";
import { makeAwaitable } from "@point_of_sale/app/utils/make_awaitable_dialog";
import { CorrectPaymentPopup } from "./correct_payment_popup";
import { isStoreCreditPaymentMethod } from "./store_credit";

patch(TicketScreen.prototype, {
    get showCorrectPaymentMethod() {
        if (!this.pos.canCorrectPaymentMethod()) {
            return false;
        }
        if (this.pos.session?.state !== "opened") {
            return false;
        }
        const order = this.getSelectedOrder();
        if (!order || !this.isOrderSynced) {
            return false;
        }
        if (order.account_move || order.state === "invoiced") {
            return false;
        }
        const tenders = (order.payment_ids || []).filter(
            (payment) => !payment.is_change && Math.abs(payment.getAmount?.() ?? payment.amount ?? 0) > 0
        );
        if (tenders.length !== 1) {
            return false;
        }
        const change = (order.payment_ids || []).filter(
            (payment) => payment.is_change && Math.abs(payment.getAmount?.() ?? payment.amount ?? 0) > 0
        );
        if (change.length) {
            return false;
        }
        const method = tenders[0].payment_method_id;
        if (!method || isStoreCreditPaymentMethod(method)) {
            return false;
        }
        return method.type === "cash" || method.type === "bank" || method.is_cash_count;
    },

    async openCorrectPaymentMethod() {
        const order = this.getSelectedOrder();
        if (!order || !this.showCorrectPaymentMethod) {
            return;
        }
        await makeAwaitable(this.dialog, CorrectPaymentPopup, { order });
    },
});
