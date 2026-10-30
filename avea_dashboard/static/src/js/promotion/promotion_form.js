/** @odoo-module **/

import { FormController } from "@web/views/form/form_controller";
import { formView } from "@web/views/form/form_view";
import { registry } from "@web/core/registry";
import { patch } from "@web/core/utils/patch";

const PROMOTION_MODEL = "avea.promotion";
const PROMOTION_LIST_ACTION = "avea_till.action_avea_promotion";

export class AveaPromotionFormController extends FormController {
    get className() {
        const base = super.className || "";
        return `${base} o_avea_workspace o_avea_workspace--promotion`.trim();
    }
}

registry.category("views").add("avea_promotion_form", {
    ...formView,
    Controller: AveaPromotionFormController,
});

/**
 * Promotion forms hide the standard control panel, so Cancel must discard
 * without triggering the "missing required fields" save path. Save and Cancel
 * both return to the promotions list.
 */
patch(FormController.prototype, {
    _isAveaPromotionForm() {
        return (this.props.resModel || this.model?.config?.resModel) === PROMOTION_MODEL;
    },

    async _returnToPromotionList() {
        await this.actionService.doAction(PROMOTION_LIST_ACTION);
    },

    async beforeExecuteActionButton(clickParams) {
        if (clickParams.special === "cancel" && this._isAveaPromotionForm()) {
            await this.discard();
            await this._returnToPromotionList();
            return false;
        }
        return await super.beforeExecuteActionButton(clickParams);
    },

    async afterExecuteActionButton(clickParams) {
        await super.afterExecuteActionButton?.(clickParams);
        if (clickParams.special === "save" && this._isAveaPromotionForm()) {
            await this._returnToPromotionList();
        }
    },
});
