/** @odoo-module **/

import { ClosePosPopup } from "@point_of_sale/app/components/popups/closing_popup/closing_popup";
import { patch } from "@web/core/utils/patch";

patch(ClosePosPopup.prototype, {
    isAveaStoreCreditPm(pm) {
        return Boolean(
            this.pos.models["pos.payment.method"].get(pm.id)?.is_avea_store_credit
        );
    },

    requiresClosingCount(pm) {
        return (
            pm.type === "bank" && pm.number !== 0 && !this.isAveaStoreCreditPm(pm)
        );
    },
});
