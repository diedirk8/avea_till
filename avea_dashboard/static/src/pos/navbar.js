/** @odoo-module **/

import { Navbar } from "@point_of_sale/app/components/navbar/navbar";
import { _t } from "@web/core/l10n/translation";
import { onWillUnmount } from "@odoo/owl";
import { patch } from "@web/core/utils/patch";

patch(Navbar.prototype, {
    setup() {
        super.setup(...arguments);
        if (typeof document !== "undefined") {
            document.title = "Avea POS";
        }
        this.state.aveaNow = Date.now();
        this._aveaClockTimer = setInterval(() => {
            this.state.aveaNow = Date.now();
        }, 1000);
        onWillUnmount(() => clearInterval(this._aveaClockTimer));
    },

    get showIssueStoreCreditMenu() {
        return typeof this.pos.canIssueStoreCredit === "function"
            ? this.pos.canIssueStoreCredit()
            : false;
    },
    get showCashUpMenu() {
        return typeof this.pos.canCashUpOwnTill === "function"
            ? this.pos.canCashUpOwnTill()
            : false;
    },
    get showBackend() {
        const cashier = this.pos.getCashierUserId?.();
        return (
            !this.pos.config.module_pos_hr ||
            (cashier && cashier.id === this.pos.user?.id)
        );
    },
    get showCloseRegister() {
        return (
            !this.pos.config.module_pos_hr ||
            this.pos.employeeIsAdmin ||
            this.pos.getCashierUserId?.()?.id === this.pos.session.user_id?.id
        );
    },
    get showPosSettingsMenu() {
        return this.pos.cashier?._role !== "minimal";
    },
    get isMinimalCashier() {
        return this.pos.cashier?._role === "minimal";
    },
    get aveaCompanyName() {
        return this.pos.company?.name || this.pos.config?.company_id?.name || "";
    },
    get aveaTillName() {
        return this.pos.config?.name || "";
    },
    get aveaCashierLabel() {
        const cashier = this.pos.cashier || this.pos.getCashier?.() || this.pos.user;
        return cashier?.name ? _t("Cashier: %s", cashier.name) : _t("Cashier");
    },
    get aveaCashierName() {
        const cashier = this.pos.cashier || this.pos.getCashier?.() || this.pos.user;
        return cashier?.name || _t("Cashier");
    },
    get aveaNetworkBusy() {
        const network = this.pos.data?.network;
        return Boolean(network?.offline || network?.loading);
    },
    get aveaNetworkOffline() {
        return Boolean(this.pos.data?.network?.offline);
    },
    get aveaUnsyncCount() {
        return this.pos.data?.network?.unsyncData?.length || 0;
    },
    get aveaLnaButtonClass() {
        const type = this.pos.lnaState?.type || "secondary";
        return `btn btn-${type} btn-sm rounded`;
    },
    get aveaDateTimeLabel() {
        const now = new Date(this.state.aveaNow || Date.now());
        const date = now.toLocaleDateString(undefined, {
            weekday: "short",
            day: "numeric",
            month: "short",
            year: "numeric",
        });
        const time = now.toLocaleTimeString(undefined, {
            hour: "2-digit",
            minute: "2-digit",
            hour12: false,
        });
        return `${date}, ${time}`;
    },
    issueStoreCredit() {
        this.pos.issueStoreCredit();
    },
    openCashUp() {
        this.pos.openCashUp();
    },
    openPosSettings() {
        const configId = this.pos.config.id;
        window.open(`/web#id=${configId}&model=pos.config&view_type=form`, "_blank");
    },
});
