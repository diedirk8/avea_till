/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";

export function isAveaCreditEnabled(pos) {
    return Boolean(pos.config.avea_credit_enabled);
}

export function getPosOperator(pos) {
    if (!pos) {
        return null;
    }
    if (pos.config?.module_pos_hr) {
        // POS HR: manager actions use the active employee cashier (pos.cashier).
        const cashier = pos.cashier || pos.getCashier?.();
        return cashier || null;
    }
    // Standard POS: manager actions use the logged-in POS user.
    return pos.getCashier?.() ?? pos.user ?? null;
}

export function getOperatorCanIssueStoreCredit(operator) {
    if (!operator) {
        return false;
    }
    // Server-injected booleans without a model field live on the raw payload.
    // Underscore-prefixed extras also get a direct getter (_role, _pin, …).
    if (operator._can_issue_store_credit !== undefined) {
        return Boolean(operator._can_issue_store_credit);
    }
    const raw = operator.raw;
    if (raw?.can_issue_store_credit !== undefined) {
        return Boolean(raw.can_issue_store_credit);
    }
    if (raw?._can_issue_store_credit !== undefined) {
        return Boolean(raw._can_issue_store_credit);
    }
    return Boolean(operator.can_issue_store_credit);
}

export function canIssueStoreCredit(pos) {
    return isAveaCreditEnabled(pos) && getOperatorCanIssueStoreCredit(getPosOperator(pos));
}

export function isStoreCreditPaymentMethod(paymentMethod) {
    return Boolean(paymentMethod?.is_avea_store_credit);
}

export function getStoreCreditPaymentMethod(pos) {
    if (!isAveaCreditEnabled(pos)) {
        return null;
    }
    const fromConfig = pos.config.payment_method_ids.find((pm) =>
        isStoreCreditPaymentMethod(pm)
    );
    if (fromConfig) {
        return fromConfig;
    }
    // POS IndexedDB can keep a stale config.payment_method_ids from before
    // Store Credit was attached to the till. Payment methods themselves are
    // still loaded, so cashiers would see the customer balance but not the
    // Store Credit button until a manager login reloaded the POS.
    const loaded = pos.models["pos.payment.method"]?.getAll?.() ?? [];
    return loaded.find((pm) => isStoreCreditPaymentMethod(pm)) ?? null;
}

export function getPartnerStoreCreditBalance(partner) {
    return partner?.avea_credit_balance ?? 0;
}

export function getStoreCreditUsedOnOrder(order, pos) {
    return order.payment_ids
        .filter((payment) => isStoreCreditPaymentMethod(payment.payment_method_id) && !payment.is_change)
        .reduce((sum, payment) => sum + Math.abs(payment.getAmount()), 0);
}

export function getAvailableStoreCreditForOrder(order, pos, excludePaymentLine = null) {
    const partner = order.getPartner();
    if (!partner || !isAveaCreditEnabled(pos)) {
        return 0;
    }
    let used = getStoreCreditUsedOnOrder(order, pos);
    if (excludePaymentLine) {
        used -= Math.abs(excludePaymentLine.getAmount());
    }
    return Math.max(0, getPartnerStoreCreditBalance(partner) - used);
}

export function isStoreCreditPaymentAvailable(pos, paymentMethod, order) {
    if (!isStoreCreditPaymentMethod(paymentMethod)) {
        return true;
    }
    if (!isAveaCreditEnabled(pos)) {
        return false;
    }
    const partner = order?.getPartner();
    if (!partner) {
        return false;
    }
    if (order?.isRefund) {
        return true;
    }
    return getPartnerStoreCreditBalance(partner) > 0;
}

export function getMaxStoreCreditRefundTotal(order, pos) {
    const refundTotal = Math.abs(order.totalDue ?? order.priceIncl ?? 0);
    const otherPayments = order.payment_ids
        .filter(
            (payment) =>
                !isStoreCreditPaymentMethod(payment.payment_method_id) && !payment.is_change
        )
        .reduce((sum, payment) => sum + Math.abs(payment.getAmount()), 0);
    return Math.max(0, refundTotal - otherPayments);
}

export function getOriginalStoreCreditPaid(order, pos) {
    const refundedLine = order.lines.find((line) => line.refunded_orderline_id);
    if (!refundedLine) {
        return 0;
    }
    const originalOrder = refundedLine.refunded_orderline_id.order_id;
    if (!originalOrder) {
        return 0;
    }
    return getStoreCreditUsedOnOrder(originalOrder, pos);
}

export function getStoreCreditRemainingBalance(order, pos) {
    const partner = order.getPartner();
    if (!partner || !isAveaCreditEnabled(pos)) {
        return 0;
    }
    const startingBalance = getPartnerStoreCreditBalance(partner);
    const used = getStoreCreditUsedOnOrder(order, pos);
    if (order.isRefund) {
        return startingBalance + used;
    }
    return Math.max(0, startingBalance - used);
}

export function formatStoreCreditAmount(pos, amount, partner) {
    let currency = pos.currency;
    const currencyRef = partner?.avea_credit_currency_id;
    if (currencyRef) {
        const currencyId = currencyRef.id ?? currencyRef;
        currency = pos.models["res.currency"].get(currencyId) ?? currency;
    }
    return pos.env.utils.formatCurrency(amount, currency);
}

export function validateStoreCreditPaymentAmount(pos, order, paymentLine) {
    if (!isStoreCreditPaymentMethod(paymentLine.payment_method_id)) {
        return null;
    }
    const partner = order.getPartner();
    if (!partner) {
        return _t("Select a customer before using Store Credit.");
    }
    const amount = Math.abs(paymentLine.getAmount());
    if (amount <= 0) {
        return null;
    }
    if (order.isRefund) {
        const maxRefund = getMaxStoreCreditRefundTotal(order, pos);
        const otherPayments = order.payment_ids.filter(
            (payment) =>
                isStoreCreditPaymentMethod(payment.payment_method_id) &&
                !payment.is_change &&
                payment.uuid !== paymentLine.uuid
        );
        const requestedTotal =
            amount + otherPayments.reduce((sum, payment) => sum + Math.abs(payment.getAmount()), 0);
        if (requestedTotal > maxRefund + 0.00001) {
            return _t(
                "Only %s Store Credit can be refunded to this customer for this order.",
                formatStoreCreditAmount(pos, maxRefund, partner)
            );
        }
        return null;
    }
    const available = getAvailableStoreCreditForOrder(order, pos, paymentLine);
    if (amount > available + 0.00001) {
        return _t(
            "Only %s Store Credit is available for this customer.",
            formatStoreCreditAmount(pos, available, partner)
        );
    }
    return null;
}

export function validateOrderStoreCredit(pos, order) {
    const storeCreditPayments = order.payment_ids.filter(
        (payment) => isStoreCreditPaymentMethod(payment.payment_method_id) && !payment.is_change
    );
    if (!storeCreditPayments.length) {
        return null;
    }
    for (const paymentLine of storeCreditPayments) {
        const message = validateStoreCreditPaymentAmount(pos, order, paymentLine);
        if (message) {
            return message;
        }
    }
    return null;
}
