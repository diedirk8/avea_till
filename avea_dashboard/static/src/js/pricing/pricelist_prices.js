/** @odoo-module **/

import { Pager } from "@web/core/pager/pager";
import { ListController } from "@web/views/list/list_controller";
import { listView } from "@web/views/list/list_view";
import { registry } from "@web/core/registry";
import { debounce } from "@web/core/utils/timing";
import { useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

export class AveaPricelistPricesController extends ListController {
    static template = "avea_till.PricelistPricesList";
    static components = { ...ListController.components, Pager };

    setup() {
        super.setup();
        this.actionService = useService("action");
        this.filterState = useState({ searchText: "" });
        this._applySearchDebounced = debounce(() => this.applySearch(), 300);
    }

    get className() {
        const base = this.props.className || "";
        return `${base} o_avea_workspace o_avea_workspace--pricelist o_avea_workspace--pricelist-prices`.trim();
    }

    get display() {
        return {
            ...super.display,
            controlPanel: false,
        };
    }

    get pricelistName() {
        return this.props.context?.avea_pricelist_name || "this list";
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
                "|",
                ["name", "ilike", query],
                ["default_code", "ilike", query],
                ["barcode", "ilike", query],
                ["categ_id", "ilike", query]
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
        const pricelistId = this.props.context?.avea_pricelist_id;
        if (pricelistId) {
            await this.actionService.doAction("avea_till.action_avea_pricelist_manager", {
                viewType: "form",
                resId: Number(pricelistId),
            });
            return;
        }
        await this.actionService.doAction("avea_till.action_avea_pricelist_manager");
    }

    async openRecord() {
        return;
    }
}

registry.category("views").add("avea_pricelist_prices", {
    ...listView,
    Controller: AveaPricelistPricesController,
});
