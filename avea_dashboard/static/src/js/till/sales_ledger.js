/** @odoo-module **/

import { ListController } from "@web/views/list/list_controller";
import { ListRenderer } from "@web/views/list/list_renderer";
import { listView } from "@web/views/list/list_view";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class AveaSalesLedgerRenderer extends ListRenderer {
    setup() {
        super.setup();
        this.orm = useService("orm");
        this.actionService = useService("action");
    }

    async onCellClicked(record, column, ev, newWindow) {
        if (column.name === "avea_order_reference" && record.resId) {
            ev.preventDefault();
            ev.stopPropagation();
            const action = await this.orm.call(
                "pos.order.line",
                "action_avea_open_pos_order",
                [[record.resId]]
            );
            if (action) {
                return this.actionService.doAction(action);
            }
            return;
        }
        return super.onCellClicked(record, column, ev, newWindow);
    }
}

export class AveaSalesLedgerController extends ListController {
    static template = "avea_till.SalesLedgerList";
}

registry.category("views").add("avea_sales_ledger_list", {
    ...listView,
    Controller: AveaSalesLedgerController,
    Renderer: AveaSalesLedgerRenderer,
});
