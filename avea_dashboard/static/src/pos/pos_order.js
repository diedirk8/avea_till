/** @odoo-module **/

import { PosOrder } from "@point_of_sale/app/models/pos_order";
import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";
import { isAveaExchangeOrder } from "./store_credit";

patch(PosOrder.prototype, {
    setup(vals) {
        super.setup(...arguments);
        if (vals.avea_is_exchange) {
            this.avea_is_exchange = true;
        }
    },

    serializeForORM(opts = {}) {
        const data = super.serializeForORM(opts);
        if (this.avea_is_exchange) {
            data.avea_is_exchange = true;
        }
        return data;
    },

    setToInvoice() {
        this.to_invoice = false;
    },

    isToInvoice() {
        return false;
    },

    get isExchange() {
        return isAveaExchangeOrder(this);
    },

    getAveaExchangeReturnTotal() {
        return (this.lines || [])
            .filter((line) => line.refunded_orderline_id)
            .reduce((sum, line) => {
                const raw =
                    line.prices?.total_included ??
                    (typeof line.getPriceWithTax === "function" ? line.getPriceWithTax() : null) ??
                    Math.abs((line.price_unit || 0) * (line.qty || 0));
                return sum + Math.abs(Number(raw) || 0);
            }, 0);
    },

    getName() {
        let name = this.floatingOrderName || "";
        if (this.isExchange) {
            name += _t(" (Exchange)");
        } else if (this.isRefund) {
            name += _t(" (Refund)");
        }
        return name;
    },
});
