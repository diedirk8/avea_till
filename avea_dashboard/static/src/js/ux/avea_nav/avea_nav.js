/** @odoo-module **/

import { Component, useState, useRef, onMounted, onWillUnmount } from "@odoo/owl";
import { session } from "@web/session";
import { browser } from "@web/core/browser/browser";
import { user } from "@web/core/user";
import { useService } from "@web/core/utils/hooks";

const SIDEBAR_COLLAPSED_KEY = "avea_sidebar_collapsed";

export class AveaNav extends Component {
    static template = "avea_till.AveaNav";
    static components = {};
    static props = {};

    setup() {
        this.rootRef = useRef("root");
        this.menuService = useService("menu");
        this.actionService = useService("action");
        this.nav = session.avea_nav || {
            sections: [],
            sell: null,
            home: null,
            settings: null,
            role: "cashier",
        };
        this.state = useState({
            activeSectionId: null,
            activeGroupId: null,
            activeMenuXmlid: null,
            expandedSectionId: null,
            expandedGroupIds: {},
            settingsOpen: false,
            mobileOpen: false,
            userMenuOpen: false,
            collapsed: browser.localStorage.getItem(SIDEBAR_COLLAPSED_KEY) === "1",
        });
        this._onDocumentClick = (ev) => {
            if (!this.state.userMenuOpen) {
                return;
            }
            const menu = this.rootRef.el?.querySelector(".o_avea_user_menu");
            if (menu && !menu.contains(ev.target)) {
                this.state.userMenuOpen = false;
            }
        };
        this._syncActiveFromMenu = () => {
            const match = this._findActiveItem();
            if (match) {
                this.state.activeSectionId = match.sectionId;
                this.state.activeGroupId = match.groupId;
                this.state.activeMenuXmlid = match.menuXmlid;
                if (match.sectionId) {
                    this.state.expandedSectionId = match.sectionId;
                }
                if (match.groupId) {
                    this.state.expandedGroupIds = {
                        ...this.state.expandedGroupIds,
                        [match.groupId]: true,
                    };
                }
                if (match.settings) {
                    this.state.settingsOpen = true;
                }
            }
            this._syncShellClass();
        };

        onMounted(() => {
            this._syncActiveFromMenu();
            if (!this.state.expandedSectionId && this.sections.length === 1) {
                this.state.expandedSectionId = this.sections[0].id;
            }
            this._syncShellClass();
            document.addEventListener("click", this._onDocumentClick);
            this.env.bus.addEventListener("MENUS:APP-CHANGED", this._syncActiveFromMenu);
            this.env.bus.addEventListener("ACTION_MANAGER:UI-UPDATED", this._syncActiveFromMenu);
        });
        onWillUnmount(() => {
            document.removeEventListener("click", this._onDocumentClick);
            document.body.classList.remove(
                "o_avea_sidebar_collapsed",
                "o_avea_mobile_nav_open"
            );
            this.env.bus.removeEventListener("MENUS:APP-CHANGED", this._syncActiveFromMenu);
            this.env.bus.removeEventListener(
                "ACTION_MANAGER:UI-UPDATED",
                this._syncActiveFromMenu
            );
        });
    }

    get sections() {
        return this.nav.sections || [];
    }

    get sellAction() {
        return this.nav.sell;
    }

    get homeItem() {
        return this.nav.home;
    }

    get settingsNav() {
        return this.nav.settings;
    }

    get companyName() {
        return user.activeCompany?.name || "";
    }

    get userName() {
        return user.name;
    }

    get userInitials() {
        const parts = user.name.trim().split(/\s+/).filter(Boolean);
        if (parts.length >= 2) {
            return `${parts[0][0]}${parts[parts.length - 1][0]}`.toUpperCase();
        }
        return (parts[0]?.[0] || "U").toUpperCase();
    }

    get companies() {
        return user.allowedCompanies || [];
    }

    get hasMultipleCompanies() {
        return this.companies.length > 1;
    }

    isActiveCompany(company) {
        return company.id === user.activeCompany?.id;
    }

    async onSwitchCompany(companyId) {
        if (companyId === user.activeCompany?.id) {
            this.closeUserMenu();
            return;
        }
        await user.activateCompanies([companyId]);
        this.closeUserMenu();
    }

    onUserMenuPanelClick(ev) {
        ev.stopPropagation();
    }

    toggleUserMenu(ev) {
        ev.stopPropagation();
        this.state.userMenuOpen = !this.state.userMenuOpen;
    }

    closeUserMenu() {
        this.state.userMenuOpen = false;
    }

    onLogout() {
        this.closeUserMenu();
        window.location.href = "/web/session/logout?redirect=/web/login";
    }

    get isCashier() {
        return this.nav.role === "cashier";
    }

    _syncShellClass() {
        document.body.classList.toggle("o_avea_sidebar_collapsed", this.state.collapsed);
        document.body.classList.toggle("o_avea_mobile_nav_open", this.state.mobileOpen);
    }

    _menuByXmlid(xmlid) {
        return this.menuService.getAll().find((menu) => menu.xmlid === xmlid);
    }

