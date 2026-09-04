/** @odoo-module **/

import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { TextInputPopup } from "@point_of_sale/app/components/popups/text_input_popup/text_input_popup";
import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";

const NON_PROMO_PROGRAM_TYPES = new Set(["loyalty", "ewallet", "gift_card"]);

patch(PaymentScreen.prototype, {
    get aveaAppliedPromotions() {
        const lines = this.currentOrder._get_reward_lines?.() || [];
        return lines.filter((line) => {
            const programType = line.reward_id?.program_id?.program_type;
            return programType && !NON_PROMO_PROGRAM_TYPES.has(programType);
        });
    },

    get hasAveaPromotionsApplied() {
        return this.aveaAppliedPromotions.length > 0;
    },

    get canEnterPromoCode() {
        return typeof this.pos.activateCode === "function";
    },

    aveaPromotionLabel(line) {
        return (
            line.reward_id?.program_id?.name ||
            line.reward_id?.description ||
            _t("Promotion")
        );
    },

    async clickEnterPromoCode() {
        if (!this.canEnterPromoCode) {
            return;
        }
        this.dialog.add(TextInputPopup, {
            title: _t("Promo Code"),
            placeholder: _t("Enter promo code"),
            getPayload: async (code) => {
                code = code.trim();
                if (!code) {
                    return;
                }
                const result = await this.pos.activateCode(code);
                if (result !== true) {
                    this.dialog.add(AlertDialog, {
                        title: _t("Promo Code"),
                        body: result || _t("Invalid or expired promo code."),
                    });
                    return;
                }
                if (typeof this.pos.updateRewards === "function") {
                    await this.pos.updateRewards();
                }
            },
        });
    },
});
