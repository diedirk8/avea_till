/** @odoo-module **/

import { Pager } from "@web/core/pager/pager";
import { ListController } from "@web/views/list/list_controller";
import { listView } from "@web/views/list/list_view";
import { registry } from "@web/core/registry";
import { debounce } from "@web/core/utils/timing";
import { useState, onMounted, onWillUnmount } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";

const BASE_DOMAIN = [["supplier_rank", ">", 0]];
const ACTION_MANAGER_SCROLL_CLASS = "o_avea_customer_list_action_manager";
const BODY_PAGE_CLASS = "o_avea_customer_list_page";

const STATUS_OPTIONS = [
    { value: "all", label: "All" },
    { value: "active", label: "Active" },
    { value: "owing", label: "We owe them" },
    { value: "credit", label: "Has credit" },
    { value: "with_products", label: "Supplies products" },
    { value: "archived", label: "Archived" },
];

const SORT_OPTIONS = [
    { value: "name_asc", label: "Name A–Z" },
    { value: "name_desc", label: "Name Z–A" },
    { value: "newest", label: "Newest first" },
    { value: "oldest", label: "Oldest first" },
    { value: "owing_desc", label: "We owe high–low" },
    { value: "spend_desc", label: "Purchases high–low" },
    { value: "receipt_desc", label: "Last receipt (recent first)" },
    { value: "products_desc", label: "Products high–low" },
];

const ORDER_BY_MAP = {
    name_asc: [{ name: "name", asc: true }],
    name_desc: [{ name: "name", asc: false }],
    newest: [{ name: "create_date", asc: false }],
    oldest: [{ name: "create_date", asc: true }],
    owing_desc: [{ name: "avea_supplier_payable", asc: false }],
    spend_desc: [{ name: "avea_supplier_spend_total", asc: false }],
    receipt_desc: [{ name: "avea_supplier_last_receipt", asc: false }],
    products_desc: [{ name: "avea_supplier_product_count", asc: false }],
};

export class AveaSupplierListController extends ListController {
    static template = "avea_till.SupplierList";
    static components = { ...ListController.components, Pager };

    setup() {
        super.setup();
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.filterState = useState({
            searchText: "",
            status: "active",
            sortBy: "name_asc",
        });
        this._applyFiltersDebounced = debounce(() => this.applyFilters(), 300);
        onMounted(() => this._onFiltersMounted());
        queueMicrotask(() => this._setupScrollShell());
        onWillUnmount(() => {
            document.body.classList.remove(BODY_PAGE_CLASS);
            this._teardownScrollShell();
        });
    }

    get className() {
        const base = this.props.className || "";
        return `${base} o_avea_catalogue_flush o_avea_workspace o_avea_workspace--customer o_avea_workspace--customer-list o_avea_workspace--supplier`.trim();
    }

    get display() {
        return {
            ...super.display,
            controlPanel: false,
        };
    }

    get statusOptions() {
        return STATUS_OPTIONS;
    }

    get sortOptions() {
        return SORT_OPTIONS;
    }

    get listTitle() {
        return _t("Suppliers");
    }

    get listSubtitle() {
        return _t(
            "Search by name, phone, email, or VAT. Open a supplier to receive stock or record an expense."
        );
    }

    _getActionDomain() {
        return this.props.domain?.length ? [...this.props.domain] : [...BASE_DOMAIN];
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

    async _onFiltersMounted() {
        document.body.classList.add(BODY_PAGE_CLASS);
        this._setupScrollShell();
        await this.applyFilters();
    }

    async _buildFilterDomain() {
        const domain = [...this._getActionDomain()];
        const query = this.filterState.searchText.trim();
        if (query) {
            domain.push(
                "|",
                "|",
                "|",
                ["name", "ilike", query],
                ["email", "ilike", query],
                ["phone", "ilike", query],
                ["vat", "ilike", query]
            );
        }
        switch (this.filterState.status) {
            case "active":
                domain.push(["active", "=", true]);
                break;
            case "archived":
                domain.push(["active", "=", false]);
                break;
            case "owing":
                domain.push(
                    ...(await this.orm.call("res.partner", "avea_supplier_owing_domain", []))
                );
                break;
            case "credit":
                domain.push(
                    ...(await this.orm.call("res.partner", "avea_supplier_credit_domain", []))
                );
                break;
            case "with_products":
                domain.push(["avea_supplier_product_count", ">", 0]);
                break;
            default:
                break;
        }
        return domain;
    }

    _getOrderBy() {
        return ORDER_BY_MAP[this.filterState.sortBy] || ORDER_BY_MAP.name_asc;
    }

    _resolveOrderBy({ useDropdownOrder = false } = {}) {
        if (useDropdownOrder) {
            return this._getOrderBy();
        }
        const current = this.model?.root?.orderBy;
        if (current?.length) {
            return [...current];
        }
        return this._getOrderBy();
    }

    async applyFilters({ resetOffset = true, useDropdownOrder = false } = {}) {
        if (!this.model?.root) {
            return;
        }
        await this.model.root.load({
            domain: await this._buildFilterDomain(),
            orderBy: this._resolveOrderBy({ useDropdownOrder }),
            offset: resetOffset ? 0 : this.model.root.offset,
        });
    }

    onFilterInputChange(field, ev) {
        this.filterState[field] = ev.target.value;
        this._applyFiltersDebounced();
    }

    onFilterSelectChange(field, ev) {
        this.filterState[field] = ev.target.value;
        this.applyFilters({ useDropdownOrder: field === "sortBy" });
    }

    onStatusClick(status) {
        this.filterState.status = status;
        if (status === "owing") {
            this.filterState.sortBy = "owing_desc";
            this.applyFilters({ useDropdownOrder: true });
            return;
        }
        this.applyFilters();
    }

    _statusButtonClass(value) {
        const active = this.filterState.status === value;
        return `btn o_avea_period_btn ${active ? "btn-primary" : "btn-outline-secondary"}`;
    }

    async onClickCreateSupplier() {
        await this.createRecord();
    }
}

registry.category("views").add("avea_supplier_list", {
    ...listView,
    Controller: AveaSupplierListController,
});
