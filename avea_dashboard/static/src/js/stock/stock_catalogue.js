/** @odoo-module **/

import { FormController } from "@web/views/form/form_controller";
import { ListController } from "@web/views/list/list_controller";
import { listView } from "@web/views/list/list_view";
import { registry } from "@web/core/registry";
import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";
import { debounce } from "@web/core/utils/timing";
import { useState, onMounted } from "@odoo/owl";

const BASE_DOMAIN = [
    ["sale_ok", "=", true],
    ["active", "=", true],
];

const STOCK_STATUS_OPTIONS = [
    { value: "all", label: "All" },
    { value: "in_stock", label: "In Stock" },
    { value: "low_stock", label: "Low Stock" },
    { value: "out_of_stock", label: "Out of Stock" },
];

const ARRANGE_OPTIONS = [
    { value: "newest", label: "Newest First" },
    { value: "oldest", label: "Oldest First" },
    { value: "name_asc", label: "Product A–Z" },
    { value: "name_desc", label: "Product Z–A" },
    { value: "stock_asc", label: "Stock Low–High" },
    { value: "stock_desc", label: "Stock High–Low" },
];

const ORDER_BY_MAP = {
    newest: [{ name: "create_date", asc: false }],
    oldest: [{ name: "create_date", asc: true }],
    name_asc: [{ name: "name", asc: true }],
    name_desc: [{ name: "name", asc: false }],
    stock_asc: [{ name: "avea_stock_qty", asc: true }],
    stock_desc: [{ name: "avea_stock_qty", asc: false }],
};

/**
 * Stock Item / Stock Count forms hide the control panel, so Cancel must discard
 * without triggering the missing-required-fields save path.
 */
patch(FormController.prototype, {
    async beforeExecuteActionButton(clickParams) {
        const resModel = this.props.resModel || this.model?.config?.resModel;
        const ctx = this.props.context || this.model?.config?.context || {};
        if (
            clickParams.special === "cancel" &&
            resModel === "product.template" &&
            ctx.avea_stock_workspace
        ) {
            await this.discard();
            return false;
        }
        if (
            clickParams.special === "cancel" &&
            resModel === "avea.stock.count.placeholder"
        ) {
            await this.discard();
            return false;
        }
        return await super.beforeExecuteActionButton(clickParams);
    },
});

export class AveaStockCatalogueController extends ListController {
    static template = "avea_till.StockCatalogueList";

    setup() {
        super.setup();
        this.orm = useService("orm");
        this.filterState = useState({
            productName: "",
            sku: "",
            barcode: "",
            supplierId: "",
            categoryId: "",
            stockStatus: "all",
            arrangeBy: "newest",
        });
        this.filterOptions = useState({
            suppliers: [],
            categories: [],
        });
        this._applyFiltersDebounced = debounce(() => this.applyFilters(), 300);
        onMounted(() => this._onFiltersMounted());
    }

    get className() {
        const base = this.props.className || "";
        return `${base} o_avea_workspace o_avea_workspace--stock-catalogue`.trim();
    }

    get display() {
        const display = super.display;
        if (!display.controlPanel) {
            return display;
        }
        return {
            ...display,
            controlPanel: {
                ...display.controlPanel,
                layoutActions: false,
            },
        };
    }

    get stockStatusOptions() {
        return STOCK_STATUS_OPTIONS;
    }

    get arrangeOptions() {
        return ARRANGE_OPTIONS;
    }

    async _onFiltersMounted() {
        const [suppliers, categories] = await Promise.all([
            this.orm.searchRead(
                "res.partner",
                [["supplier_rank", ">", 0]],
                ["id", "name", "display_name"],
                { order: "name asc", limit: 500 }
            ),
            this.orm.searchRead(
                "product.category",
                [],
                ["id", "name", "display_name"],
                { order: "name asc", limit: 500 }
            ),
        ]);
        this.filterOptions.suppliers = suppliers;
        this.filterOptions.categories = categories;
        await this.applyFilters();
    }

    _buildFilterDomain() {
        const domain = [...BASE_DOMAIN];
        const name = this.filterState.productName.trim();
        const sku = this.filterState.sku.trim();
        const barcode = this.filterState.barcode.trim();
        if (name) {
            domain.push(["name", "ilike", name]);
        }
        if (sku) {
            domain.push(["default_code", "ilike", sku]);
        }
        if (barcode) {
            domain.push(["barcode", "ilike", barcode]);
        }
        if (this.filterState.supplierId) {
            domain.push(["avea_supplier_id", "=", Number(this.filterState.supplierId)]);
        }
        if (this.filterState.categoryId) {
            domain.push(["categ_id", "=", Number(this.filterState.categoryId)]);
        }
        if (this.filterState.stockStatus && this.filterState.stockStatus !== "all") {
            domain.push(["avea_stock_status", "=", this.filterState.stockStatus]);
        }
        return domain;
    }

    _getOrderBy() {
        return ORDER_BY_MAP[this.filterState.arrangeBy] || ORDER_BY_MAP.newest;
    }

    async applyFilters({ resetOffset = true } = {}) {
        if (!this.model?.root) {
            return;
        }
        await this.model.root.load({
            domain: this._buildFilterDomain(),
            orderBy: this._getOrderBy(),
            offset: resetOffset ? 0 : this.model.root.offset,
        });
    }

    onFilterInputChange(field, ev) {
        this.filterState[field] = ev.target.value;
        this._applyFiltersDebounced();
    }

    onFilterSelectChange(field, ev) {
        this.filterState[field] = ev.target.value;
        this.applyFilters();
    }

    async onRecordSaved(record) {
        await super.onRecordSaved(record);
        await this.applyFilters({ resetOffset: false });
    }

    /**
     * New Stock Item always opens the Avea product workspace (not an inline row
     * and not the standard Odoo product form).
     */
    async openNewStockItem() {
        const action = await this.orm.call(
            "product.template",
            "action_avea_new_stock_item",
            []
        );
        return this.actionService.doAction(action);
    }

    async createRecord() {
        return this.openNewStockItem();
    }

    async onClickCreate() {
        return this.openNewStockItem();
    }

    /**
     * Opening a row uses the Avea Stock Item form, not the standard product form.
     */
    async openRecord(record, { newWindow } = {}) {
        if (newWindow) {
            return super.openRecord(record, { newWindow });
        }
        const action = await this.orm.call(
            "product.template",
            "action_avea_open_stock_item",
            [[record.resId]]
        );
        return this.actionService.doAction(action);
    }
}

registry.category("views").add("avea_stock_catalogue_list", {
    ...listView,
    Controller: AveaStockCatalogueController,
});
