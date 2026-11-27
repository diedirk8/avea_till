/** @odoo-module **/

import { FormController } from "@web/views/form/form_controller";
import { formView } from "@web/views/form/form_view";
import { registry } from "@web/core/registry";
import { onMounted, onWillUnmount } from "@odoo/owl";

const ACTION_MANAGER_SCROLL_CLASS = "o_avea_stock_history_action_manager";

export class AveaStockHistoryFormController extends FormController {
    setup() {
        super.setup();
        onMounted(() => this._setupScrollShell());
        onWillUnmount(() => this._teardownScrollShell());
    }

    get className() {
        const base = super.className || "";
        return `${base} o_avea_workspace o_avea_workspace--stock o_avea_workspace--stock-history o_avea_workspace--stock-history-form`.trim();
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

registry.category("views").add("avea_stock_history_form", {
    ...formView,
    Controller: AveaStockHistoryFormController,
});
