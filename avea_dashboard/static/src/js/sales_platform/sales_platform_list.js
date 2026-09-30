/** @odoo-module **/

import { Pager } from "@web/core/pager/pager";
import { ListController } from "@web/views/list/list_controller";
import { listView } from "@web/views/list/list_view";
import { registry } from "@web/core/registry";
import { useState } from "@odoo/owl";

const PLATFORM_FILTER_NAMES = new Set(["active", "inactive"]);

export class AveaSalesPlatformListController extends ListController {
    static template = "avea_till.SalesPlatformList";
    static components = { ...ListController.components, Pager };

    setup() {
        super.setup();
        this.bannerState = useState({ activeFilter: "all" });
    }

    get className() {
        const base = this.props.className || "";
        return `${base} o_avea_workspace o_avea_workspace--sales-platform o_avea_workspace--sales-platform-list`.trim();
    }

    get display() {
        return {
            ...super.display,
            controlPanel: false,
        };
    }

    _platformSearchItem(name) {
        return Object.values(this.env.searchModel.searchItems).find((item) => item.name === name);
    }

    _filterButtonClass(key) {
        const active = this.bannerState.activeFilter === key;
        return `btn o_avea_period_btn ${active ? "btn-primary" : "btn-outline-secondary"}`;
    }

    async onFilterClick(filterKey) {
        const searchModel = this.env.searchModel;
        for (const name of PLATFORM_FILTER_NAMES) {
            const item = this._platformSearchItem(name);
            if (!item) {
                continue;
            }
            const isActive = searchModel.query.some((q) => q.searchItemId === item.id);
            if (isActive) {
                searchModel.toggleSearchItem(item.id);
            }
        }
        if (filterKey === "active") {
            const item = this._platformSearchItem("active");
            if (item) {
                searchModel.toggleSearchItem(item.id);
            }
        } else if (filterKey === "inactive") {
            const item = this._platformSearchItem("inactive");
            if (item) {
                searchModel.toggleSearchItem(item.id);
            }
        }
        this.bannerState.activeFilter = filterKey;
        await searchModel.search();
    }

    async onClickCreatePlatform() {
        await this.createRecord();
    }
}

registry.category("views").add("avea_sales_platform_list", {
    ...listView,
    Controller: AveaSalesPlatformListController,
});
