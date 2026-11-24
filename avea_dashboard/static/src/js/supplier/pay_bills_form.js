/** @odoo-module **/

import { FormController } from "@web/views/form/form_controller";
import { formView } from "@web/views/form/form_view";
import { registry } from "@web/core/registry";
import { onMounted, onWillUnmount } from "@odoo/owl";

export class AveaSupplierPayBillsFormController extends FormController {
    setup() {
        super.setup();
        onMounted(() => this._aveaPayBillsExpandDialog());
        onWillUnmount(() => this._aveaPayBillsRestoreDialog());
    }

    _aveaPayBillsDialogNodes() {
        const root = this.el;
        if (!root) {
            return {};
        }
        const modal = root.closest(".modal");
        const dialog = modal?.querySelector(".modal-dialog");
        const content = modal?.querySelector(".modal-content");
        return { modal, dialog, content };
    }

    _aveaPayBillsExpandDialog() {
        const { modal, dialog, content } = this._aveaPayBillsDialogNodes();
        if (!dialog) {
            window.requestAnimationFrame(() => this._aveaPayBillsExpandDialog());
            return;
        }
        dialog.classList.add("o_avea_pay_bills_fullscreen_dialog");
        content?.classList.add("o_avea_pay_bills_fullscreen_content");
        modal?.classList.add("o_avea_pay_bills_fullscreen_modal");
        document.body.classList.add("o_avea_pay_bills_fullscreen_open");
    }

    _aveaPayBillsRestoreDialog() {
        const { modal, dialog, content } = this._aveaPayBillsDialogNodes();
        dialog?.classList.remove("o_avea_pay_bills_fullscreen_dialog");
        content?.classList.remove("o_avea_pay_bills_fullscreen_content");
        modal?.classList.remove("o_avea_pay_bills_fullscreen_modal");
        document.body.classList.remove("o_avea_pay_bills_fullscreen_open");
    }
}

registry.category("views").add("avea_supplier_pay_bills_form", {
    ...formView,
    Controller: AveaSupplierPayBillsFormController,
});