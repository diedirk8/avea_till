/** @odoo-module **/

import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { formatMonetary } from "@web/views/fields/formatters";

import { Component } from "@odoo/owl";

export class CreditLedgerAmountField extends Component {
    static template = "avea_till.CreditLedgerAmountField";
    static props = {
        ...standardFieldProps,
        currencyField: { type: String, optional: true },
    };

    get displayMode() {
        if (this.props.record.data.reason_is_outflow) {
            return "out";
        }
        if (this.props.record.data.reason_id) {
            return "in";
        }
        return "neutral";
    }

    get icon() {
        if (this.displayMode === "in") {
            return "▲";
        }
        if (this.displayMode === "out") {
            return "▼";
        }
        return "●";
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
        if (this.displayMode === "in") {
            return `+${formatted}`;
        }
        if (this.displayMode === "out") {
            return `-${formatted}`;
        }
        return formatted;
    }

    get cssClass() {
        if (this.displayMode === "in") {
            return "o_avea_credit_ledger_amount_in";
        }
        if (this.displayMode === "out") {
            return "o_avea_credit_ledger_amount_out";
        }
        return "o_avea_credit_ledger_amount_neutral";
    }
}

export const creditLedgerAmountField = {
    component: CreditLedgerAmountField,
    supportedTypes: ["monetary", "float"],
};

registry.category("fields").add("credit_ledger_amount", creditLedgerAmountField);
