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
        if (this.props.aveaStaffPayeeCreate) {
            return {
                ...suggestion,
                label: _t('Add new employee "%s"', request),
            };
        }
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
        const ctx = this.props.context || {};
        const asPerson = Boolean(ctx.avea_expense_payee_person || ctx.avea_staff_payee);
        return {
            ...super.many2XAutocompleteProps,
            aveaExpenseSupplierCreate: !asPerson,
            aveaStaffPayeeCreate: asPerson,
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

class AveaEmployeeMany2One extends Many2One {
    get many2XAutocompleteProps() {
        return {
            ...super.many2XAutocompleteProps,
            aveaStaffPayeeCreate: true,
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

class AveaEmployeeMany2OneField extends Many2OneField {
    static components = { Many2One: AveaEmployeeMany2One };
}

registry.category("fields").add(
    "avea_employee_many2one",
    buildM2OFieldDescription(AveaEmployeeMany2OneField)
);
