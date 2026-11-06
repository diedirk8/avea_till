/** @odoo-module **/

import { Pager } from "@web/core/pager/pager";
import { ListController } from "@web/views/list/list_controller";
import { listView } from "@web/views/list/list_view";
import { registry } from "@web/core/registry";
import { debounce } from "@web/core/utils/timing";
import { useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

export class AveaAccountActivityController extends ListController {
    static template = "avea_till.AccountActivityList";
    static components = { ...ListController.components, Pager };

    setup() {
        super.setup();
        this.actionService = useService("action");
        this.filterState = useState({ searchText: "" });
        this._applySearchDebounced = debounce(() => this.applySearch(), 300);
    }

    get className() {
        const base = this.props.className || "";
        return `${base} o_avea_workspace o_avea_workspace--account o_avea_workspace--account-activity`.trim();
    }

    get display() {
        return {
            ...super.display,
            controlPanel: false,
        };
    }

    get accountName() {
        return this.props.context?.avea_account_name || "this account";
    }

    _getActionDomain() {
        return this.props.domain?.length ? [...this.props.domain] : [];
    }

    async applySearch() {
        if (!this.model?.root) {
            return;
        }
        const domain = this._getActionDomain();
        const query = this.filterState.searchText.trim();
        if (query) {
            domain.push(
                "|",
                "|",
                ["name", "ilike", query],
                ["move_name", "ilike", query],
                ["partner_id", "ilike", query]
            );
        }
        await this.model.root.load({
            domain,
            offset: 0,
        });
    }

    onSearchInput(ev) {
        this.filterState.searchText = ev.target.value;
        this._applySearchDebounced();
    }

    async onClickBack() {
        if (this.env.config?.historyBack) {
            await this.env.config.historyBack();
            return;
        }
        const accountId = this.props.context?.avea_account_id;
        if (accountId) {
            await this.actionService.doAction("avea_till.action_avea_account_manager", {
                viewType: "form",
                resId: Number(accountId),
            });
            return;
        }
        await this.actionService.doAction("avea_till.action_avea_account_manager");
    }

    async openRecord() {
        return;
    }
}

registry.category("views").add("avea_account_activity", {
    ...listView,
    Controller: AveaAccountActivityController,
    props: (genericProps, view) => {
        const props = listView.props(genericProps, view);
        return { ...props, allowSelectors: false };
    },
});
