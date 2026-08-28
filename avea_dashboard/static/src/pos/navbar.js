/** @odoo-module **/

import { Navbar } from "@point_of_sale/app/components/navbar/navbar";
import { patch } from "@web/core/utils/patch";

patch(Navbar.prototype, {
    get showIssueStoreCreditMenu() {
        return this.pos.canIssueStoreCredit();
    },
    get showCashUpMenu() {
        return this.pos.canCashUpOwnTill();
    },
    issueStoreCredit() {
        this.pos.issueStoreCredit();
    },
    openCashUp() {
        this.pos.openCashUp();
    },
});
