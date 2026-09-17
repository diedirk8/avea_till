/** @odoo-module **/

import { ProductScreen } from "@point_of_sale/app/screens/product_screen/product_screen";
import { AveaCategorySelector } from "./avea_category_selector";
import { _t } from "@web/core/l10n/translation";
import { useEffect } from "@odoo/owl";
import { patch } from "@web/core/utils/patch";

ProductScreen.template = "avea_till.ProductScreen";
patch(ProductScreen, {
    components: { ...ProductScreen.components, AveaCategorySelector },
});

const STOCK_STATUS_LABELS = {
    in_stock: _t("In stock"),
    low_stock: _t("Low stock"),
    out_of_stock: _t("Out of stock"),
    not_tracked: _t("Not tracked"),
};

const PROMOTION_PROGRAM_TYPES = new Set([
    "promotion",
    "promo_code",
    "buy_x_get_y",
    "coupons",
]);

patch(ProductScreen.prototype, {
    setup() {
        super.setup(...arguments);
        this.state.aveaProductPage = 0;
        this.state.aveaProductTab = "products";
        if (!this.pos.aveaRecentProductIds) {
            this.pos.aveaRecentProductIds = [];
        }
        useEffect(
            () => {
                this.state.aveaProductPage = 0;
            },
            () => [
                this.pos.searchProductWord,
                this.pos.selectedCategory?.id,
                this.pos.config.avea_products_per_page,
                this.pos.config.avea_product_layout,
                this.state.aveaProductTab,
            ]
        );
    },

    get aveaProductsPerPage() {
        const perPage = parseInt(this.pos.config.avea_products_per_page || "50", 10);
        return Number.isFinite(perPage) && perPage > 0 ? perPage : 50;
    },

    get aveaProductTabs() {
        return [
            { id: "products", label: _t("Products"), icon: "fa-cube" },
            { id: "favourites", label: _t("Favourites"), icon: "fa-star" },
            { id: "recent", label: _t("Recent"), icon: "fa-clock-o" },
            { id: "promotions", label: _t("Promotions"), icon: "fa-tag" },
        ];
    },

    aveaSetProductTab(tabId) {
        this.state.aveaProductTab = tabId;
        this.state.aveaProductPage = 0;
    },

    isAveaProductTabActive(tabId) {
        return this.state.aveaProductTab === tabId;
    },

    _aveaFilterProductsByTab(products) {
        const tab = this.state.aveaProductTab || "products";
        if (tab === "favourites") {
            return products.filter((product) => product.is_favorite);
        }
        if (tab === "recent") {
            const recentIds = new Set(this.pos.aveaRecentProductIds || []);
            return products.filter((product) => recentIds.has(product.id));
        }
        if (tab === "promotions") {
            const promoProductIds = this._aveaPromotionalProductTmplIds();
            return products.filter((product) => promoProductIds.has(product.id));
        }
        return products;
    },

    _aveaPromotionalProductTmplIds() {
        const tmplIds = new Set();
        const programs = this.pos.models["loyalty.program"]?.getAll() || [];
        const productModel = this.pos.models["product.product"];
        const templateModel = this.pos.models["product.template"];
        const now = new Date();

        const addVariantId = (variantId) => {
            if (!variantId) {
                return;
            }
            const variant = productModel?.get(variantId);
            const tmplId = variant?.product_tmpl_id?.id ?? variant?.product_tmpl_id;
            if (tmplId) {
                tmplIds.add(tmplId);
                return;
            }
            for (const template of templateModel?.getAll() || []) {
                const variantIds = (template.product_variant_ids || []).map((record) =>
                    typeof record === "object" ? record.id : record
                );
                if (variantIds.includes(variantId)) {
                    tmplIds.add(template.id);
                    return;
                }
            }
        };

        for (const program of programs) {
            if (
                !PROMOTION_PROGRAM_TYPES.has(program.program_type) &&
                !program.avea_is_combo
            ) {
                continue;
            }
            const configIds = program.pos_config_ids || [];
            if (configIds.length && !configIds.some((config) => config.id === this.pos.config.id)) {
                continue;
            }
            if (program.date_from) {
                const start = new Date(program.date_from);
                start.setHours(0, 0, 0, 0);
                if (now < start) {
                    continue;
                }
            }
            if (program.date_to) {
                const end = new Date(program.date_to);
                end.setHours(23, 59, 59, 999);
                if (now > end) {
                    continue;
                }
            }

            for (const rule of program.rule_ids || []) {
                const validIds = rule.validProductIds || rule.valid_product_ids || [];
                for (const variantId of validIds) {
                    addVariantId(variantId);
                }
                for (const product of rule.product_ids || []) {
                    addVariantId(product.id);
                }
            }
            for (const reward of program.reward_ids || []) {
                for (const product of reward.all_discount_product_ids || []) {
                    addVariantId(product.id);
                }
                for (const product of reward.reward_product_ids || []) {
                    addVariantId(product.id);
                }
            }
            for (const component of program.avea_combo_components || []) {
                addVariantId(component.product_id);
            }
        }
        return tmplIds;
    },

    get aveaIsListLayout() {
        return (this.pos.config.avea_product_layout || "list") === "list";
    },

    _aveaConfigFlag(field, defaultValue = true) {
        const value = this.pos.config?.[field];
        if (value === undefined || value === null) {
            return defaultValue;
        }
        return Boolean(value);
    },

    get aveaShowProductImages() {
        return this._aveaConfigFlag("show_product_images", true);
    },

    get aveaShowProductCode() {
        return this._aveaConfigFlag("avea_show_product_code", true);
    },

    get aveaShowStockQuantity() {
        return this._aveaConfigFlag("avea_show_stock_quantity", true);
    },

    get aveaShowStockStatus() {
        return this._aveaConfigFlag("avea_show_stock_status", true);
    },

    get aveaAllProducts() {
        return this._aveaFilterProductsByTab(this.pos.productsToDisplay);
    },

    async addProductToOrder(product) {
        await super.addProductToOrder(...arguments);
        const recent = (this.pos.aveaRecentProductIds || []).filter((id) => id !== product.id);
        recent.unshift(product.id);
        this.pos.aveaRecentProductIds = recent.slice(0, 50);
    },

    get aveaProductCount() {
        return this.aveaAllProducts.length;
    },

    get aveaTotalPages() {
        return Math.max(1, Math.ceil(this.aveaProductCount / this.aveaProductsPerPage));
    },

    get aveaCurrentPage() {
        const page = this.state.aveaProductPage || 0;
        return Math.min(page, this.aveaTotalPages - 1);
    },

    get aveaPaginatedProducts() {
        const start = this.aveaCurrentPage * this.aveaProductsPerPage;
        return this.aveaAllProducts.slice(start, start + this.aveaProductsPerPage);
    },

    get currentOrderDisplayRef() {
        const order = this.currentOrder;
        if (!order) {
            return "";
        }
        const label = order.getName?.() || order.tracking_number || "";
        return label ? String(label) : "";
    },

    get partnerDisplayName() {
        const partner = this.currentOrder?.getPartner();
        return partner?.name || _t("Walk-in Customer");
    },

    get aveaIsPromotionsTab() {
        return this.state.aveaProductTab === "promotions";
    },

    aveaGoToPage(page) {
        const nextPage = Math.max(0, Math.min(page, this.aveaTotalPages - 1));
        this.state.aveaProductPage = nextPage;
    },

    aveaPreviousPage() {
        this.aveaGoToPage(this.aveaCurrentPage - 1);
    },

    aveaNextPage() {
        this.aveaGoToPage(this.aveaCurrentPage + 1);
    },

    aveaToggleScan() {
        if (!this.pos.scanning) {
            const screenName = this.pos.router.state.current;
            if (screenName === "ProductScreen") {
                this.pos.navigate("ProductScreen", {
                    orderUuid: this.pos.getOrder().uuid,
                });
            }
        }
        this.pos.mobile_pane = "right";
        this.pos.scanning = !this.pos.scanning;
    },

    aveaHoldSale() {
        if (this.currentOrder?.isEmpty()) {
            return;
        }
        this.pos.addNewOrder();
        this.env.services.notification.add(_t("Sale held — switched to a new order"), {
            type: "info",
        });
    },

    aveaParkSale() {
        if (this.currentOrder?.isEmpty()) {
            return;
        }
        this.pos.clickSaveOrder();
    },

    aveaClearSale() {
        const order = this.currentOrder;
        if (!order || order.isEmpty()) {
            return;
        }
        for (const line of [...order.lines]) {
            order.removeOrderline(line);
        }
        order.deselectOrderline();
    },

    aveaToggleFavorite(product) {
        this.pos.data.write("product.template", [product.id], {
            is_favorite: !product.is_favorite,
        });
    },

    getProductCategoryLabel(product) {
        const categories = product.pos_categ_ids || [];
        if (!categories.length) {
            return "";
        }
        const category = categories[categories.length - 1];
        return category.display_name || category.name || "";
    },

    getProductCode(product) {
        return product.default_code || "";
    },

    getProductDisplayPrice(product) {
        return product.displayPriceUnit;
    },

    getStockQuantityLabel(product) {
        if (!product.is_storable) {
            return "";
        }
        const qty = this.env.utils.formatProductQty(product.avea_stock_qty || 0, false);
        return qty;
    },

    getStockStatusLabel(product) {
        const status = product.avea_stock_status;
        return STOCK_STATUS_LABELS[status] || "";
    },

    getStockStatusClass(product) {
        const status = product.avea_stock_status;
        return {
            "avea-stock-in": status === "in_stock",
            "avea-stock-low": status === "low_stock",
            "avea-stock-out": status === "out_of_stock",
            "avea-stock-none": status === "not_tracked",
        };
    },

    aveaShouldShowStock(product) {
        if (!product.is_storable) {
            return false;
        }
        return this.aveaShowStockQuantity || this.aveaShowStockStatus;
    },
});
