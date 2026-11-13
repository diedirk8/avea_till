/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { formatMonetary } from "@web/views/fields/formatters";
import { Many2XAutocomplete } from "@web/views/fields/relational_utils";
import { Many2ManyTagsField, many2ManyTagsField } from "@web/views/fields/many2many_tags/many2many_tags_field";

export class AveaPromotionProductPickerField extends Many2ManyTagsField {
    static template = "avea_till.AveaPromotionProductPickerField";
    static components = {
        Many2XAutocomplete,
    };

    _formatMoney(record, value) {
        return formatMonetary(value ?? 0, {
            data: record.data,
            field: { currency_field: "currency_id" },
        });
    }

    _formatMarkup(value) {
        const markup = Number(value) || 0;
        return `${markup.toFixed(1)}%`;
    }

    get selectedProducts() {
        return this.props.record.data[this.props.name].records.map((record) => ({
            id: record.id,
            code: record.data.default_code || "",
            name: record.data.name || record.data.display_name || "",
            retail: this._formatMoney(record, record.data.list_price),
            cost: this._formatMoney(
                record,
                record.data.avea_cost_ex_tax || record.data.standard_price
            ),
            costIncl: this._formatMoney(record, record.data.avea_cost_incl_tax),
            profit: this._formatMoney(record, record.data.avea_profit_incl_tax),
            markup: this._formatMarkup(record.data.avea_markup_percent),
        }));
    }

    get searchPlaceholder() {
        return this.props.placeholder || _t("Search and add a product");
    }
}

export const aveaPromotionProductPickerField = {
    ...many2ManyTagsField,
    component: AveaPromotionProductPickerField,
    displayName: _t("Promotion product picker"),
    relatedFields: () => [
        { name: "display_name", type: "char" },
        { name: "default_code", type: "char" },
        { name: "name", type: "char" },
        { name: "list_price", type: "float" },
        { name: "standard_price", type: "float" },
        { name: "avea_cost_ex_tax", type: "float" },
        { name: "avea_cost_incl_tax", type: "float" },
        { name: "avea_profit_incl_tax", type: "float" },
        { name: "avea_markup_percent", type: "float" },
        { name: "currency_id", type: "many2one" },
    ],
};

registry.category("fields").add("avea_promotion_product_picker", aveaPromotionProductPickerField);
