/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { WebClient } from "@web/webclient/webclient";
import { AveaNav } from "./avea_nav";
import { usesAveaNav } from "./avea_nav_shell";

patch(WebClient, {
    components: {
        ...WebClient.components,
        AveaNav,
    },
});

patch(WebClient.prototype, {
    setup() {
        super.setup(...arguments);
        if (usesAveaNav()) {
            document.body.classList.add("o_avea_product_shell");
            const themeColor = document.querySelector('meta[name="theme-color"]');
            if (themeColor) {
                themeColor.content = "#c45c26";
            }
        }
    },

    usesAveaNav() {
        return usesAveaNav();
    },
});
