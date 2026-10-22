/** @odoo-module **/

import { ListController } from "@web/views/list/list_controller";
import { listView } from "@web/views/list/list_view";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class AveaBankReconciliationListController extends ListController {
    static template = "avea_till.BankReconciliationList";

    setup() {
        super.setup();
        this.orm = useService("orm");
        this.actionService = useService("action");
    }

    get className() {
        const base = this.props.className || "";
        return `${base} o_avea_workspace o_avea_workspace--bank-recon`.trim();
    }

    async onClickNewReconciliation() {
        // Server action so Odoo builds a full window action (views, etc.).
        await this.actionService.doAction(
            "avea_till.action_avea_new_bank_reconciliation"
        );
    }

    async createRecord() {
        return this.onClickNewReconciliation();
    }
}

registry.category("views").add("avea_bank_reconciliation_list", {
    ...listView,
    Controller: AveaBankReconciliationListController,
});
