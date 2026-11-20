/** @odoo-module **/

import { onMounted, onPatched, onWillUnmount, useComponent } from "@odoo/owl";

const ACTION_MANAGER_CLASS = "o_avea_list_pane_action_manager";
const PANE_HEIGHT = "calc(100vh - var(--avea-topbar-height, 3.25rem))";

const UNLOCK = {
    display: "block",
    flex: "none",
    height: "auto",
    "max-height": "none",
    "min-height": "0",
    overflow: "visible",
    "overflow-x": "visible",
    "overflow-y": "visible",
};

function _pin(restore, el, styles) {
    restore.push([el, el.getAttribute("style")]);
    for (const [prop, value] of Object.entries(styles)) {
        el.style.setProperty(prop, value, "important");
    }
}

/**
 * Scroll the whole activity page. Inner table overflow:auto with height:auto
 * never grows a thumb, and parent overflow:hidden then clips the rows.
 */
export function useAveaListPaneScroll() {
    const component = useComponent();
    const restore = [];
    let live = true;

    function teardown() {
        for (const [el, style] of restore) {
            el.classList.remove(ACTION_MANAGER_CLASS);
            if (style === null) {
                el.removeAttribute("style");
            } else {
                el.setAttribute("style", style);
            }
        }
        restore.length = 0;
    }

    function setup() {
        if (!live) {
            return;
        }
        const root = component.el;
        if (!root) {
            window.requestAnimationFrame(setup);
            return;
        }
        const actionManager = root.closest(".o_action_manager");
        if (!actionManager) {
            return;
        }

        teardown();

        _pin(restore, actionManager, {
            display: "block",
            height: PANE_HEIGHT,
            "max-height": PANE_HEIGHT,
            "overflow-x": "hidden",
            "overflow-y": "scroll",
            "-webkit-overflow-scrolling": "touch",
        });
        actionManager.classList.add(ACTION_MANAGER_CLASS);

        let node = root;
        while (node && node !== actionManager) {
            _pin(restore, node, UNLOCK);
            node = node.parentElement;
        }

        root.querySelectorAll(
            [
                ".o_view_controller",
                ".o_content",
                ".o_form_renderer",
                ".o_form_sheet_bg",
                ".o_form_sheet",
                ".o_avea_workspace_sheet",
                ".o_avea_account_list_shell",
                ".o_avea_account_list_footer",
                ".o_list_view",
                ".o_list_renderer",
                ".table-responsive",
            ].join(", ")
        ).forEach((el) => _pin(restore, el, UNLOCK));
    }

    onMounted(() => {
        setup();
        window.setTimeout(setup, 0);
    });
    onPatched(() => {
        const actionManager = component.el?.closest(".o_action_manager");
        if (actionManager && actionManager.style.getPropertyValue("overflow-y") !== "scroll") {
            setup();
        }
    });
    onWillUnmount(() => {
        live = false;
        teardown();
    });
}
