/** @odoo-module **/

import { FormController } from "@web/views/form/form_controller";
import { formView } from "@web/views/form/form_view";
import { registry } from "@web/core/registry";
import { patch } from "@web/core/utils/patch";
import { onMounted, onWillUnmount } from "@odoo/owl";

const PROMOTION_MODEL = "avea.promotion";
const PROMOTION_LIST_ACTION = "avea_till.action_avea_promotion";
const ACTION_MANAGER_SCROLL_CLASS = "o_avea_promotion_form_action_manager";

export class AveaPromotionFormController extends FormController {
    setup() {
        super.setup();
        onMounted(() => this._setupScrollShell());
        onWillUnmount(() => this._teardownScrollShell());
    }

    get className() {
        const base = super.className || "";
        return `${base} o_avea_workspace o_avea_workspace--promotion`.trim();
    }

    _actionManagerEl() {
        return document.querySelector(".o_action_manager");
    }

    _setupScrollShell() {
        this._actionManagerEl()?.classList.add(ACTION_MANAGER_SCROLL_CLASS);
    }

    _teardownScrollShell() {
        this._actionManagerEl()?.classList.remove(ACTION_MANAGER_SCROLL_CLASS);
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
