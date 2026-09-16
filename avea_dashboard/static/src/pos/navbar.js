/** @odoo-module **/

import { Navbar } from "@point_of_sale/app/components/navbar/navbar";
import { patch } from "@web/core/utils/patch";

patch(Navbar.prototype, {
    get showIssueStoreCreditMenu() {
        return typeof this.pos.canIssueStoreCredit === "function"
            ? this.pos.canIssueStoreCredit()
            : false;
    },
    get showCashUpMenu() {
        return typeof this.pos.canCashUpOwnTill === "function"
            ? this.pos.canCashUpOwnTill()
            : false;
    },
    issueStoreCredit() {
        this.pos.issueStoreCredit();
    },
    openCashUp() {
        this.pos.openCashUp();
    },
});
