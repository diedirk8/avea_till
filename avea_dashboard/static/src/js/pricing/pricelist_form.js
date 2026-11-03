/** @odoo-module **/

import { FormController } from "@web/views/form/form_controller";
import { formView } from "@web/views/form/form_view";
import { registry } from "@web/core/registry";
import { patch } from "@web/core/utils/patch";

const PRICELIST_MODEL = "product.pricelist";
const PRICELIST_LIST_ACTION = "avea_till.action_avea_pricelist_manager";

export class AveaPricelistFormController extends FormController {
    get className() {
        const base = super.className || "";
        return `${base} o_avea_workspace o_avea_workspace--pricelist`.trim();
    }
}

registry.category("views").add("avea_pricelist_form", {
    ...formView,
    Controller: AveaPricelistFormController,
});

patch(FormController.prototype, {
    _isAveaPricelistForm() {
        if ((this.props.resModel || this.model?.config?.resModel) !== PRICELIST_MODEL) {
            return false;
        }
        const jsClass = this.props.archInfo?.jsClass || this.model?.config?.archInfo?.jsClass;
        return jsClass === "avea_pricelist_form";
    },

    async _returnToPricelistList() {
        await this.actionService.doAction(PRICELIST_LIST_ACTION);
    },

    async beforeExecuteActionButton(clickParams) {
        if (clickParams.special === "cancel" && this._isAveaPricelistForm()) {
            await this.discard();
            await this._returnToPricelistList();
            return false;
        }
        return await super.beforeExecuteActionButton(clickParams);
    },

    async afterExecuteActionButton(clickParams) {
        await super.afterExecuteActionButton?.(clickParams);
        if (clickParams.special === "save" && this._isAveaPricelistForm()) {
            await this._returnToPricelistList();
        }
    },
});
