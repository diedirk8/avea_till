/** @odoo-module **/

import { session } from "@web/session";

export function usesAveaNav() {
    if (session.is_admin || session.is_system) {
        return false;
    }
    return Boolean(session.avea_product_shell && session.avea_nav);
}
