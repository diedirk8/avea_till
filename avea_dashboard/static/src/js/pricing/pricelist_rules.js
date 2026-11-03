/** @odoo-module **/

import { ListRenderer } from "@web/views/list/list_renderer";
import { listView } from "@web/views/list/list_view";
import { registry } from "@web/core/registry";

export class AveaPricelistRulesRenderer extends ListRenderer {
    getRowClass(record) {
        const base = super.getRowClass ? super.getRowClass(record) : "o_data_row";
        const method = record?.data?.avea_method || "";
        return `${base} o_avea_pricelist_rule_card o_avea_method_${method}`.trim();
    }

    getCellClass(column, record) {
        const base = super.getCellClass ? super.getCellClass(column, record) : "o_data_cell";
        const applied = record?.data?.applied_on;
        const hide =
            (column.name === "categ_id" && applied !== "2_product_category") ||
            (column.name === "product_tmpl_id" && applied !== "1_product") ||
            (column.name === "product_id" && applied !== "0_product_variant");
        return hide ? `${base} o_invisible_modifier` : base;
    }
}

registry.category("views").add("avea_pricelist_rules", {
    ...listView,
    Renderer: AveaPricelistRulesRenderer,
});
