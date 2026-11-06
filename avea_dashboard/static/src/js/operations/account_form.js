/** @odoo-module **/

import { FormController } from "@web/views/form/form_controller";
import { formView } from "@web/views/form/form_view";
import { registry } from "@web/core/registry";
import { patch } from "@web/core/utils/patch";

const ACCOUNT_MODEL = "account.account";
const ACCOUNT_LIST_ACTION = "avea_till.action_avea_account_manager";

export class AveaAccountFormController extends FormController {
    get className() {
        const base = super.className || "";
        return `${base} o_avea_workspace o_avea_workspace--account`.trim();
    }
}

registry.category("views").add("avea_account_form", {
    ...formView,
    Controller: AveaAccountFormController,
});

patch(FormController.prototype, {
    _isAveaAccountForm() {
        if ((this.props.resModel || this.model?.config?.resModel) !== ACCOUNT_MODEL) {
            return false;
        }
        const jsClass = this.props.archInfo?.jsClass || this.model?.config?.archInfo?.jsClass;
        return jsClass === "avea_account_form";
    },

    async _returnToAccountList() {
        await this.actionService.doAction(ACCOUNT_LIST_ACTION);
    },

    async beforeExecuteActionButton(clickParams) {
        if (clickParams.special === "cancel" && this._isAveaAccountForm()) {
            await this.discard();
            await this._returnToAccountList();
            return false;
        }
        return await super.beforeExecuteActionButton(clickParams);
    },
});
