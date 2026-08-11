/** @odoo-module **/

import { PosStore } from "@point_of_sale/app/services/pos_store";
import { patch } from "@web/core/utils/patch";
import { makeAwaitable } from "@point_of_sale/app/utils/make_awaitable_dialog";
import { IssueStoreCreditPopup } from "./issue_store_credit_popup";
import {
    canIssueStoreCredit,
    formatStoreCreditAmount,
    getAvailableStoreCreditForOrder,
    getOriginalStoreCreditPaid,
    getPartnerStoreCreditBalance,
    getStoreCreditPaymentMethod,
    getStoreCreditRemainingBalance,
    getStoreCreditUsedOnOrder,
    isAveaCreditEnabled,
    isStoreCreditPaymentAvailable,
    isStoreCreditPaymentMethod,
    validateStoreCreditPaymentAmount,
} from "./store_credit";

patch(PosStore.prototype, {
    isAveaCreditEnabled() {
        return isAveaCreditEnabled(this);
    },
    canIssueStoreCredit() {
        return canIssueStoreCredit(this);
    },
    isStoreCreditPaymentMethod(paymentMethod) {
        return isStoreCreditPaymentMethod(paymentMethod);
    },
    getStoreCreditPaymentMethod() {
        return getStoreCreditPaymentMethod(this);
    },
    getPartnerStoreCreditBalance(partner) {
        return getPartnerStoreCreditBalance(partner);
    },
    getStoreCreditUsedOnOrder(order) {
        return getStoreCreditUsedOnOrder(order, this);
    },
    getAvailableStoreCreditForOrder(order, excludePaymentLine = null) {
        return getAvailableStoreCreditForOrder(order, this, excludePaymentLine);
    },
    isStoreCreditPaymentAvailable(paymentMethod, order) {
        return isStoreCreditPaymentAvailable(this, paymentMethod, order);
    },
    getOriginalStoreCreditPaid(order) {
        return getOriginalStoreCreditPaid(order, this);
    },
    getStoreCreditRemainingBalance(order) {
        return getStoreCreditRemainingBalance(order, this);
    },
    formatStoreCreditAmount(amount, partner) {
        return formatStoreCreditAmount(this, amount, partner);
    },
    validateStoreCreditPaymentAmount(order, paymentLine) {
        return validateStoreCreditPaymentAmount(this, order, paymentLine);
    },
    issueStoreCredit() {
        return makeAwaitable(this.dialog, IssueStoreCreditPopup);
    },
    updatePartnerStoreCreditBalance(partnerId, balance) {
        const partner = this.models["res.partner"].get(partnerId);
        if (partner) {
            partner.avea_credit_balance = balance;
        }
        for (const order of this.getOpenOrders()) {
            const orderPartner = order.getPartner();
            if (orderPartner?.id === partnerId) {
                orderPartner.avea_credit_balance = balance;
            }
        }
    },
});
