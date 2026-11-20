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
    { value: "draft", label: "Drafts" },
    { value: "done", label: "Received" },
];

const SORT_OPTIONS = [
    { value: "newest", label: "Newest first" },
    { value: "oldest", label: "Oldest first" },
    { value: "supplier_asc", label: "Supplier A–Z" },
];

const ORDER_BY_MAP = {
    newest: [
        { name: "state", asc: false },
        { name: "write_date", asc: false },
        { name: "id", asc: false },
    ],
    oldest: [
        { name: "received_date", asc: true },
        { name: "id", asc: true },
    ],
    supplier_asc: [{ name: "partner_id", asc: true }],
};

export class AveaStockReceiveListController extends ListController {
    static template = "avea_till.StockReceiveList";
    static components = { ...ListController.components, Pager };

    setup() {
        super.setup();
        this.orm = useService("orm");
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
        return `${base} o_avea_catalogue_flush o_avea_workspace o_avea_workspace--stock o_avea_workspace--customer-list`.trim();
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
        return _t("Receive Stock");
    }

    get listSubtitle() {
        return _t(
            "Drafts stay here until you receive them. Press New to start another supplier without losing an open draft."
        );
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
        const domain = this.props.domain?.length ? [...this.props.domain] : [];
        const query = this.filterState.searchText.trim();
        if (query) {
            domain.push("|", ["partner_id", "ilike", query], ["invoice_number", "ilike", query]);
        }
        if (this.filterState.status === "draft") {
            domain.push(["state", "=", "draft"]);
        } else if (this.filterState.status === "done") {
            domain.push(["state", "=", "done"]);
        }
        return domain;
    }

    _getOrderBy() {
        return ORDER_BY_MAP[this.filterState.sortBy] || ORDER_BY_MAP.newest;
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

    onStatusClick(status) {
        this.filterState.status = status;
        this.applyFilters();
    }

    _statusButtonClass(value) {
        const active = this.filterState.status === value;
        return `btn o_avea_period_btn ${active ? "btn-primary" : "btn-outline-secondary"}`;
    }

    async onClickNewReceive() {
        const action = await this.orm.call("avea.stock.receive", "action_new_receive", []);
        await this.actionService.doAction(action);
    }

    async openRecord(record) {
        const action = await this.orm.call("avea.stock.receive", "action_open_record", [
            [record.resId],
        ]);
        await this.actionService.doAction(action);
    }
}

registry.category("views").add("avea_stock_receive_list", {
    ...listView,
    Controller: AveaStockReceiveListController,
});
