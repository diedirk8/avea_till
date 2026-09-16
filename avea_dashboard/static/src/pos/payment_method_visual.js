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
        store_credit: "fa fa-ticket",
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

/**
 * Normalize POS payment-method relations (array or model collection) to a plain array.
 */
export function normalizePaymentMethodSource(source) {
    if (!source) {
        return [];
    }
    if (Array.isArray(source)) {
        return source;
    }
    if (typeof source.map === "function") {
        return source.map((item) => item);
    }
    return [];
}

/**
 * Native PaymentScreen.setup() calls payment_method_ids.slice(). Materialize first.
 */
export function materializeConfigPaymentMethods(pos) {
    const config = pos?.config;
    if (!config) {
        return;
    }
    let methods = config.payment_method_ids;
    if (!methods) {
        config.payment_method_ids = pos.models["pos.payment.method"]?.getAll?.() ?? [];
        return;
    }
    if (typeof methods.slice !== "function" && typeof methods.map === "function") {
        config.payment_method_ids = methods.map((paymentMethod) => paymentMethod);
    }
}

/**
 * Build the sorted payment-method list for the Avea payment screen.
 * Always returns an array so OWL t-foreach never receives undefined.
 */
export function buildAveaPaymentMethodList(source, storeCreditMethod = null) {
    const methods = [...normalizePaymentMethodSource(source)];
    if (storeCreditMethod && !methods.some((method) => method.id === storeCreditMethod.id)) {
        methods.push(storeCreditMethod);
    }
    const kindOrder = { card: 0, cash: 1, eft: 2, store_credit: 3, other: 4 };
    return methods.sort((a, b) => {
        const ka = getPaymentMethodVisualKind(a);
        const kb = getPaymentMethodVisualKind(b);
        const byKind = (kindOrder[ka] ?? 4) - (kindOrder[kb] ?? 4);
        if (byKind !== 0) {
            return byKind;
        }
        return (a.sequence || 0) - (b.sequence || 0);
    });
}
