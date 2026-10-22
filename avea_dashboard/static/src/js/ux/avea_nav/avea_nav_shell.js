/** @odoo-module **/

import { session } from "@web/session";

export function aveaNavSessionEnabled() {
    return Boolean(session.avea_product_shell && session.avea_nav);
}

/**
 * Avea sidebar for every screen when the user has the retail shell session.
 * (Odoo apps like Discuss stay reachable via direct links; navigation is Avea-first.)
 */
export function usesAveaNav(_menuService) {
    return aveaNavSessionEnabled();
}
