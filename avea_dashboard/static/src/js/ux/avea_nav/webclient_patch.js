/** @odoo-module **/

import { onMounted, onWillUnmount } from "@odoo/owl";
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
        this._syncAveaShellClass = () => {
            const enabled = this.usesAveaNav();
            document.body.classList.toggle("o_avea_product_shell", enabled);
            const themeColor = document.querySelector('meta[name="theme-color"]');
            if (themeColor) {
                themeColor.content = enabled ? "#c45c26" : "";
            }
        };
        onMounted(() => {
            this._syncAveaShellClass();
            this.env.bus.addEventListener("MENUS:APP-CHANGED", this._syncAveaShellClass);
        });
        onWillUnmount(() => {
            this.env.bus.removeEventListener("MENUS:APP-CHANGED", this._syncAveaShellClass);
            document.body.classList.remove("o_avea_product_shell");
        });
    },

    usesAveaNav() {
        return usesAveaNav(this.menuService);
    },
});
