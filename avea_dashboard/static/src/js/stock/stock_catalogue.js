/** @odoo-module **/

import { FormController } from "@web/views/form/form_controller";
import { ListController } from "@web/views/list/list_controller";
import { listView } from "@web/views/list/list_view";
import { registry } from "@web/core/registry";
import { patch } from "@web/core/utils/patch";

/**
 * Stock Item / Stock Count forms hide the control panel, so Cancel must discard
 * without triggering the missing-required-fields save path.
 */
patch(FormController.prototype, {
    async beforeExecuteActionButton(clickParams) {
        const resModel = this.props.resModel || this.model?.config?.resModel;
        const ctx = this.props.context || this.model?.config?.context || {};
        if (
            clickParams.special === "cancel" &&
            resModel === "product.template" &&
            ctx.avea_stock_workspace
        ) {
            await this.discard();
            return false;
        }
        if (
            clickParams.special === "cancel" &&
            resModel === "avea.stock.count.placeholder"
        ) {
            await this.discard();
            return false;
        }
        return await super.beforeExecuteActionButton(clickParams);
    },
});

export class AveaStockCatalogueController extends ListController {
    static template = "avea_till.StockCatalogueList";

    /**
     * New Stock Item always opens the Avea product workspace (not an inline row
     * and not the standard Odoo product form).
     */
    async openNewStockItem() {
        const action = await this.orm.call(
            "product.template",
            "action_avea_new_stock_item",
            []
        );
        return this.actionService.doAction(action);
    }

    async createRecord() {
        return this.openNewStockItem();
    }

    async onClickCreate() {
        return this.openNewStockItem();
    }

    /**
     * Opening a row uses the Avea Stock Item form, not the standard product form.
     */
    async openRecord(record, { newWindow } = {}) {
        if (newWindow) {
            return super.openRecord(record, { newWindow });
        }
        const action = await this.orm.call(
            "product.template",
            "action_avea_open_stock_item",
            [[record.resId]]
        );
        return this.actionService.doAction(action);
    }
}

registry.category("views").add("avea_stock_catalogue_list", {
    ...listView,
    Controller: AveaStockCatalogueController,
});
