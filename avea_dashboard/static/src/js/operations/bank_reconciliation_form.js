/** @odoo-module **/

import { FormController } from "@web/views/form/form_controller";
import { formView } from "@web/views/form/form_view";
import { registry } from "@web/core/registry";
import { patch } from "@web/core/utils/patch";
import { onMounted, onWillUnmount } from "@odoo/owl";

const RECON_MODEL = "avea.bank.reconciliation";
const ACTION_MANAGER_SCROLL_CLASS = "o_avea_bank_recon_form_action_manager";
const PANE_HEIGHT = "calc(100vh - var(--avea-topbar-height, 3.25rem))";

export class AveaBankReconciliationFormController extends FormController {
    setup() {
        super.setup();
        this._ensureAveaReconScrollHooks();
    }

    get className() {
        const base = super.className || "";
        return `${base} o_avea_workspace o_avea_workspace--overview o_avea_workspace--bank-recon-form o_avea_bank_reconcile_wizard`.trim();
    }
}

function _unlockInner(el) {
    el.style.setProperty("display", "block", "important");
    el.style.setProperty("flex", "none", "important");
    el.style.setProperty("height", "auto", "important");
    el.style.setProperty("max-height", "none", "important");
    el.style.setProperty("min-height", "0", "important");
    el.style.setProperty("overflow", "visible", "important");
    el.style.setProperty("overflow-x", "visible", "important");
    el.style.setProperty("overflow-y", "visible", "important");
}

function _unlockList(el) {
    el.style.setProperty("display", "block", "important");
    el.style.setProperty("flex", "none", "important");
    el.style.setProperty("height", "auto", "important");
    el.style.setProperty("max-height", "none", "important");
    el.style.setProperty("min-height", "22rem", "important");
    el.style.setProperty("overflow", "visible", "important");
    el.style.setProperty("overflow-x", "hidden", "important");
    el.style.setProperty("overflow-y", "visible", "important");
}

patch(FormController.prototype, {
    _isAveaBankReconForm() {
        return (this.props.resModel || this.model?.config?.resModel) === RECON_MODEL;
    },

    _ensureAveaReconScrollHooks() {
        if (this._aveaReconScrollHooksBound) {
            return;
        }
        this._aveaReconScrollHooksBound = true;
        this._aveaReconScrollRestore = [];
        onMounted(() => {
            this._setupAveaReconScrollShell();
            window.setTimeout(() => this._setupAveaReconScrollShell(), 0);
        });
        onWillUnmount(() => this._teardownAveaReconScrollShell());
    },

    setup() {
        super.setup();
        if (this._isAveaBankReconForm()) {
            this._ensureAveaReconScrollHooks();
        }
    },

    _setupAveaReconScrollShell() {
        if (!this._isAveaBankReconForm()) {
            return;
        }
        const root = this.el;
        if (!root) {
            window.requestAnimationFrame(() => this._setupAveaReconScrollShell());
            return;
        }
        const actionManager = root.closest(".o_action_manager");
        if (!actionManager) {
            return;
        }

        const nodes = new Set();
        let node = root;
        while (node && node !== actionManager.parentElement) {
            nodes.add(node);
            node = node.parentElement;
        }
        nodes.add(actionManager);
        root.querySelectorAll(
            [
                ".o_form_renderer",
                ".o_form_sheet_bg",
                ".o_form_sheet",
                ".o_avea_workspace_sheet",
                ".o_content",
                ".o_notebook",
                ".o_notebook_content",
                ".tab-content",
                ".tab-pane.active",
                ".tab-pane.show",
                ".o_field_x2many",
                ".o_field_one2many",
                ".o_field_x2many_list",
                ".o_list_view",
            ].join(", ")
        ).forEach((el) => nodes.add(el));

        this._teardownAveaReconScrollShell();
        for (const el of nodes) {
            this._aveaReconScrollRestore.push([el, el.getAttribute("style")]);
            if (el === actionManager) {
                el.classList.add(ACTION_MANAGER_SCROLL_CLASS);
                el.style.setProperty("overflow-x", "hidden", "important");
                el.style.setProperty("overflow-y", "auto", "important");
                el.style.setProperty("height", PANE_HEIGHT, "important");
                el.style.setProperty("max-height", PANE_HEIGHT, "important");
                el.style.setProperty("-webkit-overflow-scrolling", "touch");
            } else {
                _unlockInner(el);
            }
        }

        root.querySelectorAll(
            ".o_list_renderer, .o_avea_bank_reconcile_lines .o_list_renderer"
        ).forEach((el) => {
            this._aveaReconScrollRestore.push([el, el.getAttribute("style")]);
            _unlockList(el);
        });
    },

    _teardownAveaReconScrollShell() {
        for (const [el, style] of this._aveaReconScrollRestore || []) {
            el.classList.remove(ACTION_MANAGER_SCROLL_CLASS);
            if (style === null) {
                el.removeAttribute("style");
            } else {
                el.setAttribute("style", style);
            }
        }
        this._aveaReconScrollRestore = [];
    },
});

registry.category("views").add("avea_bank_reconciliation_form", {
    ...formView,
    Controller: AveaBankReconciliationFormController,
});
