/** @odoo-module **/

import { PosStore } from "@point_of_sale/app/services/pos_store";
import { patch } from "@web/core/utils/patch";
import { makeAwaitable } from "@point_of_sale/app/utils/make_awaitable_dialog";
import { IssueStoreCreditPopup } from "./issue_store_credit_popup";
import { CashUpPopup } from "./cash_up_popup";
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
    canCashUpOwnTill() {
        const operator = this.cashier || this.getCashier?.() || this.user;
        if (!operator) {
            return false;
        }
        if (operator._can_cash_up_own_till !== undefined) {
            return Boolean(operator._can_cash_up_own_till);
        }
        const raw = operator.raw;
        if (raw?.can_cash_up_own_till !== undefined) {
            return Boolean(raw.can_cash_up_own_till);
        }
        return Boolean(operator.can_cash_up_own_till);
    },
    canCorrectPaymentMethod() {
        const operator = this.cashier || this.getCashier?.() || this.user;
        if (!operator || this.session?.state !== "opened") {
            return false;
        }
        if (operator._can_correct_payment_method !== undefined) {
            return Boolean(operator._can_correct_payment_method);
        }
        const raw = operator.raw;
        if (raw?.can_correct_payment_method !== undefined) {
            return Boolean(raw.can_correct_payment_method);
        }
        if (raw?._can_correct_payment_method !== undefined) {
            return Boolean(raw._can_correct_payment_method);
        }
        return Boolean(operator.can_correct_payment_method);
    },
    openCashUp() {
        if (this.session?.state === "closed") {
            return;
        }
        return makeAwaitable(this.dialog, CashUpPopup);
    },
    async closingSessionNotification(data) {
        if (this.aveaSuppressSessionReload) {
            return;
        }
        return await super.closingSessionNotification(data);
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
    async refreshPartnerStoreCreditBalance(partnerId) {
        if (!partnerId || !this.isAveaCreditEnabled()) {
            return 0;
        }
        try {
            const result = await this.data.call(
                "res.partner",
                "pos_get_store_credit_balance",
                [partnerId]
            );
            const balance = result?.balance ?? 0;
            this.updatePartnerStoreCreditBalance(partnerId, balance);
            return balance;
        } catch (_error) {
            const partner = this.models["res.partner"].get(partnerId);
            return this.getPartnerStoreCreditBalance(partner);
        }
    },
    setPartnerToCurrentOrder(partner) {
        super.setPartnerToCurrentOrder(...arguments);
        if (partner?.id) {
            this.refreshPartnerStoreCreditBalance(partner.id);
        }
    },
});
