/** @odoo-module **/

import { onWillStart } from "@odoo/owl";
import { OrderReceipt } from "@point_of_sale/app/screens/receipt_screen/receipt/order_receipt";
import { usePos } from "@point_of_sale/app/hooks/pos_hook";
import { patch } from "@web/core/utils/patch";
import {
    formatStoreCreditAmount,
    getStoreCreditRemainingBalance,
    getStoreCreditUsedOnOrder,
    getPartnerStoreCreditBalance,
    isAveaCreditEnabled,
} from "./store_credit";
import {
    aveaPrintLayoutClass,
    aveaPrintShow,
    getPrintReceiptCompany,
    isAveaPrintCustomizeEnabled,
    loadAveaPrintReceiptCompanySettings,
} from "./print_receipt_settings";

patch(OrderReceipt.prototype, {
    setup() {
        super.setup(...arguments);
        this.pos = usePos();
        onWillStart(async () => {
            await loadAveaPrintReceiptCompanySettings(this.pos);
        });
    },

    get aveaPrintCompany() {
        return getPrintReceiptCompany(this.order, this.pos);
    },

    get aveaPrintCustomizeEnabled() {
        return isAveaPrintCustomizeEnabled(this.order, this.pos);
    },

    aveaPrintShow(fieldName) {
        return aveaPrintShow(this.order, fieldName, this.pos);
    },

    get aveaPrintLayoutClass() {
        const layoutClass = aveaPrintLayoutClass(this.order, this.pos);
        return this.aveaPrintCustomizeEnabled
            ? `${layoutClass} avea-pos-receipt--customized`
            : layoutClass;
    },

    get storeCreditUsed() {
        if (!this.order.getPartner() || !isAveaCreditEnabled(this.pos)) {
            return 0;
        }
        return getStoreCreditUsedOnOrder(this.order, this.pos);
    },

    get showStoreCreditReceiptInfo() {
        if (!this.aveaPrintCustomizeEnabled) {
            return this.storeCreditUsed > 0;
        }
        if (!this.aveaPrintShow("avea_print_receipt_show_store_credit_balance")) {
            return false;
        }
        const partner = this.order.getPartner();
        if (!partner || !isAveaCreditEnabled(this.pos)) {
            return false;
        }
        return this.storeCreditUsed > 0 || getPartnerStoreCreditBalance(partner) > 0;
    },

    get storeCreditRemainingBalance() {
        if (!this.showStoreCreditReceiptInfo) {
            return 0;
        }
        if (this.storeCreditUsed > 0) {
            return getStoreCreditRemainingBalance(this.order, this.pos);
        }
        const partner = this.order.getPartner();
        return partner ? getPartnerStoreCreditBalance(partner) : 0;
    },

    formatStoreCreditAmount(amount) {
        return formatStoreCreditAmount(this.pos, amount, this.order.getPartner());
    },

    get aveaShowLoyaltyBalance() {
        if (!this.aveaPrintCustomizeEnabled || !this.aveaPrintShow("avea_print_receipt_show_loyalty_balance")) {
            return false;
        }
        const partner = this.order.getPartner();
        if (!partner || typeof this.pos.getLoyaltyCards !== "function") {
            return false;
        }
        const cards = (this.pos.getLoyaltyCards(partner) || []).filter(
            (card) => card.program_id?.program_type === "loyalty" && card.points
        );
        return cards.length > 0;
    },

    get aveaLoyaltyBalanceLines() {
        const partner = this.order.getPartner();
        if (!partner || typeof this.pos.getLoyaltyCards !== "function") {
            return [];
        }
        return (this.pos.getLoyaltyCards(partner) || [])
            .filter((card) => card.program_id?.program_type === "loyalty" && card.points)
            .map((card) => ({
                label: card.program_id?.name || "Loyalty",
                value: card.points,
            }));
    },

    get aveaShowCustomerAccountBalance() {
        if (
            !this.aveaPrintCustomizeEnabled ||
            !this.aveaPrintShow("avea_print_receipt_show_customer_account_balance")
        ) {
            return false;
        }
        const partner = this.order.getPartner();
        return Boolean(partner?.avea_customer_account_balance);
    },

    get aveaCustomerAccountBalance() {
        const partner = this.order.getPartner();
        if (!partner?.avea_customer_account_balance) {
            return 0;
        }
        return partner.avea_customer_account_balance;
    },

    get aveaTotalAmountPaid() {
        return this.paymentLines.reduce((sum, line) => sum + line.getAmount(), 0);
    },

    get aveaCustomFooterMessage() {
        if (!this.aveaPrintCustomizeEnabled) {
            return "";
        }
        return (this.aveaPrintCompany?.avea_print_receipt_footer_message || "").trim();
    },

    get aveaShowProductsSection() {
        return !this.aveaPrintCustomizeEnabled || this.aveaPrintShow("avea_print_receipt_show_products");
    },
});
