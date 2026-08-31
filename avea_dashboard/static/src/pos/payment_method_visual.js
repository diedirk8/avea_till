/** @odoo-module **/

export function getPaymentMethodVisualKind(paymentMethod) {
    if (!paymentMethod) {
        return "other";
    }
    if (paymentMethod.is_avea_store_credit) {
        return "store_credit";
    }
    if (paymentMethod.type === "cash" || paymentMethod.is_cash_count) {
        return "cash";
    }
    const name = (paymentMethod.name || "").toLowerCase();
    if (paymentMethod.type === "bank") {
        if (name.includes("eft") || name.includes("transfer")) {
            return "eft";
        }
        return "card";
    }
    return "other";
}

export function paymentMethodIconClass(paymentMethod) {
    const kind = getPaymentMethodVisualKind(paymentMethod);
    const icons = {
        cash: "fa fa-money",
        card: "fa fa-credit-card",
        eft: "fa fa-university",
        store_credit: "fa fa-id-card-o",
        other: "fa fa-circle-o",
    };
    return `avea-pm-icon ${icons[kind] || icons.other}`;
}

export function paymentMethodButtonClass(paymentMethod, extra = {}) {
    const kind = getPaymentMethodVisualKind(paymentMethod);
    return {
        "avea-pm-btn": true,
        "avea-pm-cash": kind === "cash",
        "avea-pm-card": kind === "card",
        "avea-pm-eft": kind === "eft",
        "avea-pm-store-credit": kind === "store_credit",
        ...extra,
    };
}
