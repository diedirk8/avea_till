/** @odoo-module **/

import { FormController } from "@web/views/form/form_controller";
import { formView } from "@web/views/form/form_view";
import { registry } from "@web/core/registry";

export class AveaStockHistoryFormController extends FormController {
    get className() {
        const base = super.className || "";
        return `${base} o_avea_workspace o_avea_workspace--stock o_avea_workspace--stock-history`.trim();
    }
}

registry.category("views").add("avea_stock_history_form", {
    ...formView,
    Controller: AveaStockHistoryFormController,
});
