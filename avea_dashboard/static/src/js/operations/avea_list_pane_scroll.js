/** @odoo-module **/

import { onMounted, onPatched, onWillUnmount, useComponent } from "@odoo/owl";

const ACTION_MANAGER_CLASS = "o_avea_list_pane_action_manager";
const PANE_HEIGHT = "calc(100vh - var(--avea-topbar-height, 3.25rem))";

const PANE_LOCK = {
    display: "flex",
    "flex-direction": "column",
    flex: "1 1 auto",
    height: "100%",
    "max-height": "100%",
    "min-height": "0",
    overflow: "hidden",
    "overflow-x": "hidden",
    "overflow-y": "hidden",
};

const HERO_LOCK = {
    flex: "0 0 auto",
    "flex-shrink": "0",
    height: "auto",
    "max-height": "none",
    overflow: "visible",
};

const LIST_LOCK = {
    display: "block",
    flex: "1 1 auto",
    height: "auto",
    "max-height": "none",
    "min-height": "0",
    overflow: "auto",
    "overflow-x": "auto",
    "overflow-y": "auto",
    "-webkit-overflow-scrolling": "touch",
};

function _pin(restore, el, styles) {
    restore.push([el, el.getAttribute("style")]);
    for (const [prop, value] of Object.entries(styles)) {
        el.style.setProperty(prop, value, "important");
    }
}

/**
 * Keep the hero/search visible and put a working scrollbar on the table.
 * CSS :has() plus overflow-x:clip is not enough on its own (promotion form
 * and stock catalogue already pin the action manager for the same reason).
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
            display: "flex",
            "flex-direction": "column",
            height: PANE_HEIGHT,
            "max-height": PANE_HEIGHT,
            overflow: "hidden",
            "overflow-x": "hidden",
            "overflow-y": "hidden",
        });
        actionManager.classList.add(ACTION_MANAGER_CLASS);

        let node = root.parentElement;
        while (node && node !== actionManager) {
            _pin(restore, node, PANE_LOCK);
            node = node.parentElement;
        }
        _pin(restore, root, PANE_LOCK);

        root.querySelectorAll(".o_view_controller, .o_content").forEach((el) => {
            _pin(restore, el, PANE_LOCK);
        });
        root.querySelectorAll(
            ".o_avea_account_list_shell, .o_avea_account_list_footer, .o_avea_account_pager"
        ).forEach((el) => {
            _pin(restore, el, HERO_LOCK);
        });
        root.querySelectorAll(".o_list_renderer, .o_list_renderer .table-responsive").forEach((el) => {
            _pin(restore, el, LIST_LOCK);
        });
    }

    onMounted(() => {
        setup();
        window.setTimeout(setup, 0);
    });
    onPatched(() => {
        const renderer = component.el?.querySelector(".o_list_renderer");
        if (renderer && renderer.style.getPropertyValue("overflow-y") !== "auto") {
            setup();
        }
    });
    onWillUnmount(() => {
        live = false;
        teardown();
    });
}
