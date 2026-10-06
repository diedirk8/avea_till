/** @odoo-module **/

import { Pager } from "@web/core/pager/pager";
import { ListController } from "@web/views/list/list_controller";
import { listView } from "@web/views/list/list_view";
import { registry } from "@web/core/registry";
import { debounce } from "@web/core/utils/timing";
import { useState } from "@odoo/owl";

const PROMOTION_FILTER_NAMES = new Set([
    "running",
    "scheduled",
    "expired",
    "active",
    "inactive",
]);

export class AveaPromotionListController extends ListController {
    static template = "avea_till.PromotionList";
    static components = { ...ListController.components, Pager };

    setup() {
        super.setup();
        this.bannerState = useState({ activeFilter: "all", searchText: "" });
        this._applySearchDebounced = debounce(() => this.applyPromotionSearch(), 300);
    }

    get className() {
        const base = this.props.className || "";
        return `${base} o_avea_workspace o_avea_workspace--promotion o_avea_workspace--promotion-list`.trim();
    }

    get display() {
        return {
            ...super.display,
            controlPanel: false,
        };
    }

    _promotionSearchItem(name) {
        return Object.values(this.env.searchModel.searchItems).find((item) => item.name === name);
    }

    _promotionTextSearchItem() {
        return Object.values(this.env.searchModel.searchItems).find(
            (item) => item.type === "field" && item.fieldName === "name"
        );
    }

    _clearPromotionTextSearch(searchModel) {
        const item = this._promotionTextSearchItem();
        if (!item) {
            return;
        }
        searchModel.query = searchModel.query.filter((queryElem) => queryElem.searchItemId !== item.id);
    }

    async applyPromotionSearch() {
        const searchModel = this.env.searchModel;
        if (!searchModel) {
            return;
        }
        const text = this.bannerState.searchText.trim();
        this._clearPromotionTextSearch(searchModel);
        if (text) {
            const item = this._promotionTextSearchItem();
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

    onPromotionSearchInput(ev) {
        this.bannerState.searchText = ev.target.value;
        this._applySearchDebounced();
    }

    _filterButtonClass(filterKey) {
        return this.bannerState.activeFilter === filterKey
            ? "btn btn-primary o_avea_period_btn"
            : "btn btn-secondary o_avea_period_btn";
    }

    async _clearPromotionFilters(searchModel) {
        for (const name of PROMOTION_FILTER_NAMES) {
            const item = this._promotionSearchItem(name);
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
        const searchModel = this.env.searchModel;
        await this._clearPromotionFilters(searchModel);
        if (filterKey !== "all") {
            const item = this._promotionSearchItem(filterKey);
            if (item) {
                searchModel.toggleSearchItem(item.id);
            }
        }
        this.bannerState.activeFilter = filterKey;
        await searchModel.search();
    }

    async onClickCreatePromotion() {
        await this.createRecord();
    }
}

registry.category("views").add("avea_promotion_list", {
    ...listView,
    Controller: AveaPromotionListController,
    props: (genericProps, view) => {
        const props = listView.props(genericProps, view);
        return { ...props, allowSelectors: false };
    },
});
