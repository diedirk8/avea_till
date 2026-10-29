/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { Component, useState } from "@odoo/owl";
import { usePos } from "@point_of_sale/app/hooks/pos_hook";
import { Dialog } from "@web/core/dialog/dialog";
import { useAsyncLockedMethod } from "@point_of_sale/app/hooks/hooks";
import { RPCError } from "@web/core/network/rpc";

function _aveaLineMoney(line, included, excluded) {
    const prices = line.prices || {};
    const totalIncluded = Number(
        included ??
            prices.total_included ??
            (typeof line.getPriceWithTax === "function" ? line.getPriceWithTax() : null) ??
            (Number(line.price_unit) || 0) * (Number(line.qty) || 0)
    );
    const totalExcluded = Number(
        excluded ??
            prices.total_excluded ??
            (typeof line.getPriceWithoutTax === "function" ? line.getPriceWithoutTax() : null) ??
            totalIncluded
    );
    return {
        totalIncluded: Number.isFinite(totalIncluded) ? totalIncluded : 0,
        totalExcluded: Number.isFinite(totalExcluded) ? totalExcluded : 0,
    };
}

export function aveaQuoteLines(order) {
    const lines = [];
    for (const line of order?.lines || []) {
        const quantity = Number(line.qty || 0);
        if (quantity <= 0) {
            continue;
        }
        const parent = line.combo_parent_id;
        if (parent) {
            const parentTotal = Math.abs(_aveaLineMoney(parent, parent.priceIncl, parent.priceExcl).totalIncluded);
            if (parentTotal >= 0.0001) {
                continue;
            }
        }
        if (line.combo_line_ids?.length) {
            const ownTotal = Math.abs(_aveaLineMoney(line, line.priceIncl, line.priceExcl).totalIncluded);
            if (ownTotal < 0.0001) {
                continue;
            }
        }
        const product = line.product_id;
        const totals = _aveaLineMoney(line, line.priceIncl, line.priceExcl);
        const unitIncluded =
            typeof line.displayPriceUnitIncl === "number"
                ? line.displayPriceUnitIncl
                : quantity
                  ? totals.totalIncluded / quantity
                  : Number(line.price_unit) || 0;
        const name =
            (typeof line.getFullProductName === "function" && line.getFullProductName()) ||
            line.full_product_name ||
            product?.display_name ||
            product?.name ||
            "";
        if (!name) {
            continue;
        }
        lines.push({
            product_id: product?.id || false,
            name,
            default_code: product?.default_code || "",
            quantity,
            discount: typeof line.getDiscount === "function" ? line.getDiscount() : line.discount || 0,
            price_unit: unitIncluded,
            price_subtotal: totals.totalExcluded,
            price_total: totals.totalIncluded,
        });
    }
    return lines;
}

export class AveaQuotePopup extends Component {
    static template = "avea_till.AveaQuotePopup";
    static components = { Dialog };
    static props = ["close", "order", "getPayload?"];

    setup() {
        this.pos = usePos();
        this.notification = useService("notification");
        this.state = useState({
            note: "",
            quote: null,
            pdf: null,
            emailedTo: "",
            busy: false,
        });
        this.saveQuote = useAsyncLockedMethod(this.saveQuote);
        this.printQuote = useAsyncLockedMethod(this.printQuote);
        this.downloadQuote = useAsyncLockedMethod(this.downloadQuote);
        this.emailQuote = useAsyncLockedMethod(this.emailQuote);
    }

    get partner() {
        return this.props.order?.getPartner?.() || null;
    }

    get partnerName() {
        return this.partner?.name || "";
    }

    get canEmail() {
        return Boolean((this.state.quote?.partner_email || "").trim());
    }

    _errorMessage(error) {
        if (error instanceof RPCError) {
            return error.data?.message || error.message;
        }
        return error?.data?.message || error?.message || _t("The quote could not be completed.");
    }

    _cashierName() {
        const cashier = this.pos.getCashier?.() || this.pos.cashier;
        return cashier?.name || "";
    }

    async saveQuote() {
        const partner = this.partner;
        if (!partner) {
            this.notification.add(_t("Select a customer before creating a quote."), {
                type: "warning",
            });
            return;
        }
        const lines = aveaQuoteLines(this.props.order);
        if (!lines.length) {
            this.notification.add(_t("Add a product before creating a quote."), {
                type: "warning",
            });
            return;
        }
        this.state.busy = true;
        try {
            const result = await this.pos.data.call("avea.pos.quote", "create_from_pos", [
                {
                    partner_id: partner.id,
                    config_id: this.pos.config?.id || false,
                    session_id: this.pos.session?.id || false,
                    cashier_name: this._cashierName(),
                    note: this.state.note,
                    lines,
                },
            ]);
            this.state.quote = result;
        } catch (error) {
            this.notification.add(this._errorMessage(error), { type: "danger" });
        } finally {
            this.state.busy = false;
        }
    }

    async _loadPdf() {
        if (this.state.pdf) {
            return this.state.pdf;
        }
        const pdf = await this.pos.data.call("avea.pos.quote", "get_pdf", [[this.state.quote.id]]);
        this.state.pdf = pdf;
        return pdf;
    }

    _pdfBlob(pdf) {
        const binary = atob(pdf.pdf);
        const bytes = new Uint8Array(binary.length);
        for (let index = 0; index < binary.length; index++) {
            bytes[index] = binary.charCodeAt(index);
        }
        return new Blob([bytes], { type: "application/pdf" });
    }

    async printQuote() {
        this.state.busy = true;
        try {
            const pdf = await this._loadPdf();
            const url = URL.createObjectURL(this._pdfBlob(pdf));
            const opened = window.open(url, "_blank");
            if (!opened) {
                this.notification.add(_t("Allow pop-ups to print, or use Download PDF."), {
                    type: "warning",
                });
            }
            setTimeout(() => URL.revokeObjectURL(url), 60000);
        } catch (error) {
            this.notification.add(this._errorMessage(error), { type: "danger" });
        } finally {
            this.state.busy = false;
        }
    }

    async downloadQuote() {
        this.state.busy = true;
        try {
            const pdf = await this._loadPdf();
            const url = URL.createObjectURL(this._pdfBlob(pdf));
            const link = document.createElement("a");
            link.href = url;
            link.download = pdf.filename || "quote.pdf";
            document.body.appendChild(link);
            link.click();
            link.remove();
            setTimeout(() => URL.revokeObjectURL(url), 60000);
        } catch (error) {
            this.notification.add(this._errorMessage(error), { type: "danger" });
        } finally {
            this.state.busy = false;
        }
    }

    async emailQuote() {
        if (!this.canEmail) {
            this.notification.add(_t("This customer has no email address. Download the PDF instead."), {
                type: "warning",
            });
            return;
        }
        this.state.busy = true;
        try {
            const result = await this.pos.data.call("avea.pos.quote", "action_send_email", [
                [this.state.quote.id],
            ]);
            this.state.emailedTo = result.email;
            this.notification.add(_t("Quote emailed to %s.", result.email), { type: "success" });
        } catch (error) {
            this.notification.add(this._errorMessage(error), { type: "danger" });
        } finally {
            this.state.busy = false;
        }
    }
}
