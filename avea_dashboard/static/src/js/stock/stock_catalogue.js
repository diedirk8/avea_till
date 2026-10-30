/** @odoo-module **/

import { FormController } from "@web/views/form/form_controller";
import { Pager } from "@web/core/pager/pager";
import { ListController } from "@web/views/list/list_controller";
import { listView } from "@web/views/list/list_view";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { registry } from "@web/core/registry";
import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";
import { debounce } from "@web/core/utils/timing";
import { useState, onMounted, onWillUnmount } from "@odoo/owl";

const ACTION_MANAGER_SCROLL_CLASS = "o_avea_stock_catalogue_action_manager";
const BODY_PAGE_CLASS = "o_avea_stock_catalogue_page";

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
    { value: "barcode_asc", label: "Barcode A–Z (blank first)" },
    { value: "barcode_desc", label: "Barcode Z–A" },
];

const ORDER_BY_MAP = {
    newest: [{ name: "create_date", asc: false }],
    oldest: [{ name: "create_date", asc: true }],
    name_asc: [{ name: "name", asc: true }],
    name_desc: [{ name: "name", asc: false }],
    stock_asc: [{ name: "avea_stock_qty", asc: true }],
    stock_desc: [{ name: "avea_stock_qty", asc: false }],
    barcode_asc: [{ name: "avea_barcode_sort", asc: true }],
    barcode_desc: [{ name: "avea_barcode_sort", asc: false }],
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
        return await super.beforeExecuteActionButton(clickParams);
    },
});

export class AveaStockCatalogueController extends ListController {
    static template = "avea_till.StockCatalogueList";
    static components = { ...ListController.components, Pager };

    setup() {
        super.setup();
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.dialog = useService("dialog");
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
        onMounted(() => {
            document.body.classList.add(BODY_PAGE_CLASS);
            this._setupScrollShell();
            this._onFiltersMounted();
        });
        queueMicrotask(() => this._setupScrollShell());
        onWillUnmount(() => {
            document.body.classList.remove(BODY_PAGE_CLASS);
            this._teardownScrollShell();
        });
    }

    _actionManagerEl() {
        return document.querySelector(".o_action_manager");
    }

    _setupScrollShell() {
        this._actionManagerEl()?.classList.add(ACTION_MANAGER_SCROLL_CLASS);
    }

    _teardownScrollShell() {
        this._actionManagerEl()?.classList.remove(ACTION_MANAGER_SCROLL_CLASS);
    }

    get className() {
        const base = this.props.className || "";
        return `${base} o_avea_catalogue_flush o_avea_workspace o_avea_workspace--stock o_avea_workspace--stock-catalogue o_avea_workspace--stock-catalogue-list`.trim();
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
                // Show Odoo's selection bar (Actions, Export, Archive, …) when rows are selected.
                layoutActions: this.hasSelectedRecords,
            },
        };
    }

    get selectedCount() {
        if (this.isDomainSelected) {
            return this.model.root.count;
        }
        return this.model.root.selection.length;
    }

    discardCatalogueSelection() {
        this.discardSelection();
    }

    async _selectedTemplateIds() {
        return await this.model.root.getResIds(true);
    }

    async _callBulk(method) {
        const ids = await this._selectedTemplateIds();
        if (!ids.length) {
            return;
        }
        const result = await this.orm.call("product.template", method, [ids]);
        await this.model.load();
        this.discardCatalogueSelection();
        if (result && typeof result === "object" && result.type === "ir.actions.act_window") {
            await this.actionService.doAction(result);
        }
    }

    async onBulkArchive() {
        await this._callBulk("action_avea_bulk_archive");
    }

    async onBulkRestore() {
        await this._callBulk("action_avea_bulk_unarchive");
    }

    async onBulkEnablePos() {
        await this._callBulk("action_avea_bulk_enable_pos");
    }

    async onBulkDisablePos() {
        await this._callBulk("action_avea_bulk_disable_pos");
    }

    async onBulkMerge() {
        const ids = await this._selectedTemplateIds();
        if (ids.length < 2) {
            return;
        }
        const action = await this.orm.call(
            "product.template",
            "action_avea_open_merge_wizard",
            [ids]
        );
        await this.actionService.doAction(action);
    }

    async onBulkPrintLabels() {
        const ids = await this._selectedTemplateIds();
        if (!ids.length) {
            return;
        }
        const action = await this.orm.call(
            "product.template",
            "action_open_label_layout",
            [ids]
        );
        await this.actionService.doAction(action);
    }

    async onBulkDelete() {
        const ids = await this._selectedTemplateIds();
        if (!ids.length) {
            return;
        }
        this.dialog.add(ConfirmationDialog, {
            title: "Delete products",
            body: `Permanently delete ${ids.length} selected product(s)? This cannot be undone.`,
            confirm: async () => {
                await this.orm.call("product.template", "action_avea_bulk_delete", [ids]);
                await this.model.load();
                this.discardCatalogueSelection();
            },
            cancel: () => {},
        });
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
     * While a row is being edited inline, finish that edit before navigating away.
     */
    async openRecord(record, { newWindow } = {}) {
        if (newWindow) {
            return super.openRecord(record, { newWindow });
        }
        if (this.editedRecord) {
            if (this.editedRecord.resId === record.resId) {
                return;
            }
            const canLeave = await this.model.root.leaveEditMode({ validate: true });
            if (!canLeave) {
                return;
            }
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
