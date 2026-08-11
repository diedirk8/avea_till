/** @odoo-module **/

import OrderPaymentValidation from "@point_of_sale/app/utils/order_payment_validation";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";
import { validateOrderStoreCredit } from "./store_credit";

patch(OrderPaymentValidation.prototype, {
    async isOrderValid(isForceValidate) {
        const isValid = await super.isOrderValid(...arguments);
        if (!isValid) {
            return false;
        }
        const message = validateOrderStoreCredit(this.pos, this.order);
        if (message) {
            this.pos.dialog.add(AlertDialog, {
                title: _t("Store Credit"),
                body: message,
            });
            return false;
        }
        return true;
    },

    async _askForCustomerIfRequired() {
        const needsCustomer = this.order.payment_ids.some(
            (payment) =>
                payment.payment_method_id.is_avea_store_credit && !payment.is_change
        );
        if (needsCustomer && !this.order.getPartner()) {
            this.pos.dialog.add(AlertDialog, {
                title: _t("Customer required"),
                body: _t("Select a customer before using Store Credit."),
            });
            await this.pos.selectPartner();
            return false;
        }
        return super._askForCustomerIfRequired(...arguments);
    },
});
