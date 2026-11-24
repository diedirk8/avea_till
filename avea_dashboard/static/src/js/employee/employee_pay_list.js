/** @odoo-module **/

import { Pager } from "@web/core/pager/pager";
import { ListController } from "@web/views/list/list_controller";
import { listView } from "@web/views/list/list_view";
import { registry } from "@web/core/registry";
import { debounce } from "@web/core/utils/timing";
import { useState, onMounted, onWillUnmount } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";

const BASE_DOMAIN = [["avea_staff_pay_kind", "!=", false]];
const ACTION_MANAGER_SCROLL_CLASS = "o_avea_customer_list_action_manager";
const BODY_PAGE_CLASS = "o_avea_customer_list_page";

const STATUS_OPTIONS = [
    { value: "all", label: "All" },
    { value: "salary", label: "Salary" },
    { value: "advance", label: "Advance" },
];

const SORT_OPTIONS = [
    { value: "newest", label: "Newest first" },
    { value: "oldest", label: "Oldest first" },
    { value: "amount_desc", label: "Cash paid high–low" },
];

const ORDER_BY_MAP = {
    newest: [{ name: "date", asc: false }, { name: "id", asc: false }],
    oldest: [{ name: "date", asc: true }, { name: "id", asc: true }],
    amount_desc: [{ name: "amount", asc: true }],
};

export class AveaEmployeePayListController extends ListController {
    static template = "avea_till.EmployeePayList";
    static components = { ...ListController.components, Pager };

    setup() {
        super.setup();
        this.actionService = useService("action");
        this.filterState = useState({
            searchText: "",
            status: "all",
            sortBy: "newest",
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
        return _t("Pay history");
    }

    get listSubtitle() {
        return _t(
            "Every salary and advance. An advance is salary paid early — it comes off the next salary."
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
                ["avea_employee_id.name", "ilike", query],
                ["payment_ref", "ilike", query],
                ["journal_id.name", "ilike", query]
            );
        }
        switch (this.filterState.status) {
            case "salary":
                domain.push(["avea_staff_pay_kind", "=", "salary"]);
                break;
            case "advance":
                domain.push(["avea_staff_pay_kind", "=", "advance"]);
                break;
            default:
                break;
        }
        return domain;
    }

    _getOrderBy() {
        return ORDER_BY_MAP[this.filterState.sortBy] || ORDER_BY_MAP.newest;
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
        this.applyFilters();
    }

    _statusButtonClass(value) {
        const active = this.filterState.status === value;
        return `btn o_avea_period_btn ${active ? "btn-primary" : "btn-outline-secondary"}`;
    }

    async onClickEmployees() {
        await this.actionService.doAction("avea_till.action_avea_employee_centre");
    }

    async onClickRecordSalary() {
        await this.actionService.doAction("avea_till.action_avea_withdraw_cash_wizard");
    }
}

registry.category("views").add("avea_employee_pay_list", {
    ...listView,
    Controller: AveaEmployeePayListController,
});
