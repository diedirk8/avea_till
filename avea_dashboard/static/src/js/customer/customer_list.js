/** @odoo-module **/

import { Pager } from "@web/core/pager/pager";
import { ListController } from "@web/views/list/list_controller";
import { listView } from "@web/views/list/list_view";
import { registry } from "@web/core/registry";
import { debounce } from "@web/core/utils/timing";
import { useState, onMounted, onWillUnmount } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";

const BASE_DOMAIN = [["customer_rank", ">", 0]];
const ACTION_MANAGER_SCROLL_CLASS = "o_avea_customer_list_action_manager";

const STATUS_OPTIONS = [
    { value: "all", label: "All" },
    { value: "active", label: "Active" },
    { value: "credit", label: "Store credit" },
    { value: "with_sales", label: "With sales" },
    {
        value: "follow_up",
        label: "Customers to follow up",
        hint:
            "Regular customers who have not been in as long as they usually do. Check usual visits, usual spend per visit, last visit, and what they usually buy.",
    },
    { value: "archived", label: "Archived" },
];

const SORT_OPTIONS = [
    { value: "name_asc", label: "Name A–Z" },
    { value: "name_desc", label: "Name Z–A" },
    { value: "newest", label: "Newest first" },
    { value: "oldest", label: "Oldest first" },
    { value: "credit_desc", label: "Store credit high–low" },
    { value: "sales_desc", label: "Total sales high–low" },
    { value: "last_visit_desc", label: "Last visit (recent first)" },
    { value: "days_away_desc", label: "Longest away first" },
];

const ORDER_BY_MAP = {
    name_asc: [{ name: "name", asc: true }],
    name_desc: [{ name: "name", asc: false }],
    newest: [{ name: "create_date", asc: false }],
    oldest: [{ name: "create_date", asc: true }],
    credit_desc: [{ name: "avea_credit_balance", asc: false }],
    sales_desc: [{ name: "avea_pos_sales_total", asc: false }],
    last_visit_desc: [{ name: "avea_last_visit", asc: false }],
    days_away_desc: [{ name: "avea_days_since_visit", asc: false }],
};

export class AveaCustomerListController extends ListController {
    static template = "avea_till.CustomerList";
    static components = { ...ListController.components, Pager };

    setup() {
        super.setup();
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.notification = useService("notification");
        this.filterState = useState({
            searchText: "",
            status: "active",
            sortBy: "name_asc",
        });
        this._applyFiltersDebounced = debounce(() => this.applyFilters(), 300);
        onMounted(() => this._onFiltersMounted());
        onWillUnmount(() => this._teardownScrollShell());
    }

    get className() {
        const base = this.props.className || "";
        return `${base} o_avea_workspace o_avea_workspace--customer o_avea_workspace--customer-list`.trim();
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

    get activeStatusHint() {
        if (this.duplicateReviewActive) {
            return "";
        }
        const option = STATUS_OPTIONS.find(
            (entry) => entry.value === this.filterState.status
        );
        return option?.hint || "";
    }

    get duplicateReviewActive() {
        return Boolean(this.props.context?.avea_duplicate_review);
    }

    get listTitle() {
        return this.duplicateReviewActive ? _t("Possible duplicates") : _t("Customers");
    }

    get listSubtitle() {
        if (this.duplicateReviewActive) {
            return _t(
                "Customers who share an email or phone number with someone else. Select two or three, then merge."
            );
        }
        if (this.filterState.status === "follow_up") {
            return _t(
                "Customers to follow up — usual visits, usual spend per visit, last visit, and what they usually buy."
            );
        }
        return _t(
            "Search by name, email, or phone. Filter and sort to find who to follow up with."
        );
    }

    get selectedCustomerIds() {
        return this.model.root.selection.map((record) => record.resId);
    }

    get hasSelectedCustomers() {
        return this.selectedCustomerIds.length > 0;
    }

    get canMergeSelection() {
        const count = this.selectedCustomerIds.length;
        return count >= 2 && count <= 3;
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
            case "credit":
                domain.push(["avea_credit_balance", ">", 0]);
                break;
            case "with_sales":
                domain.push(["avea_pos_order_count", ">", 0]);
                break;
            case "follow_up":
                domain.push(
                    ...(await this.orm.call("res.partner", "avea_customer_lapsed_domain", []))
                );
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
        if (status === "follow_up") {
            this.filterState.sortBy = "days_away_desc";
            this.applyFilters({ useDropdownOrder: true });
            return;
        }
        this.applyFilters();
    }

    _statusButtonClass(value) {
        const active = this.filterState.status === value;
        return `btn o_avea_period_btn ${active ? "btn-primary" : "btn-outline-secondary"}`;
    }

    async onClickCreateCustomer() {
        await this.createRecord();
    }

    async onClickPossibleDuplicates() {
        const action = await this.orm.call(
            "res.partner",
            "action_avea_show_possible_duplicates",
            []
        );
        if (!action?.type) {
            return;
        }
        await this.actionService.doAction(action);
    }

    async onClickAllCustomers() {
        await this.actionService.doAction("avea_till.action_avea_customer_centre");
    }

    async onClickMergeCustomers() {
        const ids = this.selectedCustomerIds;
        if (ids.length < 2) {
            this.notification.add(
                _t("Select at least two customers to merge."),
                { type: "warning" }
            );
            return;
        }
        if (ids.length > 3) {
            this.notification.add(
                _t(
                    "Merge at most three customers at a time. Select fewer, merge, then repeat if needed."
                ),
                { type: "warning" }
            );
            return;
        }
        const action = await this.orm.call(
            "res.partner",
            "action_avea_merge_customers",
            [ids]
        );
        if (!action?.type) {
            return;
        }
        await this.actionService.doAction(action, {
            onClose: () => this.model.load(),
        });
    }

    async onClickClearSelection() {
        this.model.root.records.forEach((record) => record.toggleSelection(false));
    }
}

registry.category("views").add("avea_customer_list", {
    ...listView,
    Controller: AveaCustomerListController,
});
