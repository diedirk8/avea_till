/** @odoo-module **/

import { Component } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import {
    aveaPrintLayoutClass,
    aveaPrintLogoClass,
    aveaPrintLogoStyle,
    aveaPrintShow,
    isAveaPrintCustomizeEnabled,
} from "./print_receipt_settings";

export class AveaQuoteReceipt extends Component {
    static template = "avea_till.AveaQuoteReceipt";
    static props = {
        receipt: Object,
        config: Object,
        company: Object,
    };

    get receipt() {
        return this.props.receipt;
    }

    get config() {
        return this.props.config;
    }

    get company() {
        return this.props.company;
    }

    get customize() {
        return isAveaPrintCustomizeEnabled(this.company);
    }

    show(fieldName) {
        return aveaPrintShow(this.company, fieldName);
    }

    get layoutClass() {
        const layout = aveaPrintLayoutClass(this.company);
        return layout ? `${layout} avea-pos-receipt--customized` : "";
    }

    get logoClass() {
        return aveaPrintLogoClass(this.company);
    }

    get logoStyle() {
        return aveaPrintLogoStyle(this.company);
    }

    get logoUrl() {
        return this.config?.receiptLogoUrl || "";
    }

    get showLogo() {
        return Boolean(this.logoUrl) && this.show("avea_print_receipt_show_logo");
    }

    get footerMessage() {
        return (this.company?.avea_print_receipt_footer_message || "").trim();
    }

    get vatText() {
        if (!this.company?.vat) {
            return "";
        }
        const label = this.company.country_id?.vat_label;
        if (label) {
            return _t("%(vatLabel)s: %(vatId)s", {
                vatLabel: label,
                vatId: this.company.vat,
            });
        }
        return _t("Tax ID: %(vatId)s", { vatId: this.company.vat });
    }
}
