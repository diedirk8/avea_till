/** @odoo-module **/

import { onMounted, onWillUnmount } from "@odoo/owl";
import { patch } from "@web/core/utils/patch";
import { WebClient } from "@web/webclient/webclient";
import { AveaNav } from "./avea_nav";
import { usesAveaNav } from "./avea_nav_shell";

const PAGE_SCROLL_CLASS = "o_avea_page_scroll";
const CATALOGUE_SELECTOR = [
    ".o_avea_catalogue_flush",
    ".o_avea_workspace--customer-list",
    ".o_avea_workspace--stock-catalogue-list",
    ".o_list_view.o_avea_customer_list",
    ".o_list_view.o_avea_stock_catalogue_list",
].join(", ");

function _actionManager() {
    return document.querySelector(".o_action_manager");
}

function _syncAveaPageScroll() {
    const actionManager = _actionManager();
    if (!actionManager) {
        return;
    }
    const shellOn = document.body.classList.contains("o_avea_product_shell");
    const catalogue = Boolean(actionManager.querySelector(CATALOGUE_SELECTOR));
    actionManager.classList.toggle(PAGE_SCROLL_CLASS, shellOn && !catalogue);
}

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
            _syncAveaPageScroll();
        };
        onMounted(() => {
            this._syncAveaShellClass();
            this.env.bus.addEventListener("MENUS:APP-CHANGED", this._syncAveaShellClass);
            this._aveaPageScrollObserver = new MutationObserver(() => {
                window.clearTimeout(this._aveaPageScrollTimer);
                this._aveaPageScrollTimer = window.setTimeout(_syncAveaPageScroll, 30);
            });
            const actionManager = _actionManager();
            if (actionManager) {
                this._aveaPageScrollObserver.observe(actionManager, {
                    childList: true,
                    subtree: true,
                });
            }
            _syncAveaPageScroll();
        });
        onWillUnmount(() => {
            this.env.bus.removeEventListener("MENUS:APP-CHANGED", this._syncAveaShellClass);
            this._aveaPageScrollObserver?.disconnect();
            window.clearTimeout(this._aveaPageScrollTimer);
            document.body.classList.remove("o_avea_product_shell");
            _actionManager()?.classList.remove(PAGE_SCROLL_CLASS);
        });
    },

    usesAveaNav() {
        return usesAveaNav(this.menuService);
    },
});
