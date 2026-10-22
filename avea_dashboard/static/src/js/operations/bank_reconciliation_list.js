/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
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
        const resId = await this.orm.call(
            "avea.bank.reconciliation",
            "_avea_create_draft_id",
            [],
            {}
        );
        await this.actionService.doAction({
            type: "ir.actions.act_window",
            name: _t("New bank reconciliation"),
            res_model: "avea.bank.reconciliation",
            res_id: resId,
            view_mode: "form",
            views: [[false, "form"]],
            target: "current",
        });
    }

    async createRecord() {
        return this.onClickNewReconciliation();
    }
}

registry.category("views").add("avea_bank_reconciliation_list", {
    ...listView,
    Controller: AveaBankReconciliationListController,
});
