/** @odoo-module **/

/**
 * Customer and Stock lists were rendering with a large empty gutter between the
 * sidebar and the white card (page background showing through). CSS resets did
 * not remove every inset Odoo applies, so measure the card against the action
 * pane and pull the header and table left until they share the pane's left edge.
 * The correction is cumulative so a resize observer does not oscillate.
 */

function alignToManager(el, manager) {
    if (!el || !manager) {
        return;
    }
    const gap = Math.round(el.getBoundingClientRect().left - manager.getBoundingClientRect().left);
    if (Math.abs(gap) <= 2) {
        return;
    }
    const prev = Number(el.dataset.aveaFlushPx || 0);
    const next = prev + gap;
    el.dataset.aveaFlushPx = String(next);
    el.style.setProperty("margin-left", `${-next}px`, "important");
    el.style.setProperty("width", `calc(100% + ${next}px)`, "important");
    el.style.setProperty("max-width", "none", "important");
}

export function flushCataloguePane(root) {
    if (!root) {
        return;
    }
    const manager = root.closest(".o_action_manager");
    if (!manager) {
        return;
    }
    root.style.setProperty("overflow-x", "visible", "important");
    root.style.setProperty("padding-left", "0", "important");
    root.style.setProperty("padding-right", "0", "important");

    let node = root;
    while (node && node !== manager) {
        const pad = parseFloat(getComputedStyle(node).paddingLeft) || 0;
        if (pad > 1) {
            node.style.setProperty("padding-left", "0", "important");
        }
        node = node.parentElement;
    }

    const sheet = root.querySelector(
        ".o_avea_stock_catalogue_sheet, .o_avea_customer_list_sheet"
    );
    const content = root.querySelector(":scope > .o_content, :scope > main.o_content");
    alignToManager(sheet, manager);
    alignToManager(content, manager);
}

export function bindCatalogueFlush(root) {
    if (!root) {
        return () => {};
    }
    const run = () => flushCataloguePane(root);
    run();
    const raf = requestAnimationFrame(run);
    const observer = new ResizeObserver(run);
    observer.observe(root);
    const manager = root.closest(".o_action_manager");
    if (manager) {
        observer.observe(manager);
    }
    window.addEventListener("resize", run);
    return () => {
        cancelAnimationFrame(raf);
        observer.disconnect();
        window.removeEventListener("resize", run);
    };
}
