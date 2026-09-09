/** @odoo-module **/

import OrderPaymentValidation from "@point_of_sale/app/utils/order_payment_validation";
import { OrderReceipt } from "@point_of_sale/app/screens/receipt_screen/receipt/order_receipt";
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
        this._aveaScheduleReceiptEmail();
    },

    _aveaScheduleReceiptEmail() {
        void this._aveaSendReceiptEmailInBackground();
    },

    async _aveaSendReceiptEmailInBackground() {
        const order = this.order;
        const company = this.pos.company;
        if (!company?.avea_auto_email_receipt || !order?.id) {
            return;
        }
        const partner = order.getPartner();
        const email = partner?.email;
        if (!partner || !email || !isValidEmail(email)) {
            return;
        }
        try {
            const ticketImage = await this.pos.env.services.renderer.toJpeg(
                OrderReceipt,
                {
                    order,
                    basic_receipt: false,
                },
                { addClass: "pos-receipt-print p-3" }
            );
            await this.pos.data.silentCall(
                "pos.order",
                "avea_send_receipt_email_automatic",
                [[order.id], ticketImage]
            );
        } catch (error) {
            console.warn("Avea receipt email could not be sent.", error);
        }
    },
});
