/** @odoo-module **/

import { session } from "@web/session";

if (session.avea_product_shell) {
    document.body.classList.add("o_avea_product_shell");
}
