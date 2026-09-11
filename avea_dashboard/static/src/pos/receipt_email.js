/** @odoo-module **/

import OrderPaymentValidation from "@point_of_sale/app/utils/order_payment_validation";
import { isValidEmail } from "@point_of_sale/utils";
import { patch } from "@web/core/utils/patch";

/**
 * Schedule automatic receipt email without blocking order validation.
 *
 * ``afterOrderValidation`` runs inside ``finalizeValidation()``, which the
 * Feedback screen awaits before allowing the cashier to continue. Any await
 * here keeps the "Amount Paid" screen stuck on background processing.
 */
patch(OrderPaymentValidation.prototype, {
    async afterOrderValidation(...args) {
        await super.afterOrderValidation(...args);
        try {
            this._aveaScheduleReceiptEmail();
        } catch (error) {
            console.warn("Avea receipt email could not be scheduled.", error);
        }
    },

    _aveaPartnerEmail(partner) {
        const raw = partner?.email;
        if (typeof raw !== "string") {
            return "";
        }
        return raw.trim();
    },

    _aveaScheduleReceiptEmail() {
        const order = this.order;
        if (!order?.isSynced) {
            return;
        }
        if (order.uiState?.aveaReceiptEmailScheduled) {
            return;
        }
        const partner = order.getPartner();
        const email = this._aveaPartnerEmail(partner);
        if (!partner || !email || !isValidEmail(email)) {
            return;
        }
        order.uiState.aveaReceiptEmailScheduled = true;
        void this._aveaSendReceiptEmailInBackground(order);
    },

    async _aveaSendReceiptEmailInBackground(order) {
        try {
            await this.pos.data.silentCall(
                "pos.order",
                "avea_send_receipt_email_automatic",
                [[order.id]]
            );
        } catch (error) {
            order.uiState.aveaReceiptEmailScheduled = false;
            console.warn("Avea receipt email could not be sent.", error);
        }
    },
});
