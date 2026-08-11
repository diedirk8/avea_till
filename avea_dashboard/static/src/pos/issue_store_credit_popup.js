/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { parseFloat } from "@web/views/fields/parsers";
import { Component, useState } from "@odoo/owl";
import { usePos } from "@point_of_sale/app/hooks/pos_hook";
import { Dialog } from "@web/core/dialog/dialog";
import { Input } from "@point_of_sale/app/components/inputs/input/input";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { PartnerList } from "@point_of_sale/app/screens/partner_list/partner_list";
import { makeAwaitable } from "@point_of_sale/app/utils/make_awaitable_dialog";
import { useAsyncLockedMethod } from "@point_of_sale/app/hooks/hooks";
import { RPCError } from "@web/core/network/rpc";

export class IssueStoreCreditPopup extends Component {
    static template = "avea_till.IssueStoreCreditPopup";
    static components = { Dialog, Input };
    static props = ["close", "getPayload?"];

    setup() {
        this.pos = usePos();
        this.dialog = useService("dialog");
        this.notification = useService("notification");
        this.reasonOptions = this._loadReasonOptions();
        this.state = useState({
            partner: null,
            amount: "",
            reasonId: this.reasonOptions[0]?.id ?? null,
            notes: "",
        });
        this.confirm = useAsyncLockedMethod(this.confirm);
    }

    _loadReasonOptions() {
        const reasonModel = this.pos.models["avea.credit.reason"];
        if (!reasonModel) {
            return [];
        }
        // getAll() returns the model's internal orderedRecords array; never
        // sort that reference in place or reactive POS updates loop forever.
        return [...reasonModel.getAll()].sort(
            (a, b) =>
                (a.sequence || 0) - (b.sequence || 0) ||
                (a.name || "").localeCompare(b.name || "")
        );
    }

    get formattedBalance() {
        if (!this.state.partner) {
            return "";
        }
        return this.pos.formatStoreCreditAmount(
            this.pos.getPartnerStoreCreditBalance(this.state.partner),
            this.state.partner
        );
    }

    get canIssue() {
        const amount = parseFloat(this.state.amount);
        return Boolean(this.state.partner && amount > 0 && this.state.reasonId);
    }

    async selectCustomer() {
        const partner = await makeAwaitable(this.dialog, PartnerList, {
            partner: this.state.partner,
        });
        if (partner) {
            this.state.partner = partner;
        }
    }

    onReasonChange(ev) {
        this.state.reasonId = parseInt(ev.target.value, 10) || null;
    }

    async confirm() {
        const partner = this.state.partner;
        if (!partner) {
            this.dialog.add(AlertDialog, {
                title: _t("Issue Store Credit"),
                body: _t("Select a customer before issuing store credit."),
            });
            return;
        }
        const amount = parseFloat(this.state.amount);
        if (!amount || amount <= 0) {
            this.dialog.add(AlertDialog, {
                title: _t("Issue Store Credit"),
                body: _t("Store credit amount must be greater than zero."),
            });
            return;
        }
        if (!this.state.reasonId) {
            this.dialog.add(AlertDialog, {
                title: _t("Issue Store Credit"),
                body: _t("No store credit issue reason is configured."),
            });
            return;
        }
        try {
            const result = await this.pos.data.call(
                "avea.credit.ledger.entry",
                "pos_issue_store_credit",
                [
                    partner.id,
                    amount,
                    this.state.reasonId,
                    this.state.notes.trim() || false,
                ]
            );
            this.pos.updatePartnerStoreCreditBalance(partner.id, result.balance);
            this.notification.add(
                _t(
                    "%(amount)s Store Credit successfully issued to %(customer)s.",
                    {
                        amount: this.pos.formatStoreCreditAmount(amount, partner),
                        customer: result.partner_name || partner.name,
                    }
                ),
                { type: "success" }
            );
            this.props.close();
        } catch (error) {
            const body =
                error instanceof RPCError && error.data?.message
                    ? error.data.message
                    : error.message;
            this.dialog.add(AlertDialog, {
                title: _t("Issue Store Credit"),
                body,
            });
        }
    }
}
