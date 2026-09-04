/** @odoo-module **/

import { FormController } from "@web/views/form/form_controller";
import { patch } from "@web/core/utils/patch";

/**
 * Promotion forms hide the standard control panel, so Cancel must discard
 * without triggering the "missing required fields" save path.
 */
patch(FormController.prototype, {
    async beforeExecuteActionButton(clickParams) {
        const resModel = this.props.resModel || this.model?.config?.resModel;
        if (clickParams.special === "cancel" && resModel === "avea.promotion") {
            await this.discard();
            return false;
        }
        return await super.beforeExecuteActionButton(clickParams);
    },
});
