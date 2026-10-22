/** @odoo-module **/

import { session } from "@web/session";

export function aveaNavSessionEnabled() {
    return Boolean(session.avea_product_shell && session.avea_nav);
}

/**
 * Avea sidebar only on the Avea Dashboard app — not Discuss, Accounting, etc.
 */
export function usesAveaNav(menuService) {
    if (!aveaNavSessionEnabled()) {
        return false;
    }
    const app = menuService?.getCurrentApp?.();
    if (!app) {
        return true;
    }
    const xmlid = app.xmlid || "";
    return xmlid.startsWith("avea_till.");
}
