/** @odoo-module **/

import { Pager } from "@web/core/pager/pager";
import { ListController } from "@web/views/list/list_controller";
import { listView } from "@web/views/list/list_view";
import { registry } from "@web/core/registry";
import { debounce } from "@web/core/utils/timing";
import { useState } from "@odoo/owl";

const FILTER_NAMES = new Set(["income", "expense", "active", "inactive"]);

export class AveaAccountListController extends ListController {
    static template = "avea_till.AccountList";
    static components = { ...ListController.components, Pager };

    setup() {
        super.setup();
        this.bannerState = useState({ activeFilter: "all", searchText: "" });
        this._applySearchDebounced = debounce(() => this.applyAccountSearch(), 300);
    }

    get className() {
        const base = this.props.className || "";
        return `${base} o_avea_workspace o_avea_workspace--account o_avea_workspace--account-list`.trim();
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

    _textSearchItem() {
        return Object.values(this.env.searchModel.searchItems).find(
            (item) => item.type === "field" && item.fieldName === "name"
        );
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

    _clearTextSearch(searchModel) {
        const item = this._textSearchItem();
        if (!item) {
            return;
        }
        searchModel.query = searchModel.query.filter((queryElem) => queryElem.searchItemId !== item.id);
    }

    async applyAccountSearch() {
        const searchModel = this.env.searchModel;
        if (!searchModel) {
            return;
        }
        const text = this.bannerState.searchText.trim();
        this._clearTextSearch(searchModel);
        if (text) {
            const item = this._textSearchItem();
            if (item) {
                searchModel.addAutoCompletionValues(item.id, {
                    label: text,
                    value: text,
                    operator: "ilike",
                });
            }
        }
        await searchModel.search();
    }

    onAccountSearchInput(ev) {
        this.bannerState.searchText = ev.target.value;
        this._applySearchDebounced();
    }

    async onFilterClick(filterKey) {
        await this._clearFilters();
        const searchModel = this.env.searchModel;
        if (filterKey === "income" || filterKey === "expense") {
            const kind = this._searchItem(filterKey);
            const active = this._searchItem("active");
            if (kind) {
                searchModel.toggleSearchItem(kind.id);
            }
            if (active) {
                searchModel.toggleSearchItem(active.id);
            }
        } else if (filterKey === "inactive") {
            const item = this._searchItem("inactive");
            if (item) {
                searchModel.toggleSearchItem(item.id);
            }
        } else {
            const active = this._searchItem("active");
            if (active) {
                searchModel.toggleSearchItem(active.id);
            }
        }
        this.bannerState.activeFilter = filterKey;
        await searchModel.search();
    }

    async onClickCreateAccount() {
        await this.createRecord();
    }
}

registry.category("views").add("avea_account_list", {
    ...listView,
    Controller: AveaAccountListController,
    props: (genericProps, view) => {
        const props = listView.props(genericProps, view);
        return { ...props, allowSelectors: false };
    },
});
