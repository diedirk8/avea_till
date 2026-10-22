/** @odoo-module **/

import { session } from "@web/session";

export function usesAveaNav() {
    return Boolean(session.avea_product_shell && session.avea_nav);
}
