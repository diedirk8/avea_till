/** @odoo-module **/

import { PaymentScreenPaymentLines } from "@point_of_sale/app/screens/payment_screen/payment_lines/payment_lines";
import { patch } from "@web/core/utils/patch";
import { getPaymentMethodVisualKind } from "./payment_method_visual";

patch(PaymentScreenPaymentLines.prototype, {
    selectedLineClass(line) {
        const kind = getPaymentMethodVisualKind(line.payment_method_id);
        return {
            ...super.selectedLineClass(line),
            "avea-pm-line": true,
            "avea-pm-cash": kind === "cash",
            "avea-pm-card": kind === "card",
            "avea-pm-eft": kind === "eft",
            "avea-pm-store-credit": kind === "store_credit",
        };
    },
    unselectedLineClass(line) {
        const kind = getPaymentMethodVisualKind(line.payment_method_id);
        return {
            ...super.unselectedLineClass(line),
            "avea-pm-line": true,
            "avea-pm-cash": kind === "cash",
            "avea-pm-card": kind === "card",
            "avea-pm-eft": kind === "eft",
            "avea-pm-store-credit": kind === "store_credit",
        };
    },
});
