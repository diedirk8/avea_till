/** @odoo-module **/

import { Component } from "@odoo/owl";
import { usePos } from "@point_of_sale/app/hooks/pos_hook";
import { _t } from "@web/core/l10n/translation";

export class AveaCategorySelector extends Component {
    static template = "avea_till.AveaCategorySelector";
    static props = {};

    setup() {
        this.pos = usePos();
    }

    get allProductsLabel() {
        return _t("All Products");
    }

    get configuredNavCategories() {
        const configured = this.pos.config.avea_nav_category_ids || [];
        if (!configured.length) {
            return [];
        }
        return configured
            .filter((category) => category.hasProductsToShow)
            .sort((a, b) => a.sequence - b.sequence);
    }

    get rootCategories() {
        const configured = this.configuredNavCategories;
        if (configured.length) {
            return configured;
        }
        const { limit_categories, iface_available_categ_ids } = this.pos.config;
        let categories = this.pos.models["pos.category"]
            .getAll()
            .filter((category) => !category.parent_id)
            .sort((a, b) => a.sequence - b.sequence);
        if (limit_categories && iface_available_categ_ids.length > 0) {
            categories = iface_available_categ_ids
                .filter((category) => !category.parent_id)
                .sort((a, b) => a.sequence - b.sequence);
        }
        return categories.filter((category) => category.hasProductsToShow);
    }

    get visibleCategories() {
        const selected = this.pos.selectedCategory;
        if (!selected?.id) {
            return this.rootCategories;
        }
        const children = (selected.child_ids || []).filter((category) => category.hasProductsToShow);
        if (children.length) {
            return children;
        }
        if (selected.parent_id) {
            return (selected.parent_id.child_ids || []).filter((category) => category.hasProductsToShow);
        }
        return this.rootCategories;
    }

    get showParentPill() {
        const selected = this.pos.selectedCategory;
        return Boolean(selected?.id && selected.parent_id);
    }

    get parentCategory() {
        return this.pos.selectedCategory?.parent_id;
    }

    isAllProductsSelected() {
        return !this.pos.selectedCategory?.id;
    }

    isCategorySelected(category) {
        return this.pos.selectedCategory?.id === category.id;
    }

    selectAllProducts() {
        this.pos.setSelectedCategory(0);
    }

    selectCategory(category) {
        this.pos.setSelectedCategory(category.id);
    }

    selectParentCategory() {
        const parent = this.parentCategory;
        if (parent) {
            this.pos.setSelectedCategory(parent.id);
        }
    }
}
