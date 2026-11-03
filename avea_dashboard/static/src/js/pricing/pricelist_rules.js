/** @odoo-module **/

import { ListRenderer } from "@web/views/list/list_renderer";
import { listView } from "@web/views/list/list_view";
import { registry } from "@web/core/registry";
import { patch } from "@web/core/utils/patch";

function _isAveaPricelistRules(renderer) {
    const className = renderer.props?.archInfo?.className || renderer.props?.class || "";
    return String(className).includes("o_avea_pricelist_lines");
}

function _hideUnusedScopeCell(column, record) {
    const applied = record?.data?.applied_on;
    return (
        (column.name === "categ_id" && applied !== "2_product_category") ||
        (column.name === "product_tmpl_id" && applied !== "1_product") ||
        (column.name === "product_id" && applied !== "0_product_variant")
    );
}

export class AveaPricelistRulesRenderer extends ListRenderer {
    getRowClass(record) {
        const base = super.getRowClass(record);
        const method = record?.data?.avea_method || "";
        return `${base} o_avea_pricelist_rule_card o_avea_method_${method}`.trim();
    }

    getCellClass(column, record) {
        const base = super.getCellClass(column, record);
        return _hideUnusedScopeCell(column, record) ? `${base} o_invisible_modifier` : base;
    }
}

registry.category("views").add("avea_pricelist_rules", {
    ...listView,
    Renderer: AveaPricelistRulesRenderer,
});

// Nested x2many lists keep js_class as a CSS hook but still use ListRenderer.
patch(ListRenderer.prototype, {
    getRowClass(record) {
        const base = super.getRowClass(record);
        if (!_isAveaPricelistRules(this)) {
            return base;
        }
        const method = record?.data?.avea_method || "";
        return `${base} o_avea_pricelist_rule_card o_avea_method_${method}`.trim();
    },
    getCellClass(column, record) {
        const base = super.getCellClass(column, record);
        if (!_isAveaPricelistRules(this) || !_hideUnusedScopeCell(column, record)) {
            return base;
        }
        return `${base} o_invisible_modifier`;
    },
});
