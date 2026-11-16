/** @odoo-module **/

import { FormController } from "@web/views/form/form_controller";
import { formView } from "@web/views/form/form_view";
import { registry } from "@web/core/registry";
import { patch } from "@web/core/utils/patch";
import { onMounted } from "@odoo/owl";

const ACCOUNT_MODEL = "account.account";
const ACCOUNT_LIST_ACTION = "avea_till.action_avea_account_manager";
const ASSET_LIST_ACTION = "avea_till.action_avea_asset_account_manager";

export class AveaAccountFormController extends FormController {
    setup() {
        super.setup();
        onMounted(() => this._enterAccountEditMode());
    }

    get className() {
        const base = super.className || "";
        return `${base} o_avea_workspace o_avea_workspace--account`.trim();
    }

    get display() {
        return {
            ...super.display,
            controlPanel: false,
        };
    }

    async _enterAccountEditMode() {
        const root = this.model?.root;
        if (!root || root.isInEdition) {
            return;
        }
        try {
            if (typeof this.edit === "function") {
                await this.edit();
                return;
            }
            if (typeof root.switchMode === "function") {
                await root.switchMode("edit");
            }
        } catch {
            // Odoo 19 forms are already in edit mode.
        }
    }
}

registry.category("views").add("avea_account_form", {
    ...formView,
    Controller: AveaAccountFormController,
    props: (genericProps, view) => {
        const props = formView.props(genericProps, view);
        return {
            ...props,
            preventEdit: false,
        };
    },
});

patch(FormController.prototype, {
    _isAveaAccountForm() {
        if ((this.props.resModel || this.model?.config?.resModel) !== ACCOUNT_MODEL) {
            return false;
        }
        const jsClass = this.props.archInfo?.jsClass || this.model?.config?.archInfo?.jsClass;
        return jsClass === "avea_account_form";
    },

    _accountListAction() {
        if (this.props.context?.avea_asset_workspace) {
            return ASSET_LIST_ACTION;
        }
        return ACCOUNT_LIST_ACTION;
    },

    async _returnToAccountList() {
        await this.actionService.doAction(this._accountListAction());
    },

    async beforeExecuteActionButton(clickParams) {
        if (clickParams.special === "cancel" && this._isAveaAccountForm()) {
            await this.discard();
            await this._returnToAccountList();
            return false;
        }
        return await super.beforeExecuteActionButton(clickParams);
    },

    async afterExecuteActionButton(clickParams) {
        await super.afterExecuteActionButton?.(clickParams);
        if (clickParams.special === "save" && this._isAveaAccountForm()) {
            await this._returnToAccountList();
        }
    },
});
