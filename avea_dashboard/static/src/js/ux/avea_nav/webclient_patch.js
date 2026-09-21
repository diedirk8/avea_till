/** @odoo-module **/

import { Component, xml } from "@odoo/owl";
import { patch } from "@web/core/utils/patch";
import { WebClient } from "@web/webclient/webclient";
import { NavBar } from "@web/webclient/navbar/navbar";
import { AveaNav } from "./avea_nav";
import { usesAveaNav } from "./avea_nav_shell";

class AveaShellNav extends Component {
    static template = xml`
        <AveaNav t-if="showAveaNav"/>
        <NavBar t-else=""/>
    `;
    static components = { AveaNav, NavBar };

    setup() {
        this.showAveaNav = usesAveaNav();
        if (this.showAveaNav) {
            document.body.classList.add("o_avea_product_shell");
            const themeColor = document.querySelector('meta[name="theme-color"]');
            if (themeColor) {
                themeColor.content = "#c45c26";
            }
        }
    }
}

patch(WebClient, {
    components: {
        ...WebClient.components,
        NavBar: AveaShellNav,
    },
});
