/** @odoo-module **/

import { Pager } from "@web/core/pager/pager";
import { ListController } from "@web/views/list/list_controller";
import { ListRenderer } from "@web/views/list/list_renderer";
import { listView } from "@web/views/list/list_view";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { useState } from "@odoo/owl";

const TRANSACTION_FILTER_NAMES = new Set([
    "avea_tx_today",
    "avea_tx_last_7",
    "avea_tx_last_30",
]);

export class AveaBusinessTransactionsRenderer extends ListRenderer {
    setup() {
        super.setup();
        this.orm = useService("orm");
        this.actionService = useService("action");
    }

    getCellClass(column, record) {
        const className = super.getCellClass(column, record);
        if (
            column.name === "transaction_date_label" ||
            column.name === "reference"
        ) {
            return `${className} o_list_text o_avea_ledger_wrap_cell`.trim();
        }
        return className;
    }

    async onCellClicked(record, column, ev, newWindow) {
        if (record.resId) {
            ev.preventDefault();
            ev.stopPropagation();
            const action = await this.orm.call(
                "avea.business.transaction",
                "action_open_source_record",
                [[record.resId]]
            );
            if (action && action.type) {
                return this.actionService.doAction(action);
            }
            return;
        }
        return super.onCellClicked(record, column, ev, newWindow);
    }
}

export class AveaBusinessTransactionsController extends ListController {
    static template = "avea_till.BusinessTransactionsList";
    static components = { ...ListController.components, Pager };

    setup() {
        super.setup();
        this.bannerState = useState({ activeFilter: "all" });
    }

    get className() {
        const base = this.props.className || "";
        return `${base} o_avea_workspace o_avea_workspace--sales-ledger o_avea_workspace--business-transactions`.trim();
    }

    get display() {
        return {
            ...super.display,
            controlPanel: false,
        };
    }

    _transactionSearchItem(name) {
        return Object.values(this.env.searchModel.searchItems).find(
            (item) => item.name === name
        );
    }

    _activeTransactionFilterName() {
        for (const name of TRANSACTION_FILTER_NAMES) {
            const item = this._transactionSearchItem(name);
            if (item && this.env.searchModel.query.some((q) => q.searchItemId === item.id)) {
                return name.replace("avea_tx_", "");
            }
        }
        return "all";
    }

    _filterButtonClass(filterKey) {
        return this.bannerState.activeFilter === filterKey
            ? "btn btn-primary o_avea_period_btn"
            : "btn btn-secondary o_avea_period_btn";
    }

    async onFilterClick(filterKey) {
        const searchModel = this.env.searchModel;
        for (const name of TRANSACTION_FILTER_NAMES) {
            const item = this._transactionSearchItem(name);
            if (!item) {
                continue;
            }
            const isActive = searchModel.query.some((q) => q.searchItemId === item.id);
            if (isActive) {
                searchModel.toggleSearchItem(item.id);
            }
        }

        if (filterKey !== "all") {
            const item = this._transactionSearchItem(`avea_tx_${filterKey}`);
            if (item) {
                searchModel.toggleSearchItem(item.id);
            }
        }

        this.bannerState.activeFilter = filterKey;
        await searchModel.search();
    }
}

registry.category("views").add("avea_business_transactions_list", {
    ...listView,
    Controller: AveaBusinessTransactionsController,
    Renderer: AveaBusinessTransactionsRenderer,
    props: (genericProps, view) => {
        const props = listView.props(genericProps, view);
        return {
            ...props,
            allowSelectors: false,
        };
    },
});
