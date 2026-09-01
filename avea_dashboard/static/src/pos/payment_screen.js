/** @odoo-module **/

import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { _t } from "@web/core/l10n/translation";
import { formatFloat } from "@web/core/utils/numbers";
import { onWillUnmount, useState } from "@odoo/owl";
import { patch } from "@web/core/utils/patch";
import {
    getPaymentMethodVisualKind,
    paymentMethodButtonClass,
    paymentMethodIconClass,
} from "./payment_method_visual";

patch(PaymentScreen.prototype, {
    setup() {
        super.setup(...arguments);
        this._aveaStoreCreditLastAmount = null;
        this.aveaClock = useState({ now: new Date() });
        this._aveaClockTimer = setInterval(() => {
            this.aveaClock.now = new Date();
        }, 1000);
        onWillUnmount(() => clearInterval(this._aveaClockTimer));
    },

    getPaymentMethodVisualKind(paymentMethod) {
        return getPaymentMethodVisualKind(paymentMethod);
    },

    paymentMethodIconClass(paymentMethod) {
        return paymentMethodIconClass(paymentMethod);
    },

    paymentMethodButtonClass(paymentMethod) {
        return paymentMethodButtonClass(paymentMethod, {
            "opacity-50":
                this.isStoreCreditPaymentDisabled(paymentMethod) ||
                (this.pos.paymentTerminalInProgress &&
                    paymentMethod.use_payment_terminal),
            "d-flex justify-content-between align-items-center": true,
            "avea-pm-selected": this.isPaymentMethodOnOrder(paymentMethod),
        });
    },

    paymentMethodCardClass(paymentMethod) {
        const kind = getPaymentMethodVisualKind(paymentMethod);
        return {
            "avea-pay-card": true,
            "avea-pay-card-cash": kind === "cash",
            "avea-pay-card-card": kind === "card",
            "avea-pay-card-eft": kind === "eft",
            "avea-pay-card-store-credit": kind === "store_credit",
            "avea-pay-card-other": kind === "other",
            "avea-pay-card-selected": this.isPaymentMethodOnOrder(paymentMethod),
            "avea-pay-card-disabled":
                this.isStoreCreditPaymentDisabled(paymentMethod) ||
                (this.pos.paymentTerminalInProgress &&
                    paymentMethod.use_payment_terminal),
        };
    },

    paymentMethodTitle(paymentMethod) {
        const kind = getPaymentMethodVisualKind(paymentMethod);
        const titles = {
            cash: _t("Cash"),
            card: _t("Card"),
            eft: _t("EFT"),
            store_credit: _t("Store Credit"),
        };
        return titles[kind] || paymentMethod?.name || "";
    },

    paymentMethodSubtitle(paymentMethod) {
        const kind = getPaymentMethodVisualKind(paymentMethod);
        const subtitles = {
            cash: _t("Pay with cash"),
            card: _t("Pay with card"),
            eft: _t("Electronic transfer"),
            store_credit: _t("Pay with store credit"),
        };
        return subtitles[kind] || "";
    },


    isPaymentMethodOnOrder(paymentMethod) {
        return this.paymentLines.some(
            (line) => line.payment_method_id?.id === paymentMethod?.id
        );
    },

    /**
     * Cash is the keyboard/numpad fallback when the cashier has not
     * clicked a payment method. This does not pre-select Cash visually;
     * a cash line is only created when an amount is actually entered.
     */
    _aveaKeyboardFallbackPaymentMethod() {
        return (
            this.payment_methods_from_config.find(
                (method) => method.type === "cash" || method.is_cash_count
            ) || this.payment_methods_from_config[0]
        );
    },

    paymentMethodImage(id) {
        const method =
            this.pos.models["pos.payment.method"].get(id) || this.paymentMethod;
        if (method?.image) {
            return `/web/image/pos.payment.method/${id}/image`;
        }
        if (method?.type === "cash") {
            return "/point_of_sale/static/src/img/money.png";
        }
        if (method?.type === "pay_later") {
            return "/point_of_sale/static/src/img/pay-later.png";
        }
        return "/point_of_sale/static/src/img/card-bank.png";
    },

    getNumpadButtons() {
        const extraClass = {
            "+10": "avea-key avea-key-quick",
            "+20": "avea-key avea-key-quick",
            "+50": "avea-key avea-key-quick",
            "-": "avea-key avea-key-sign",
            Backspace: "avea-key avea-key-back",
        };
        const decimal = this.env.services.localization.decimalPoint;
        extraClass[decimal] = "avea-key avea-key-decimal";
        return super.getNumpadButtons().map((button) => ({
            ...button,
            class: `${button.class || ""} ${extraClass[button.value] || "avea-key"}`.trim(),
            text: button.value === "Backspace" ? "✕" : button.text,
        }));
    },

    get availablePaymentMethods() {
        const methods = [...this.pos.config.payment_method_ids];
        const storeCredit = this.pos.getStoreCreditPaymentMethod();
        if (storeCredit && !methods.some((method) => method.id === storeCredit.id)) {
            methods.push(storeCredit);
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
    },

    get showPartnerStoreCredit() {
        return this.currentOrder.getPartner() && this.pos.isAveaCreditEnabled();
    },

    get partnerStoreCreditBalance() {
        const partner = this.currentOrder.getPartner();
        if (!partner) {
            return 0;
        }
        return this.pos.getPartnerStoreCreditBalance(partner);
    },

    get partnerDisplayName() {
        return this.currentOrder.getPartner()?.name || _t("Walk-in Customer");
    },

    get partnerLoyaltyPointsLabel() {
        const partner = this.currentOrder.getPartner();
        if (!partner || typeof this.pos.getLoyaltyCards !== "function") {
            return "—";
        }
        const cards = (this.pos.getLoyaltyCards(partner) || []).filter(
            (card) =>
                card &&
                card.program_id?.program_type === "loyalty" &&
                !card.isExpired?.()
        );
        if (!cards.length) {
            return "—";
        }
        const points = cards.reduce((sum, card) => {
            const balance = Number(card.points) || 0;
            const spent = (this.currentOrder._get_reward_lines?.() || [])
                .filter((line) => line.coupon_id?.id === card.id)
                .reduce((spentSum, line) => spentSum + (Number(line.points_cost) || 0), 0);
            return sum + Math.max(0, balance - spent);
        }, 0);
        return _t("%s pts", formatFloat(points, { digits: [69, 2] }));
    },

    get partnerAvailableCreditLabel() {
        const partner = this.currentOrder.getPartner();
        if (!partner || !this.pos.isAveaCreditEnabled?.()) {
            return "—";
        }
        return this.pos.formatStoreCreditAmount(this.partnerStoreCreditBalance, partner);
    },

    _aveaLoyaltyClaimableRewards() {
        const order = this.currentOrder;
        if (!order || typeof order.getClaimableRewards !== "function") {
            return [];
        }
        return (order.getClaimableRewards() || []).filter(
            ({ reward }) =>
                reward?.program_id?.program_type === "loyalty" &&
                reward.reward_type === "discount"
        );
    },

    get aveaLoyaltyRewardLines() {
        const lines = this.currentOrder._get_reward_lines?.() || [];
        return lines.filter(
            (line) => line.reward_id?.program_id?.program_type === "loyalty"
        );
    },

    get hasAveaLoyaltyApplied() {
        return this.aveaLoyaltyRewardLines.length > 0;
    },

    get canUseLoyaltyPoints() {
        if (this.currentOrder.isRefund || this.hasAveaLoyaltyApplied) {
            return false;
        }
        if (!this.currentOrder.getPartner()) {
            return false;
        }
        return this._aveaLoyaltyClaimableRewards().length > 0;
    },

    _aveaRewardLineAmount(line) {
        const raw =
            line.prices?.total_included ??
            (typeof line.getPriceWithTax === "function" ? line.getPriceWithTax() : null) ??
            (line.price_unit || 0) * (line.qty || 1);
        return Math.abs(Number(raw) || 0);
    },

    get aveaLoyaltyAppliedAmount() {
        return this.aveaLoyaltyRewardLines.reduce(
            (sum, line) => sum + this._aveaRewardLineAmount(line),
            0
        );
    },

    get aveaLoyaltyAppliedDisplay() {
        return this.env.utils.formatCurrency(this.aveaLoyaltyAppliedAmount);
    },

    async clickUseLoyaltyPoints() {
        if (!this.canUseLoyaltyPoints) {
            return;
        }
        const claimable = this._aveaLoyaltyClaimableRewards();
        if (!claimable.length) {
            this.dialog.add(AlertDialog, {
                title: _t("Loyalty Points"),
                body: _t("This customer does not have enough loyalty points to redeem on this order."),
            });
            return;
        }
        const { reward, coupon_id } = claimable[0];
        this.currentOrder.uiState.disabledRewards?.delete(reward.id);
        const result = this.currentOrder._applyReward(reward, coupon_id, {});
        if (result !== true) {
            this.dialog.add(AlertDialog, {
                title: _t("Loyalty Points"),
                body: result || _t("The reward could not be applied."),
            });
            return;
        }
        this.pos.updateRewards?.();
    },

    removeAveaLoyaltyReward() {
        const lines = [...this.aveaLoyaltyRewardLines];
        if (!lines.length) {
            return;
        }
        for (const line of lines) {
            if (line.reward_id?.id) {
                this.currentOrder.uiState.disabledRewards?.add(line.reward_id.id);
            }
        }
        for (const line of lines) {
            line.delete();
        }
        this.pos.updateRewards?.();
    },

    get orderTotalDisplay() {
        return this.env.utils.formatCurrency(this.currentOrder.totalDue);
    },

    get canValidatePayment() {
        return this.currentOrder.canBeValidated() && !this.currentOrder.isRefundInProcess();
    },

    get saleSummaryLines() {
        return (this.currentOrder.lines || []).filter((line) => !line.combo_parent_id);
    },

    get saleDiscountTotal() {
        return this.currentOrder.getTotalDiscount?.() || 0;
    },

    get saleDiscountDisplay() {
        if (!this.saleDiscountTotal) {
            return "";
        }
        return this.env.utils.formatCurrency(-Math.abs(this.saleDiscountTotal));
    },

    get showSaleSubtotal() {
        return (
            this.pos.config.iface_tax_included !== "total" &&
            !this.currentOrder.currency.isZero(this.currentOrder.amountTaxes)
        );
    },

    get saleSubtotalDisplay() {
        return this.env.utils.formatCurrency(this.currentOrder.priceExcl);
    },

    get paymentIsSettled() {
        return this.currentOrder.orderHasZeroRemaining;
    },

    get paymentShowsChange() {
        return (
            this.currentOrder.orderHasZeroRemaining &&
            !this.currentOrder.currency.isZero(this.currentOrder.change)
        );
    },

    get paymentStatusLabel() {
        return this.paymentShowsChange ? _t("Change") : _t("Remaining");
    },

    get paymentStatusAmount() {
        return this.env.utils.formatCurrency(
            this.paymentShowsChange ? this.currentOrder.change : this.currentOrder.remainingDue
        );
    },

    get aveaTillName() {
        return this.pos.config?.name || "";
    },

    get aveaCashierName() {
        const cashier = this.pos.cashier || this.pos.getCashier?.() || this.pos.user;
        return cashier?.name || "";
    },

    get aveaIsOnline() {
        return !this.pos.data?.network?.offline;
    },

    get aveaStatusTime() {
        return this.aveaClock.now.toLocaleTimeString(undefined, {
            hour: "2-digit",
            minute: "2-digit",
            hour12: false,
        });
    },

    get aveaStatusDate() {
        return this.aveaClock.now.toLocaleDateString(undefined, {
            day: "numeric",
            month: "short",
            year: "numeric",
        });
    },

    storeCreditAvailableLabel(paymentMethod) {
        if (!this.pos.isStoreCreditPaymentMethod(paymentMethod)) {
            return "";
        }
        const partner = this.currentOrder.getPartner();
        if (!partner) {
            return "";
        }
        return _t("Available %s", this.pos.formatStoreCreditAmount(
            this.partnerStoreCreditBalance,
            partner
        ));
    },

    isStoreCreditPaymentDisabled(paymentMethod) {
        return (
            this.pos.isStoreCreditPaymentMethod(paymentMethod) &&
            !this.pos.isStoreCreditPaymentAvailable(paymentMethod, this.currentOrder)
        );
    },

    async clickPaymentMethod(paymentMethod) {
        if (this.pos.isStoreCreditPaymentMethod(paymentMethod)) {
            await this._aveaRefreshCurrentPartnerStoreCredit();
        }
        if (this.isStoreCreditPaymentDisabled(paymentMethod)) {
            const partner = this.currentOrder.getPartner();
            this.dialog.add(AlertDialog, {
                title: _t("Store Credit"),
                body: partner
                    ? _t("No Store Credit is available for this customer.")
                    : _t("Select a customer before using Store Credit."),
            });
            return false;
        }
        return this.addNewPaymentLine(paymentMethod);
    },

    async onMounted() {
        super.onMounted(...arguments);
        await this._aveaRefreshCurrentPartnerStoreCredit();
        await this._aveaEnsurePartnerLoyaltyCards();
        this._aveaSetupRefundStoreCredit();
    },

    async _aveaEnsurePartnerLoyaltyCards() {
        const partner = this.currentOrder?.getPartner();
        if (!partner || typeof this.pos.fetchCoupons !== "function") {
            return;
        }
        const existing = this.pos.getLoyaltyCards?.(partner) || [];
        if (!existing.some((card) => card?.program_id?.program_type === "loyalty")) {
            try {
                await this.pos.fetchCoupons(
                    [
                        ["partner_id", "=", partner.id],
                        ["program_id.program_type", "=", "loyalty"],
                    ],
                    20
                );
                this.pos.computePartnerCouponIds?.();
            } catch {
                // Loyalty cards are display-only here; missing data shows "—".
            }
        }
        this.pos.updateRewards?.();
    },

    async _aveaRefreshCurrentPartnerStoreCredit() {
        const partner = this.currentOrder?.getPartner();
        if (!partner || !this.pos.isAveaCreditEnabled()) {
            return;
        }
        await this.pos.refreshPartnerStoreCreditBalance(partner.id);
    },

    _aveaSetupRefundStoreCredit() {
        const order = this.currentOrder;
        if (!order.isRefund || !this.pos.isAveaCreditEnabled()) {
            return;
        }
        const originalStoreCreditPaid = this.pos.getOriginalStoreCreditPaid(order);
        if (originalStoreCreditPaid <= 0) {
            return;
        }
        const storeCreditMethod = this.pos.getStoreCreditPaymentMethod();
        if (!storeCreditMethod) {
            return;
        }
        const hasStoreCreditLine = order.payment_ids.some((payment) =>
            this.pos.isStoreCreditPaymentMethod(payment.payment_method_id)
        );
        if (hasStoreCreditLine) {
            return;
        }
        const due = Math.abs(order.remainingDue);
        const storeCreditAmount = Math.min(originalStoreCreditPaid, due);
        if (storeCreditAmount <= 0) {
            return;
        }
        const result = order.addPaymentline(storeCreditMethod);
        if (result.status) {
            // Refund payment lines are negative; a positive amount leaves the
            // refund unpaid and blocks Validate.
            result.data.setAmount(-storeCreditAmount);
            this.numberBuffer.set((-storeCreditAmount).toString());
        }
    },

    async addNewPaymentLine(paymentMethod) {
        if (this.pos.isStoreCreditPaymentMethod(paymentMethod)) {
            const partner = this.currentOrder.getPartner();
            if (!partner) {
                this.dialog.add(AlertDialog, {
                    title: _t("Customer required"),
                    body: _t("Select a customer before using Store Credit."),
                });
                return false;
            }
            if (
                !this.currentOrder.isRefund &&
                !this.pos.isStoreCreditPaymentAvailable(paymentMethod, this.currentOrder)
            ) {
                this.dialog.add(AlertDialog, {
                    title: _t("Store Credit"),
                    body: _t("No Store Credit is available for this customer."),
                });
                return false;
            }
        }
        return super.addNewPaymentLine(...arguments);
    },

    updateSelectedPaymentline(amount = false) {
        // Odoo auto-creates a line with payment_methods_from_config[0]
        // (Card here) when the cashier types with no selected method.
        // Create Cash first so that path stays the same except for
        // which unpaid method receives the typed amount.
        if (this.paymentLines.every((line) => line.paid)) {
            const fallback = this._aveaKeyboardFallbackPaymentMethod();
            if (fallback) {
                this.currentOrder.addPaymentline(fallback);
            }
        }
        const line = this.selectedPaymentLine;
        const previousAmount = line?.getAmount() ?? 0;
        super.updateSelectedPaymentline(...arguments);
        if (!line || !this.pos.isStoreCreditPaymentMethod(line.payment_method_id)) {
            return;
        }
        const error = this.pos.validateStoreCreditPaymentAmount(this.currentOrder, line);
        if (error) {
            line.setAmount(previousAmount);
            this.numberBuffer.set(previousAmount ? previousAmount.toString() : "");
            this.dialog.add(AlertDialog, {
                title: _t("Store Credit"),
                body: error,
            });
        }
    },

    deletePaymentLine(uuid) {
        const line = this.paymentLines.find((paymentLine) => paymentLine.uuid === uuid);
        if (
            line &&
            this.pos.isStoreCreditPaymentMethod(line.payment_method_id) &&
            this.currentOrder.isRefund &&
            this.pos.getOriginalStoreCreditPaid(this.currentOrder) > 0
        ) {
            this.dialog.add(AlertDialog, {
                title: _t("Store Credit refund"),
                body: _t(
                    "Store Credit refunds must return to the customer's Store Credit balance."
                ),
            });
            return;
        }
        return super.deletePaymentLine(...arguments);
    },
});
