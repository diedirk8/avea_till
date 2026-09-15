/** @odoo-module **/

import { Component, onMounted, onWillUnmount, useRef, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { debounce } from "@web/core/utils/timing";

const SELECTED_SUMMARY_LIMIT = 8;

export class AveaStockTakeClientAction extends Component {
    static template = "avea_till.StockTake";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.rootRef = useRef("root");
        this.countInputRef = useRef("countInput");
        this.searchInputRef = useRef("searchInput");
        this._scrollTargets = [];
        this.barcodeBuffer = "";
        this.state = useState({
            loading: true,
            step: "start",
            stockTake: null,
            options: null,
            previewCount: null,
            matchedProducts: [],
            matchedCount: 0,
            matchedTruncated: false,
            productsLoading: false,
            selectedProducts: {},
            showCancelConfirm: false,
            form: this._defaultForm(),
            search: "",
            activeLineId: null,
            countValue: "",
        });
        this._selectionDebounced = debounce(() => this._refreshSelection(), 250);
        onMounted(() => {
            this._enableActionScroll();
            this._loadInitial();
        });
        onWillUnmount(() => {
            this._disableActionScroll();
            this._detachBarcodeListener();
        });
    }

    _enableActionScroll() {
        if (this._scrollTargets.length) {
            return;
        }
        const root = this.rootRef.el;
        if (!root) {
            window.requestAnimationFrame(() => this._enableActionScroll());
            return;
        }
        const actionEl = root.closest(".o_action");
        const managerEl = root.closest(".o_action_manager");
        const targets = [managerEl, actionEl].filter(Boolean);
        if (!targets.length) {
            return;
        }
        for (const el of targets) {
            this._scrollTargets.push({
                el,
                className: el.className,
                overflow: el.style.overflow,
                overflowX: el.style.overflowX,
                overflowY: el.style.overflowY,
                height: el.style.height,
                maxHeight: el.style.maxHeight,
                minHeight: el.style.minHeight,
                display: el.style.display,
            });
            if (el.classList.contains("o_action_manager")) {
                el.classList.add("o_avea_stock_take_action_manager");
                el.style.overflowY = "auto";
                el.style.overflowX = "hidden";
            }
            if (el.classList.contains("o_action")) {
                el.classList.add("o_avea_stock_take_action");
                el.style.display = "block";
                el.style.height = "auto";
                el.style.maxHeight = "none";
                el.style.minHeight = "0";
                el.style.overflow = "visible";
            }
        }
    }

    _disableActionScroll() {
        for (const saved of this._scrollTargets) {
            const { el, className, ...styles } = saved;
            el.className = className;
            for (const [key, value] of Object.entries(styles)) {
                el.style[key] = value;
            }
        }
        this._scrollTargets = [];
    }

    _defaultForm() {
        return {
            scope_mode: "everything",
            counting_mode: "review",
            filter_product_name: "",
            filter_sku: "",
            filter_barcode: "",
            filter_category_id: "",
            filter_supplier_id: "",
            filter_stock_status: "all",
            manual_product_ids: [],
        };
    }

    async _loadInitial() {
        this.state.loading = true;
        try {
            const options = await this.orm.call("avea.stock.take", "get_filter_options", []);
            this.state.options = options;
            const stockTakeId = this.props.action?.params?.stock_take_id;
            if (stockTakeId) {
                const payload = await this.orm.call(
                    "avea.stock.take",
                    "get_workspace_state",
                    [[stockTakeId]]
                );
                this._setStockTake(payload);
            } else {
                this.state.step = "start";
                await this._refreshSelection();
            }
        } finally {
            this.state.loading = false;
            this._attachBarcodeListener();
        }
    }

    _setStockTake(payload) {
        this.state.stockTake = payload;
        if (payload.state === "applied") {
            this.state.step = "complete";
        } else if (payload.state === "review") {
            this.state.step = "review";
        } else if (payload.state === "counting") {
            this.state.step = "counting";
            this._selectNextLine();
        } else {
            this.state.step = "start";
            this.state.form = {
                scope_mode: payload.scope_mode,
                counting_mode: payload.counting_mode || "review",
                filter_product_name: payload.filter_product_name,
                filter_sku: payload.filter_sku,
                filter_barcode: payload.filter_barcode,
                filter_category_id: payload.filter_category_id || "",
                filter_supplier_id: payload.filter_supplier_id || "",
                filter_stock_status: payload.filter_stock_status || "all",
                manual_product_ids: payload.manual_product_ids || [],
            };
            this._loadSelectedProductDetails(payload.manual_product_ids || []);
            this._refreshSelection();
        }
    }

    get stockTake() {
        return this.state.stockTake;
    }

    get isPartial() {
        return this.state.form.scope_mode === "partial";
    }

    get hasPartialFilter() {
        const form = this.state.form;
        return Boolean(
            form.filter_product_name.trim() ||
                form.filter_sku.trim() ||
                form.filter_barcode.trim() ||
                form.filter_category_id ||
                form.filter_supplier_id ||
                (form.filter_stock_status && form.filter_stock_status !== "all")
        );
    }

    get selectedCount() {
        return this.state.form.manual_product_ids.length;
    }

    get allVisibleSelected() {
        const visibleIds = this.state.matchedProducts.map((product) => product.id);
        return (
            visibleIds.length > 0 &&
            visibleIds.every((id) => this.state.form.manual_product_ids.includes(id))
        );
    }

    get visibleSelectedCount() {
        return this.state.matchedProducts.filter((product) =>
            this.isProductSelected(product.id)
        ).length;
    }

    get selectedProductsList() {
        return this.state.form.manual_product_ids
            .map((id) => this.state.selectedProducts[id])
            .filter((product) => product);
    }

    get selectedSummaryProducts() {
        return this.selectedProductsList.slice(0, SELECTED_SUMMARY_LIMIT);
    }

    get selectedSummaryOverflow() {
        const overflow = this.selectedCount - SELECTED_SUMMARY_LIMIT;
        return overflow > 0 ? overflow : 0;
    }

    get canStartStockTake() {
        if (this.state.form.scope_mode === "partial") {
            return this.selectedCount > 0;
        }
        return (this.state.previewCount || 0) > 0;
    }

    get startCountLabel() {
        if (this.state.form.scope_mode === "partial") {
            return this.selectedCount;
        }
        return this.state.previewCount || 0;
    }

    isProductSelected(productId) {
        return this.state.form.manual_product_ids.includes(productId);
    }

    get progressPercent() {
        const total = this.stockTake?.line_count || 0;
        if (!total) {
            return 0;
        }
        return Math.round((this.stockTake.counted_count / total) * 100);
    }

    get filteredLines() {
        const query = this.state.search.trim().toLowerCase();
        const lines = this.stockTake?.lines || [];
        if (!query) {
            return lines;
        }
        return lines.filter(
            (line) =>
                line.product_name.toLowerCase().includes(query) ||
                (line.default_code || "").toLowerCase().includes(query) ||
                (line.barcode || "").toLowerCase().includes(query)
        );
    }

    get activeLine() {
        const lines = this.stockTake?.lines || [];
        return lines.find((line) => line.id === this.state.activeLineId) || null;
    }

    get differenceLines() {
        return (this.stockTake?.lines || []).filter(
            (line) => line.is_counted && Math.abs(line.difference_qty || 0) > 0.0001
        );
    }

    get matchedLines() {
        return (this.stockTake?.lines || []).filter(
            (line) => line.is_counted && Math.abs(line.difference_qty || 0) <= 0.0001
        );
    }

    _formPayload() {
        return {
            scope_mode: this.state.form.scope_mode,
            counting_mode: "review",
            filter_product_name: this.state.form.filter_product_name,
            filter_sku: this.state.form.filter_sku,
            filter_barcode: this.state.form.filter_barcode,
            filter_category_id: this.state.form.filter_category_id || false,
            filter_supplier_id: this.state.form.filter_supplier_id || false,
            filter_stock_status: this.state.form.filter_stock_status,
            manual_product_ids: [[6, 0, this.state.form.manual_product_ids]],
        };
    }

    _filterPayload() {
        return {
            scope_mode: "partial",
            filter_product_name: this.state.form.filter_product_name,
            filter_sku: this.state.form.filter_sku,
            filter_barcode: this.state.form.filter_barcode,
            filter_category_id: this.state.form.filter_category_id || false,
            filter_supplier_id: this.state.form.filter_supplier_id || false,
            filter_stock_status: this.state.form.filter_stock_status,
        };
    }

    async _refreshPreview() {
        const result = await this.orm.call("avea.stock.take", "preview_product_count", [this._formPayload()]);
        this.state.previewCount = result.count;
    }

    _rememberProduct(product) {
        this.state.selectedProducts = {
            ...this.state.selectedProducts,
            [product.id]: {
                id: product.id,
                name: product.name,
                default_code: product.default_code || "",
            },
        };
    }

    _forgetProduct(productId) {
        const selectedProducts = { ...this.state.selectedProducts };
        delete selectedProducts[productId];
        this.state.selectedProducts = selectedProducts;
    }

    async _loadSelectedProductDetails(productIds) {
        if (!productIds.length) {
            return;
        }
        const missingIds = productIds.filter((id) => !this.state.selectedProducts[id]);
        if (!missingIds.length) {
            return;
        }
        const products = await this.orm.searchRead(
            "product.product",
            [["id", "in", missingIds]],
            ["id", "display_name", "default_code"]
        );
        for (const product of products) {
            this._rememberProduct({
                id: product.id,
                name: product.display_name,
                default_code: product.default_code || "",
            });
        }
    }

    async _refreshProductList() {
        if (this.state.form.scope_mode !== "partial") {
            this.state.matchedProducts = [];
            this.state.matchedCount = 0;
            this.state.matchedTruncated = false;
            return;
        }
        if (!this.hasPartialFilter) {
            this.state.matchedProducts = [];
            this.state.matchedCount = 0;
            this.state.matchedTruncated = false;
            this.state.previewCount = this.selectedCount;
            return;
        }
        this.state.productsLoading = true;
        try {
            const result = await this.orm.call(
                "avea.stock.take",
                "search_products_for_selection",
                [this._filterPayload()]
            );
            this.state.matchedProducts = result.products || [];
            this.state.matchedCount = result.count || 0;
            this.state.matchedTruncated = Boolean(result.truncated);
            for (const product of this.state.matchedProducts) {
                if (this.isProductSelected(product.id)) {
                    this._rememberProduct(product);
                }
            }
            this.state.previewCount = this.selectedCount;
        } finally {
            this.state.productsLoading = false;
        }
    }

    async _refreshSelection() {
        if (this.state.form.scope_mode === "partial") {
            await this._refreshProductList();
            return;
        }
        await this._refreshPreview();
    }

    onScopeChange(mode) {
        this.state.form.scope_mode = mode;
        if (mode === "everything") {
            this.state.form.manual_product_ids = [];
            this.state.matchedProducts = [];
            this.state.selectedProducts = {};
        }
        this._selectionDebounced();
    }

    onFilterInput(field, ev) {
        this.state.form[field] = ev.target.value;
        this._selectionDebounced();
    }

    onFilterSelect(field, ev) {
        this.state.form[field] = ev.target.value;
        this._selectionDebounced();
    }

    onToggleProduct(product, ev) {
        if (ev) {
            ev.stopPropagation();
        }
        const productId = product.id;
        const selected = [...this.state.form.manual_product_ids];
        const index = selected.indexOf(productId);
        if (index >= 0) {
            selected.splice(index, 1);
            this._forgetProduct(productId);
        } else {
            selected.push(productId);
            this._rememberProduct(product);
        }
        this.state.form.manual_product_ids = selected;
        this.state.previewCount = this.selectedCount;
    }

    onRemoveSelected(productId) {
        this.state.form.manual_product_ids = this.state.form.manual_product_ids.filter(
            (id) => id !== productId
        );
        this._forgetProduct(productId);
        this.state.previewCount = this.selectedCount;
    }

    onClearSelection() {
        this.state.form.manual_product_ids = [];
        this.state.selectedProducts = {};
        this.state.previewCount = 0;
    }

    onToggleSelectAllVisible() {
        const visibleProducts = this.state.matchedProducts;
        if (!visibleProducts.length) {
            return;
        }
        if (this.allVisibleSelected) {
            const visibleIds = new Set(visibleProducts.map((product) => product.id));
            for (const productId of visibleIds) {
                this._forgetProduct(productId);
            }
            this.state.form.manual_product_ids = this.state.form.manual_product_ids.filter(
                (id) => !visibleIds.has(id)
            );
        } else {
            const selected = new Set(this.state.form.manual_product_ids);
            for (const product of visibleProducts) {
                selected.add(product.id);
                this._rememberProduct(product);
            }
            this.state.form.manual_product_ids = Array.from(selected);
        }
        this.state.previewCount = this.selectedCount;
    }

    onContinueLater() {
        this.onDone();
    }

    onRequestCancelStockTake() {
        this.state.showCancelConfirm = true;
    }

    onDismissCancelConfirm() {
        this.state.showCancelConfirm = false;
    }

    async onCancelStockTake() {
        if (!this.stockTake?.stock_take_id) {
            await this.onStartAnother();
            return;
        }
        this.state.loading = true;
        try {
            await this.orm.call(
                "avea.stock.take",
                "action_cancel_stock_take",
                [[this.stockTake.stock_take_id]]
            );
            this.state.showCancelConfirm = false;
            this.notification.add(_t("Stock take cancelled."), { type: "info" });
            await this.onStartAnother();
        } catch (error) {
            this.notification.add(error.message || _t("Could not cancel stock take."), { type: "danger" });
        } finally {
            this.state.loading = false;
        }
    }

    async onStartStockTake() {
        if (!this.canStartStockTake) {
            return;
        }
        this.state.loading = true;
        try {
            let payload;
            if (this.stockTake?.stock_take_id && this.stockTake.state === "draft") {
                await this.orm.write("avea.stock.take", [this.stockTake.stock_take_id], this._formPayload());
                payload = await this.orm.call(
                    "avea.stock.take",
                    "action_start_counting",
                    [[this.stockTake.stock_take_id]]
                );
            } else {
                payload = await this.orm.call("avea.stock.take", "create_stock_take", [this._formPayload()]);
                payload = await this.orm.call(
                    "avea.stock.take",
                    "action_start_counting",
                    [[payload.stock_take_id]]
                );
            }
            this._setStockTake(payload);
            this.state.step = "counting";
            this._selectNextLine();
        } catch (error) {
            this.notification.add(error.message || _t("Could not start stock take."), { type: "danger" });
        } finally {
            this.state.loading = false;
        }
    }

    _selectNextLine() {
        const next = (this.stockTake?.lines || []).find((line) => !line.is_counted);
        if (next) {
            this.state.activeLineId = next.id;
            this.state.countValue = "";
            this._focusCountInput();
        } else {
            this.state.activeLineId = null;
            this.state.countValue = "";
        }
    }

    onSelectLine(line) {
        if (line.is_applied) {
            return;
        }
        this.state.activeLineId = line.id;
        this.state.countValue = line.is_counted ? String(line.counted_qty) : "";
        this._focusCountInput();
    }

    onSearchInput(ev) {
        this.state.search = ev.target.value;
        const query = this.state.search.trim().toLowerCase();
        if (!query) {
            return;
        }
        const exact = (this.stockTake?.lines || []).find(
            (line) =>
                (line.barcode && line.barcode.toLowerCase() === query) ||
                (line.default_code && line.default_code.toLowerCase() === query)
        );
        if (exact) {
            this.onSelectLine(exact);
        }
    }

    onCountInput(ev) {
        this.state.countValue = ev.target.value;
    }

    onCountKeydown(ev) {
        if (ev.key === "Enter") {
            ev.preventDefault();
            this.onConfirmCount();
        }
    }

    async onConfirmCount() {
        const line = this.activeLine;
        if (!line) {
            return;
        }
        const qty = Number(this.state.countValue);
        if (Number.isNaN(qty) || qty < 0) {
            this.notification.add(_t("Enter a valid counted quantity."), { type: "warning" });
            return;
        }
        this.state.loading = true;
        try {
            const payload = await this.orm.call(
                "avea.stock.take",
                "action_record_count",
                [[this.stockTake.stock_take_id], line.id, qty]
            );
            this._setStockTake(payload);
            this._selectNextLine();
        } catch (error) {
            this.notification.add(error.message || _t("Could not save count."), { type: "danger" });
        } finally {
            this.state.loading = false;
        }
    }

    async onReview() {
        this.state.loading = true;
        try {
            const payload = await this.orm.call(
                "avea.stock.take",
                "action_prepare_review",
                [[this.stockTake.stock_take_id]]
            );
            this._setStockTake(payload);
            this.state.step = "review";
        } catch (error) {
            this.notification.add(error.message || _t("Review is not ready yet."), { type: "warning" });
        } finally {
            this.state.loading = false;
        }
    }

    async onBackToCounting() {
        const payload = await this.orm.call(
            "avea.stock.take",
            "action_reopen_counting",
            [[this.stockTake.stock_take_id]]
        );
        this._setStockTake(payload);
        this.state.step = "counting";
        this._selectNextLine();
    }

    async onApplyStockTake() {
        this.state.loading = true;
        try {
            const payload = await this.orm.call(
                "avea.stock.take",
                "action_apply_stock_take",
                [[this.stockTake.stock_take_id]]
            );
            this._setStockTake(payload);
            this.state.step = "complete";
        } catch (error) {
            this.notification.add(error.message || _t("Could not complete stock take."), { type: "danger" });
        } finally {
            this.state.loading = false;
        }
    }

    async onStartAnother() {
        this.state.stockTake = null;
        this.state.form = this._defaultForm();
        this.state.step = "start";
        this.state.search = "";
        this.state.activeLineId = null;
        this.state.countValue = "";
        this.state.showCancelConfirm = false;
        this.state.matchedProducts = [];
        this.state.matchedCount = 0;
        this.state.matchedTruncated = false;
        this.state.selectedProducts = {};
        await this._refreshSelection();
    }

    onDone() {
        this.action.doAction("avea_till.action_avea_stock_workspace");
    }

    _focusCountInput() {
        window.setTimeout(() => {
            const input = this.countInputRef.el;
            if (input) {
                input.focus();
                input.select();
            }
        }, 50);
    }

    _attachBarcodeListener() {
        this._barcodeHandler = (ev) => this._onBarcodeKey(ev);
        document.addEventListener("keydown", this._barcodeHandler);
    }

    _detachBarcodeListener() {
        if (this._barcodeHandler) {
            document.removeEventListener("keydown", this._barcodeHandler);
        }
    }

    _onBarcodeKey(ev) {
        if (this.state.step !== "counting") {
            return;
        }
        const target = ev.target;
        if (target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.tagName === "SELECT")) {
            if (target !== this.countInputRef.el && target !== this.searchInputRef.el) {
                return;
            }
        }
        if (ev.key === "Enter" && this.barcodeBuffer.length >= 3) {
            ev.preventDefault();
            this._matchBarcode(this.barcodeBuffer);
            this.barcodeBuffer = "";
            return;
        }
        if (ev.key.length === 1 && !ev.ctrlKey && !ev.metaKey && !ev.altKey) {
            this.barcodeBuffer += ev.key;
        } else if (ev.key === "Backspace") {
            this.barcodeBuffer = this.barcodeBuffer.slice(0, -1);
        }
    }

    _matchBarcode(code) {
        const normalized = code.trim();
        const line = (this.stockTake?.lines || []).find(
            (item) => item.barcode === normalized || item.default_code === normalized
        );
        if (!line) {
            this.notification.add(_t("No product found for barcode %s", normalized), { type: "warning" });
            return;
        }
        this.onSelectLine(line);
    }

    formatQty(value) {
        if (value === null || value === undefined) {
            return "";
        }
        return Number(value).toLocaleString(undefined, {
            minimumFractionDigits: 0,
            maximumFractionDigits: 2,
        });
    }
}

registry.category("actions").add("avea_stock_take", AveaStockTakeClientAction);
