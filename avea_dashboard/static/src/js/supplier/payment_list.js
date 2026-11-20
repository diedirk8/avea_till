/** @odoo-module **/

import { Pager } from "@web/core/pager/pager";
import { ListController } from "@web/views/list/list_controller";
import { listView } from "@web/views/list/list_view";
import { registry } from "@web/core/registry";
import { debounce } from "@web/core/utils/timing";
import { useState, onMounted, onWillUnmount } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";

const ACTION_MANAGER_SCROLL_CLASS = "o_avea_customer_list_action_manager";
const BODY_PAGE_CLASS = "o_avea_customer_list_page";

const STATUS_OPTIONS = [
    { value: "all", label: "All" },
    { value: "bills", label: "Bill payments" },
    { value: "unmatched", label: "Not on a statement yet" },
    { value: "matched", label: "Matched to bank" },
];

const SORT_OPTIONS = [
    { value: "newest", label: "Newest first" },
    { value: "oldest", label: "Oldest first" },
    { value: "amount_desc", label: "Amount high–low" },
];

const ORDER_BY_MAP = {
    newest: [{ name: "date", asc: false }, { name: "id", asc: false }],
    oldest: [{ name: "date", asc: true }, { name: "id", asc: true }],
    amount_desc: [{ name: "amount", asc: true }],
};

export class AveaSupplierPaymentListController extends ListController {
    static template = "avea_till.SupplierPaymentList";
    static components = { ...ListController.components, Pager };

    setup() {
        super.setup();
        this.actionService = useService("action");
        this.filterState = useState({
            searchText: "",
            status: "bills",
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
        return _t("Payments");
    }

    get listSubtitle() {
        return _t(
            "Bill payments are cash or bank lines applied to supplier bills. Only an administrator can delete a mistaken payment."
        );
    }

    async onClickNewPayment() {
        await this.actionService.doAction("avea_till.action_avea_pay_bills_wizard");
    }

    _getActionDomain() {
        return this.props.domain?.length ? [...this.props.domain] : [];
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

    _buildFilterDomain() {
        const domain = [...this._getActionDomain()];
        const query = this.filterState.searchText.trim();
        if (query) {
            domain.push(
                "|",
                "|",
                ["partner_id", "ilike", query],
                ["payment_ref", "ilike", query],
                ["journal_id", "ilike", query]
            );
        }
        if (this.filterState.status === "bills") {
            domain.push(["avea_is_bill_payment", "=", true]);
        } else if (this.filterState.status === "unmatched") {
            domain.push(["avea_cleared", "=", false]);
        } else if (this.filterState.status === "matched") {
            domain.push(["avea_cleared", "=", true]);
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
            domain: this._buildFilterDomain(),
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
}

registry.category("views").add("avea_supplier_payment_list", {
    ...listView,
    Controller: AveaSupplierPaymentListController,
});
