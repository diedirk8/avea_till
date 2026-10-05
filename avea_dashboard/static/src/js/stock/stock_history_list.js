/** @odoo-module **/

import { Pager } from "@web/core/pager/pager";
import { ListController } from "@web/views/list/list_controller";
import { listView } from "@web/views/list/list_view";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { useState } from "@odoo/owl";

const PERIOD_FILTER_NAMES = new Set([
    "avea_stock_hist_last_7",
    "avea_stock_hist_last_30",
    "avea_stock_hist_last_90",
]);

class AveaStockHistoryListController extends ListController {
    static components = { ...ListController.components, Pager };

    setup() {
        super.setup();
        this.actionService = useService("action");
        this.bannerState = useState({ activeFilter: "all" });
    }

    get className() {
        const base = this.props.className || "";
        return `${base} o_avea_workspace o_avea_workspace--stock o_avea_workspace--stock-history`.trim();
    }

    get display() {
        return {
            ...super.display,
            controlPanel: false,
        };
    }

    _periodSearchItem(name) {
        return Object.values(this.env.searchModel.searchItems).find((item) => item.name === name);
    }

    _filterButtonClass(filterKey) {
        return this.bannerState.activeFilter === filterKey
            ? "btn btn-primary o_avea_period_btn"
            : "btn btn-secondary o_avea_period_btn";
    }

    async onFilterClick(filterKey) {
        const searchModel = this.env.searchModel;
        for (const name of PERIOD_FILTER_NAMES) {
            const item = this._periodSearchItem(name);
            if (!item) {
                continue;
            }
            const isActive = searchModel.query.some((q) => q.searchItemId === item.id);
            if (isActive) {
                searchModel.toggleSearchItem(item.id);
            }
        }
        if (filterKey === "last_7") {
            const item = this._periodSearchItem("avea_stock_hist_last_7");
            if (item) {
                searchModel.toggleSearchItem(item.id);
            }
        } else if (filterKey === "last_30") {
            const item = this._periodSearchItem("avea_stock_hist_last_30");
            if (item) {
                searchModel.toggleSearchItem(item.id);
            }
        } else if (filterKey === "last_90") {
            const item = this._periodSearchItem("avea_stock_hist_last_90");
            if (item) {
                searchModel.toggleSearchItem(item.id);
            }
        }
        this.bannerState.activeFilter = filterKey;
        await searchModel.search();
    }

    async openReceiveHistory() {
        await this.actionService.doAction("avea_till.action_avea_stock_receive_history");
    }

    async openReturnHistory() {
        await this.actionService.doAction("avea_till.action_avea_stock_return_history");
    }
}

export class AveaStockReceiveHistoryListController extends AveaStockHistoryListController {
    static template = "avea_till.StockReceiveHistoryList";
}

export class AveaStockReturnHistoryListController extends AveaStockHistoryListController {
    static template = "avea_till.StockReturnHistoryList";
}

registry.category("views").add("avea_stock_receive_history_list", {
    ...listView,
    Controller: AveaStockReceiveHistoryListController,
    props: (genericProps, view) => {
        const props = listView.props(genericProps, view);
        return { ...props, allowSelectors: false };
    },
});

registry.category("views").add("avea_stock_return_history_list", {
    ...listView,
    Controller: AveaStockReturnHistoryListController,
    props: (genericProps, view) => {
        const props = listView.props(genericProps, view);
        return { ...props, allowSelectors: false };
    },
});
