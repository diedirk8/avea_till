/** @odoo-module **/

import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";

patch(PaymentScreen.prototype, {
    setup() {
        super.setup(...arguments);
        this._aveaStoreCreditLastAmount = null;
    },

    get availablePaymentMethods() {
        return this.payment_methods_from_config;
    },

    get showPartnerStoreCredit() {
        return this.currentOrder.getPartner() && this.pos.isAveaCreditEnabled();
    },

    get partnerStoreCreditBalance() {
        const partner = this.currentOrder.getPartner();
        if (!partner) {
            return 0;
        }
        return this.pos.getPartnerStoreCreditBalance(partner);
    },

    isStoreCreditPaymentDisabled(paymentMethod) {
        return (
            this.pos.isStoreCreditPaymentMethod(paymentMethod) &&
            !this.pos.isStoreCreditPaymentAvailable(paymentMethod, this.currentOrder)
        );
    },

    async clickPaymentMethod(paymentMethod) {
        if (this.isStoreCreditPaymentDisabled(paymentMethod)) {
            const partner = this.currentOrder.getPartner();
            this.dialog.add(AlertDialog, {
                title: _t("Store Credit"),
                body: partner
                    ? _t("No Store Credit is available for this customer.")
                    : _t("Select a customer before using Store Credit."),
            });
            return false;
        }
        return this.addNewPaymentLine(paymentMethod);
    },

    onMounted() {
        super.onMounted(...arguments);
        this._aveaSetupRefundStoreCredit();
    },

    _aveaSetupRefundStoreCredit() {
        const order = this.currentOrder;
        if (!order.isRefund || !this.pos.isAveaCreditEnabled()) {
            return;
        }
        const originalStoreCreditPaid = this.pos.getOriginalStoreCreditPaid(order);
        if (originalStoreCreditPaid <= 0) {
            return;
        }
        const storeCreditMethod = this.pos.getStoreCreditPaymentMethod();
        if (!storeCreditMethod) {
            return;
        }
        const hasStoreCreditLine = order.payment_ids.some((payment) =>
            this.pos.isStoreCreditPaymentMethod(payment.payment_method_id)
        );
        if (hasStoreCreditLine) {
            return;
        }
        const due = Math.abs(order.remainingDue);
        const storeCreditAmount = Math.min(originalStoreCreditPaid, due);
        if (storeCreditAmount <= 0) {
            return;
        }
        const result = order.addPaymentline(storeCreditMethod);
        if (result.status) {
            // Refund payment lines are negative; a positive amount leaves the
            // refund unpaid and blocks Validate.
            result.data.setAmount(-storeCreditAmount);
            this.numberBuffer.set((-storeCreditAmount).toString());
        }
    },

    async addNewPaymentLine(paymentMethod) {
        if (this.pos.isStoreCreditPaymentMethod(paymentMethod)) {
            const partner = this.currentOrder.getPartner();
            if (!partner) {
                this.dialog.add(AlertDialog, {
                    title: _t("Customer required"),
                    body: _t("Select a customer before using Store Credit."),
                });
                return false;
            }
            if (
                !this.currentOrder.isRefund &&
                !this.pos.isStoreCreditPaymentAvailable(paymentMethod, this.currentOrder)
            ) {
                this.dialog.add(AlertDialog, {
                    title: _t("Store Credit"),
                    body: _t("No Store Credit is available for this customer."),
                });
                return false;
            }
        }
        return super.addNewPaymentLine(...arguments);
    },

    updateSelectedPaymentline(amount = false) {
        const line = this.selectedPaymentLine;
        const previousAmount = line?.getAmount() ?? 0;
        super.updateSelectedPaymentline(...arguments);
        if (!line || !this.pos.isStoreCreditPaymentMethod(line.payment_method_id)) {
            return;
        }
        const error = this.pos.validateStoreCreditPaymentAmount(this.currentOrder, line);
        if (error) {
            line.setAmount(previousAmount);
            this.numberBuffer.set(previousAmount ? previousAmount.toString() : "");
            this.dialog.add(AlertDialog, {
                title: _t("Store Credit"),
                body: error,
            });
        }
    },

    deletePaymentLine(uuid) {
        const line = this.paymentLines.find((paymentLine) => paymentLine.uuid === uuid);
        if (
            line &&
            this.pos.isStoreCreditPaymentMethod(line.payment_method_id) &&
            this.currentOrder.isRefund &&
            this.pos.getOriginalStoreCreditPaid(this.currentOrder) > 0
        ) {
            this.dialog.add(AlertDialog, {
                title: _t("Store Credit refund"),
                body: _t(
                    "Store Credit refunds must return to the customer's Store Credit balance."
                ),
            });
            return;
        }
        return super.deletePaymentLine(...arguments);
    },
});
