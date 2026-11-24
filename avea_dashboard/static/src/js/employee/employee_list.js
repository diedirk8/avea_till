/** @odoo-module **/

import { Pager } from "@web/core/pager/pager";
import { ListController } from "@web/views/list/list_controller";
import { listView } from "@web/views/list/list_view";
import { registry } from "@web/core/registry";
import { debounce } from "@web/core/utils/timing";
import { useState, onMounted, onWillUnmount } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";

const BASE_DOMAIN = [["avea_is_employee", "=", true]];
const ACTION_MANAGER_SCROLL_CLASS = "o_avea_customer_list_action_manager";
const BODY_PAGE_CLASS = "o_avea_customer_list_page";

const STATUS_OPTIONS = [
    { value: "all", label: "All" },
    { value: "active", label: "Active" },
    { value: "advances", label: "Advances to count" },
    { value: "archived", label: "Archived" },
];

const SORT_OPTIONS = [
    { value: "name_asc", label: "Name A–Z" },
    { value: "name_desc", label: "Name Z–A" },
    { value: "newest", label: "Newest first" },
    { value: "last_paid_desc", label: "Last paid (recent first)" },
    { value: "paid_desc", label: "Salary paid high–low" },
    { value: "advance_desc", label: "Advances high–low" },
];

const ORDER_BY_MAP = {
    name_asc: [{ name: "name", asc: true }],
    name_desc: [{ name: "name", asc: false }],
    newest: [{ name: "create_date", asc: false }],
    last_paid_desc: [{ name: "avea_employee_last_paid", asc: false }],
    paid_desc: [{ name: "avea_employee_paid_total", asc: false }],
    advance_desc: [{ name: "avea_employee_advance_outstanding", asc: false }],
};

export class AveaEmployeeListController extends ListController {
    static template = "avea_till.EmployeeList";
    static components = { ...ListController.components, Pager };

    setup() {
        super.setup();
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
        return `${base} o_avea_catalogue_flush o_avea_workspace o_avea_workspace--customer o_avea_workspace--customer-list o_avea_workspace--employee`.trim();
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
        return _t("Employees");
    }

    get listSubtitle() {
        return _t(
            "People you pay. Open someone to see salary and advances — an advance is salary paid early."
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
                ["name", "ilike", query],
                ["email", "ilike", query],
                ["phone", "ilike", query]
            );
        }
        switch (this.filterState.status) {
            case "active":
                domain.push(["active", "=", true]);
                break;
            case "archived":
                domain.push(["active", "=", false]);
                break;
            case "advances":
                domain.push(["avea_employee_advance_outstanding", ">", 0]);
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
        if (status === "advances") {
            this.filterState.sortBy = "advance_desc";
            this.applyFilters({ useDropdownOrder: true });
            return;
        }
        this.applyFilters();
    }

    _statusButtonClass(value) {
        const active = this.filterState.status === value;
        return `btn o_avea_period_btn ${active ? "btn-primary" : "btn-outline-secondary"}`;
    }

    async onClickCreateEmployee() {
        await this.createRecord();
    }
}

registry.category("views").add("avea_employee_list", {
    ...listView,
    Controller: AveaEmployeeListController,
});
