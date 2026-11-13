/** @odoo-module **/

import { FormController } from "@web/views/form/form_controller";
import { formView } from "@web/views/form/form_view";
import { registry } from "@web/core/registry";
import { patch } from "@web/core/utils/patch";
import { onMounted, onWillUnmount } from "@odoo/owl";

const PROMOTION_MODEL = "avea.promotion";
const PROMOTION_LIST_ACTION = "avea_till.action_avea_promotion";
const ACTION_MANAGER_SCROLL_CLASS = "o_avea_promotion_form_action_manager";
const PANE_HEIGHT = "calc(100vh - var(--avea-topbar-height, 3.25rem))";

export class AveaPromotionFormController extends FormController {
    setup() {
        super.setup();
        this._scrollRestore = [];
        onMounted(() => this._setupScrollShell());
        onWillUnmount(() => this._teardownScrollShell());
    }

    get className() {
        const base = super.className || "";
        return `${base} o_avea_workspace o_avea_workspace--promotion`.trim();
    }

    _setupScrollShell() {
        const root = this.el;
        if (!root) {
            window.requestAnimationFrame(() => this._setupScrollShell());
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
            ".o_form_renderer, .o_form_sheet_bg, .o_form_sheet, .o_avea_workspace_sheet, .o_content"
        ).forEach((el) => nodes.add(el));

        this._teardownScrollShell();
        for (const el of nodes) {
            this._scrollRestore.push([el, el.getAttribute("style")]);
            if (el === actionManager) {
                el.classList.add(ACTION_MANAGER_SCROLL_CLASS);
                el.style.setProperty("overflow-x", "hidden", "important");
                el.style.setProperty("overflow-y", "auto", "important");
                el.style.setProperty("height", PANE_HEIGHT, "important");
                el.style.setProperty("max-height", PANE_HEIGHT, "important");
                el.style.setProperty("-webkit-overflow-scrolling", "touch");
            } else {
                el.style.setProperty("display", "block", "important");
                el.style.setProperty("flex", "none", "important");
                el.style.setProperty("height", "auto", "important");
                el.style.setProperty("max-height", "none", "important");
                el.style.setProperty("min-height", "0", "important");
                el.style.setProperty("overflow", "visible", "important");
                el.style.setProperty("overflow-x", "visible", "important");
                el.style.setProperty("overflow-y", "visible", "important");
            }
        }
    }

    _teardownScrollShell() {
        for (const [el, style] of this._scrollRestore) {
            el.classList.remove(ACTION_MANAGER_SCROLL_CLASS);
            if (style === null) {
                el.removeAttribute("style");
            } else {
                el.setAttribute("style", style);
            }
        }
        this._scrollRestore = [];
    }
}

registry.category("views").add("avea_promotion_form", {
    ...formView,
    Controller: AveaPromotionFormController,
});

/**
 * Promotion forms hide the standard control panel, so Cancel must discard
 * without triggering the "missing required fields" save path. Save and Cancel
 * both return to the promotions list.
 */
patch(FormController.prototype, {
    _isAveaPromotionForm() {
        return (this.props.resModel || this.model?.config?.resModel) === PROMOTION_MODEL;
    },

    async _returnToPromotionList() {
        await this.actionService.doAction(PROMOTION_LIST_ACTION);
    },

    async beforeExecuteActionButton(clickParams) {
        if (clickParams.special === "cancel" && this._isAveaPromotionForm()) {
            await this.discard();
            await this._returnToPromotionList();
            return false;
        }
        return await super.beforeExecuteActionButton(clickParams);
    },

    async afterExecuteActionButton(clickParams) {
        await super.afterExecuteActionButton?.(clickParams);
        if (clickParams.special === "save" && this._isAveaPromotionForm()) {
            await this._returnToPromotionList();
        }
    },
});
