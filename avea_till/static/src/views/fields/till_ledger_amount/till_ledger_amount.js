/** @odoo-module **/

import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { formatMonetary } from "@web/views/fields/formatters";

import { Component } from "@odoo/owl";

export class TillLedgerAmountField extends Component {
    static template = "avea_till.TillLedgerAmountField";
    static props = {
        ...standardFieldProps,
        currencyField: { type: String, optional: true },
    };

    get isInflow() {
        return this.props.record.data.movement_type === "in";
    }

    get icon() {
        return this.isInflow ? "▲" : "▼";
    }

    get signedAmount() {
        const value = this.props.record.data[this.props.name];
        if (value === false) {
            return "";
        }
        const formatted = formatMonetary(value, {
            data: this.props.record.data,
            field: this.props.record.fields[this.props.name],
            currencyField:
                this.props.currencyField ||
                this.props.record.fields[this.props.name].currency_field ||
                "currency_id",
        });
        const sign = this.isInflow ? "+" : "-";
        return `${sign}${formatted}`;
    }

    get cssClass() {
        return this.isInflow
            ? "o_avea_till_ledger_amount_in"
            : "o_avea_till_ledger_amount_out";
    }
}

export const tillLedgerAmountField = {
    component: TillLedgerAmountField,
    supportedTypes: ["monetary", "float"],
};

registry.category("fields").add("till_ledger_amount", tillLedgerAmountField);