    _iterNavLinks() {
        const links = [];
        const walkItems = (items, sectionId = null, groupId = null, settings = false) => {
            for (const item of items || []) {
                if (item.menu_xmlid) {
                    links.push({
                        sectionId,
                        groupId,
                        menuXmlid: item.menu_xmlid,
                        settings,
                    });
                } else if (item.items) {
                    walkItems(item.items, sectionId, item.id || item.label, settings);
                }
            }
        };
        if (this.homeItem?.menu_xmlid) {
            links.push({
                sectionId: null,
                groupId: null,
                menuXmlid: this.homeItem.menu_xmlid,
                settings: false,
                home: true,
            });
        }
        for (const section of this.sections) {
            walkItems(section.items, section.id, null, false);
        }
        if (this.settingsNav) {
            walkItems(this.settingsNav.items, null, null, true);
        }
        return links;
    }

    _findActiveItem() {
        const controller = this.actionService.currentController;
        if (!controller?.action?.id) {
            return null;
        }
        const actionId = controller.action.id;
        const allMenus = this.menuService.getAll();
        for (const link of this._iterNavLinks()) {
            const menu = allMenus.find((m) => m.xmlid === link.menuXmlid);
            if (menu?.actionID === actionId) {
                return link;
            }
        }
        if (this.sellAction) {
            const sellMenu = allMenus.find((m) => m.xmlid === this.sellAction.menu_xmlid);
            if (sellMenu?.actionID === actionId) {
                return { sectionId: null, groupId: null, menuXmlid: sellMenu.xmlid };
            }
        }
        return null;
    }

    async onBrandClick() {
        if (this.homeItem) {
            await this.openMenuXmlid(this.homeItem.menu_xmlid);
            return;
        }
        if (session.home_action_id) {
            await this.actionService.doAction(session.home_action_id);
        }
    }

    async openMenuXmlid(xmlid, { sectionId = null, groupId = null, settings = false } = {}) {
        const menu = this._menuByXmlid(xmlid);
        if (!menu) {
            return;
        }
        this.state.activeSectionId = sectionId;
        this.state.activeGroupId = groupId;
        this.state.activeMenuXmlid = xmlid;
        this.state.settingsOpen = settings;
        this.state.mobileOpen = false;
        await this.menuService.selectMenu(menu);
    }

    async onHomeClick() {
        if (this.homeItem) {
            await this.openMenuXmlid(this.homeItem.menu_xmlid);
        }
    }

    async onSellClick() {
        if (this.sellAction) {
            await this.openMenuXmlid(this.sellAction.menu_xmlid);
        }
    }

    toggleSection(section) {
        if (this.state.collapsed) {
            this.toggleCollapsed();
        }
        this.state.expandedSectionId =
            this.state.expandedSectionId === section.id ? null : section.id;
    }

    toggleGroup(groupId) {
        this.state.expandedGroupIds = {
            ...this.state.expandedGroupIds,
            [groupId]: !this.state.expandedGroupIds[groupId],
        };
    }

    toggleSettings() {
        if (this.state.collapsed) {
            this.toggleCollapsed();
        }
        this.state.settingsOpen = !this.state.settingsOpen;
    }

    isSectionExpanded(section) {
        return this.state.expandedSectionId === section.id;
    }

    isGroupExpanded(groupId) {
        return Boolean(this.state.expandedGroupIds[groupId]);
    }

    isHomeActive() {
        return this.homeItem && this.state.activeMenuXmlid === this.homeItem.menu_xmlid;
    }

    isItemActive(item) {
        return item.menu_xmlid && this.state.activeMenuXmlid === item.menu_xmlid;
    }

    isSectionActive(section) {
        return this.state.activeSectionId === section.id;
    }

    isSettingsActive() {
        return this.state.settingsOpen || this._iterNavLinks().some(
            (link) => link.settings && link.menuXmlid === this.state.activeMenuXmlid
        );
    }

    isLinkItem(item) {
        return Boolean(item.menu_xmlid);
    }

    isGroupItem(item) {
        return Boolean(item.items);
    }

    groupKey(item) {
        return item.id || item.label;
    }

    async onSectionItemClick(section, item) {
        if (this.isLinkItem(item)) {
            await this.openMenuXmlid(item.menu_xmlid, { sectionId: section.id });
            return;
        }
        this.toggleGroup(this.groupKey(item));
    }

    async onNestedItemClick(section, group, item) {
        await this.openMenuXmlid(item.menu_xmlid, {
            sectionId: section.id,
            groupId: this.groupKey(group),
        });
    }

    async onSettingsItemClick(item) {
        await this.openMenuXmlid(item.menu_xmlid, { settings: true });
    }

    toggleCollapsed() {
        this.state.collapsed = !this.state.collapsed;
        browser.localStorage.setItem(SIDEBAR_COLLAPSED_KEY, this.state.collapsed ? "1" : "0");
        this._syncShellClass();
    }

    toggleMobile() {
        this.state.mobileOpen = !this.state.mobileOpen;
        this._syncShellClass();
    }

    closeMobile() {
        this.state.mobileOpen = false;
        this._syncShellClass();
    }

}
