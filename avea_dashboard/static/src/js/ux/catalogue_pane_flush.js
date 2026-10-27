/** @odoo-module **/

/**
 * Line the catalogue card up with the sidebar's right edge.
 * The empty strip is whatever is between that edge and the card, which can sit
 * on the action pane itself or on the card. Measure once from a clean layout
 * (no ResizeObserver) so corrections do not stack.
 */

function clearPull(el) {
    if (!el) {
        return;
    }
    el.style.removeProperty("margin-left");
    el.style.removeProperty("width");
    el.style.removeProperty("max-width");
}

export function flushCataloguePane(root) {
    if (!root) {
        return;
    }
    const sidebar = document.querySelector(".o_avea_sidebar");
    const manager = root.closest(".o_action_manager");
    const sheet = root.querySelector(
        ".o_avea_stock_catalogue_sheet, .o_avea_customer_list_sheet"
    );
    const content = root.querySelector(":scope > .o_content, :scope > main.o_content");
    if (!sidebar || !manager || !sheet) {
        return;
    }

    clearPull(sheet);
    clearPull(content);
    manager.style.removeProperty("margin-left");

    const edge = () => sidebar.getBoundingClientRect().right;
    const managerGap = Math.round(manager.getBoundingClientRect().left - edge());
    if (managerGap > 2) {
        const base = parseFloat(getComputedStyle(manager).marginLeft) || 0;
        manager.style.setProperty("margin-left", `${base - managerGap}px`, "important");
    }

    root.style.setProperty("overflow", "visible", "important");
    root.style.setProperty("padding-left", "0", "important");
    root.style.setProperty("padding-right", "0", "important");

    for (const el of [sheet, content]) {
        if (!el) {
            continue;
        }
        const gap = Math.round(el.getBoundingClientRect().left - edge());
        if (gap > 2) {
            el.style.setProperty("margin-left", `${-gap}px`, "important");
            el.style.setProperty("width", `calc(100% + ${gap}px)`, "important");
            el.style.setProperty("max-width", "none", "important");
        }
    }
}

export function bindCatalogueFlush(root) {
    if (!root) {
        return () => {};
    }
    const run = () => flushCataloguePane(root);
    run();
    const raf = requestAnimationFrame(run);
    window.addEventListener("resize", run);
    return () => {
        cancelAnimationFrame(raf);
        window.removeEventListener("resize", run);
    };
}
