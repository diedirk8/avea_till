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
        if (column.invisible && this.evalInvisible(column.invisible, record)) {
            return `${base} o_invisible_modifier`;
        }
        return base;
    }
}

registry.category("views").add("avea_pricelist_rules", {
    ...listView,
    Renderer: AveaPricelistRulesRenderer,
});
