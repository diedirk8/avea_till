/** @odoo-module **/

import { onWillStart } from "@odoo/owl";
import { ReceiptHeader } from "@point_of_sale/app/screens/receipt_screen/receipt/receipt_header/receipt_header";
import { usePos } from "@point_of_sale/app/hooks/pos_hook";
import { patch } from "@web/core/utils/patch";
import {
    aveaPrintLogoClass,
    aveaPrintLogoStyle,
    aveaPrintShow,
    isAveaPrintCustomizeEnabled,
    loadAveaPrintReceiptCompanySettings,
} from "./print_receipt_settings";

patch(ReceiptHeader.prototype, {
    setup() {
        super.setup(...arguments);
        this.pos = usePos();
        onWillStart(async () => {
            await loadAveaPrintReceiptCompanySettings(this.pos);
        });
    },

    get aveaPrintCustomizeEnabled() {
        return isAveaPrintCustomizeEnabled(this.order, this.pos);
    },

    aveaPrintShow(fieldName) {
        return aveaPrintShow(this.order, fieldName, this.pos);
    },

    get aveaPrintLogoClass() {
        return aveaPrintLogoClass(this.order, this.pos);
    },

    get aveaPrintLogoStyle() {
        return aveaPrintLogoStyle(this.order, this.pos);
    },
});
