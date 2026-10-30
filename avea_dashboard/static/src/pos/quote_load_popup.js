/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { Component, onWillStart, useState } from "@odoo/owl";
import { usePos } from "@point_of_sale/app/hooks/pos_hook";
import { Dialog } from "@web/core/dialog/dialog";
import { useAsyncLockedMethod } from "@point_of_sale/app/hooks/hooks";
import { RPCError } from "@web/core/network/rpc";

export class AveaLoadQuotePopup extends Component {
    static template = "avea_till.AveaLoadQuotePopup";
    static components = { Dialog };
    static props = ["close", "getPayload?"];

    setup() {
        this.pos = usePos();
        this.notification = useService("notification");
        this.state = useState({
            search: "",
            quotes: [],
            loading: true,
            busy: false,
        });
        this.loadQuotes = useAsyncLockedMethod(this.loadQuotes);
        this.addQuote = useAsyncLockedMethod(this.addQuote);
        onWillStart(() => this.loadQuotes());
    }

    _errorMessage(error) {
        if (error instanceof RPCError) {
            return error.data?.message || error.message;
        }
        return error?.data?.message || error?.message || _t("The quote could not be added.");
    }

    async loadQuotes() {
        this.state.loading = true;
        try {
            const rows = await this.pos.data.call("avea.pos.quote", "list_open_for_pos", [
                {
                    company_id: this.pos.company?.id || false,
                    search: this.state.search,
                },
            ]);
            this.state.quotes = rows || [];
        } catch (error) {
            this.notification.add(this._errorMessage(error), { type: "danger" });
            this.state.quotes = [];
        } finally {
            this.state.loading = false;
        }
    }

    onSearchInput(event) {
        this.state.search = event.target.value;
        this.loadQuotes();
    }

    async addQuote(quoteId) {
        const order = this.pos.getOrder();
        if (!order) {
            this.notification.add(_t("Open a sale before loading a quote."), { type: "warning" });
            return;
        }
        this.state.busy = true;
        try {
            const quote = await this.pos.data.call("avea.pos.quote", "get_for_sale", [[quoteId]]);
            await this._applyQuote(order, quote);
            this.notification.add(_t("Added %s to the sale.", quote.name), { type: "success" });
            this.props.close();
        } catch (error) {
            this.notification.add(this._errorMessage(error), { type: "danger" });
        } finally {
            this.state.busy = false;
        }
    }

    async _applyQuote(order, quote) {
        if (!order.getPartner() && quote.partner_id) {
            let partner = this.pos.models["res.partner"].get(quote.partner_id);
            if (!partner) {
                await this.pos.data.read("res.partner", [quote.partner_id]);
                partner = this.pos.models["res.partner"].get(quote.partner_id);
            }
            if (partner) {
                await this.pos.setPartnerToCurrentOrder(partner);
            }
        }
        const missing = [];
        let added = 0;
        for (const row of quote.lines || []) {
            const product = row.product_id
                ? this.pos.models["product.product"].get(row.product_id)
                : null;
            if (!product) {
                missing.push(row.name || _t("A product"));
                continue;
            }
            const values = {
                product_id: product,
                product_tmpl_id: product.product_tmpl_id,
                qty: Number(row.quantity) || 1,
            };
            const price = Number(row.pos_price_unit);
            if (price) {
                values.price_unit = price;
            }
            const line = await this.pos.addLineToCurrentOrder(values, {}, false);
            if (!line) {
                missing.push(row.name || product.display_name);
                continue;
            }
            const discount = Number(row.discount) || 0;
            if (discount) {
                line.setDiscount(discount);
            }
            added += 1;
        }
        if (!added) {
            throw new Error(_t("None of the products on this quote are on the till."));
        }
        if (missing.length) {
            this.notification.add(
                _t("Could not add: %s.", missing.join(", ")),
                { type: "warning" }
            );
        }
    }
}
