/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { patch } from "@web/core/utils/patch";
import { Many2XAutocomplete } from "@web/views/fields/relational_utils";
import { Many2One } from "@web/views/fields/many2one/many2one";
import {
    Many2OneField,
    buildM2OFieldDescription,
} from "@web/views/fields/many2one/many2one_field";

patch(Many2XAutocomplete.prototype, {
    buildCreateSuggestion(request) {
        const suggestion = super.buildCreateSuggestion(request);
        if (this.props.aveaExpenseSupplierCreate) {
            return {
                ...suggestion,
                label: _t('Add new supplier "%s"', request),
            };
        }
        return suggestion;
    },
});

class AveaExpenseSupplierMany2One extends Many2One {
    get many2XAutocompleteProps() {
        return {
            ...super.many2XAutocompleteProps,
            aveaExpenseSupplierCreate: true,
        };
    }

    async quickCreate(name) {
        const [id, displayName] = await this.orm.call(
            this.props.relation,
            "name_create",
            [name],
            { context: this.props.context }
        );
        return this.update({ id, display_name: displayName });
    }
}

class AveaExpenseSupplierMany2OneField extends Many2OneField {
    static components = { Many2One: AveaExpenseSupplierMany2One };
}

registry.category("fields").add(
    "avea_expense_supplier_many2one",
    buildM2OFieldDescription(AveaExpenseSupplierMany2OneField)
);
