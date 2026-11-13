/** @odoo-module **/

import { Pager } from "@web/core/pager/pager";
import { ListController } from "@web/views/list/list_controller";
import { listView } from "@web/views/list/list_view";
import { registry } from "@web/core/registry";
import { useState } from "@odoo/owl";

const FILTER_NAMES = new Set(["active", "inactive", "pos"]);

export class AveaPricelistListController extends ListController {
    static template = "avea_till.PricelistList";
    static components = { ...ListController.components, Pager };

    setup() {
        super.setup();
        this.bannerState = useState({ activeFilter: "all" });
    }

    get className() {
        const base = this.props.className || "";
        return `${base} o_avea_workspace o_avea_workspace--pricelist o_avea_workspace--pricelist-list`.trim();
    }

    get display() {
        return {
            ...super.display,
            controlPanel: false,
        };
    }

    _searchItem(name) {
        return Object.values(this.env.searchModel.searchItems).find((item) => item.name === name);
    }

    _filterButtonClass(key) {
        const active = this.bannerState.activeFilter === key;
        return `btn o_avea_period_btn ${active ? "btn-primary" : "btn-outline-secondary"}`;
    }

    async _clearFilters() {
        const searchModel = this.env.searchModel;
        for (const name of FILTER_NAMES) {
            const item = this._searchItem(name);
            if (!item) {
                continue;
            }
            const isActive = searchModel.query.some((q) => q.searchItemId === item.id);
            if (isActive) {
                searchModel.toggleSearchItem(item.id);
            }
        }
    }

    async onFilterClick(filterKey) {
        await this._clearFilters();
        if (filterKey === "active") {
            const item = this._searchItem("active");
            if (item) {
                this.env.searchModel.toggleSearchItem(item.id);
            }
        } else if (filterKey === "inactive") {
            const item = this._searchItem("inactive");
            if (item) {
                this.env.searchModel.toggleSearchItem(item.id);
            }
        } else if (filterKey === "pos") {
            const item = this._searchItem("pos");
            if (item) {
                this.env.searchModel.toggleSearchItem(item.id);
            }
        }
        this.bannerState.activeFilter = filterKey;
        await this.env.searchModel.search();
    }

    async onClickCreatePricelist() {
        await this.createRecord();
    }
}

registry.category("views").add("avea_pricelist_list", {
    ...listView,
    Controller: AveaPricelistListController,
});
