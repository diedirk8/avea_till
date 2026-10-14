/** @odoo-module **/

import { FormController } from "@web/views/form/form_controller";
import { patch } from "@web/core/utils/patch";

const SALES_PLATFORM_MODEL = "avea.sales.platform";
const SALES_PLATFORM_LIST_ACTION = "avea_till.action_avea_sales_platform";

patch(FormController.prototype, {
    _isAveaSalesPlatformForm() {
        return (this.props.resModel || this.model?.config?.resModel) === SALES_PLATFORM_MODEL;
    },

    async _returnToSalesPlatformList() {
        await this.actionService.doAction(SALES_PLATFORM_LIST_ACTION);
    },

    async beforeExecuteActionButton(clickParams) {
        if (clickParams.special === "cancel" && this._isAveaSalesPlatformForm()) {
            await this.discard();
            await this._returnToSalesPlatformList();
            return false;
        }
        return await super.beforeExecuteActionButton(clickParams);
    },

    async afterExecuteActionButton(clickParams) {
        await super.afterExecuteActionButton?.(clickParams);
        if (clickParams.special === "save" && this._isAveaSalesPlatformForm()) {
            await this._returnToSalesPlatformList();
        }
    },
});
