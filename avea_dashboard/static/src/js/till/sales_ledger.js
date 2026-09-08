/** @odoo-module **/

import { Pager } from "@web/core/pager/pager";
import { ListController } from "@web/views/list/list_controller";
import { ListRenderer } from "@web/views/list/list_renderer";
import { listView } from "@web/views/list/list_view";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { useState, onMounted } from "@odoo/owl";

const LEDGER_FILTER_NAMES = new Set([
    "avea_ledger_today",
    "avea_ledger_last_7",
    "avea_ledger_last_30",
    "refunds",
    "sales",
]);

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
    static components = { ...ListController.components, Pager };

    setup() {
        super.setup();
        this.orm = useService("orm");
        this._bannerLoadToken = 0;
        this.bannerState = useState({
            total: 0,
            rangeDisplay: "",
            summaryDisplay: "",
            activeFilter: "all",
        });

        onMounted(() => {
            this.loadBannerInfo();
        });
    }

    get className() {
        const base = this.props.className || "";
        return `${base} o_avea_workspace o_avea_workspace--sales-ledger`.trim();
    }

    get display() {
        return {
            ...super.display,
            controlPanel: false,
        };
    }

    _ledgerSearchItem(name) {
        return Object.values(this.env.searchModel.searchItems).find(
            (item) => item.name === name
        );
    }

    _activeLedgerFilterName() {
        for (const name of LEDGER_FILTER_NAMES) {
            const item = this._ledgerSearchItem(name);
            if (item && this.env.searchModel.query.some((q) => q.searchItemId === item.id)) {
                return name === "refunds" || name === "sales" ? name : name.replace("avea_ledger_", "");
            }
        }
        return "all";
    }

    async loadBannerInfo() {
        const searchModel = this.env.searchModel;
        if (!searchModel) {
            return;
        }
        const token = ++this._bannerLoadToken;
        try {
            const info = await this.orm.call(
                "pos.order.line",
                "avea_sales_ledger_banner_info",
                [],
                { domain: searchModel.domain }
            );
            if (token !== this._bannerLoadToken) {
                return;
            }
            this.bannerState.total = info.total;
            this.bannerState.rangeDisplay = info.range_display;
            this.bannerState.summaryDisplay = info.summary_display;
            this.bannerState.activeFilter = this._activeLedgerFilterName();
        } catch (error) {
            console.warn("Sales Ledger banner load failed", error);
        }
    }

    _filterButtonClass(filterKey) {
        return this.bannerState.activeFilter === filterKey
            ? "btn btn-primary o_avea_period_btn"
            : "btn btn-secondary o_avea_period_btn";
    }

    async onFilterClick(filterKey) {
        const searchModel = this.env.searchModel;
        for (const name of LEDGER_FILTER_NAMES) {
            const item = this._ledgerSearchItem(name);
            if (!item) {
                continue;
            }
            const isActive = searchModel.query.some((q) => q.searchItemId === item.id);
            if (isActive) {
                searchModel.toggleSearchItem(item.id);
            }
        }

        if (filterKey !== "all") {
            const filterName =
                filterKey === "refunds" || filterKey === "sales"
                    ? filterKey
                    : `avea_ledger_${filterKey}`;
            const item = this._ledgerSearchItem(filterName);
            if (item) {
                searchModel.toggleSearchItem(item.id);
            }
        }

        this.bannerState.activeFilter = filterKey;
        await searchModel.search();
        await this.loadBannerInfo();
    }
}

registry.category("views").add("avea_sales_ledger_list", {
    ...listView,
    Controller: AveaSalesLedgerController,
    Renderer: AveaSalesLedgerRenderer,
    props: (genericProps, view) => {
        const props = listView.props(genericProps, view);
        return {
            ...props,
            allowSelectors: false,
        };
    },
});
