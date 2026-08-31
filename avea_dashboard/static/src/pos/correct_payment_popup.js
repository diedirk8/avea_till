/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { Component, onWillStart, useState } from "@odoo/owl";
import { usePos } from "@point_of_sale/app/hooks/pos_hook";
import { Dialog } from "@web/core/dialog/dialog";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { useAsyncLockedMethod } from "@point_of_sale/app/hooks/hooks";
import { RPCError } from "@web/core/network/rpc";

export class CorrectPaymentPopup extends Component {
    static template = "avea_till.CorrectPaymentPopup";
    static components = { Dialog };
    static props = ["close", "getPayload?", "order"];

    setup() {
        this.pos = usePos();
        this.dialog = useService("dialog");
        this.notification = useService("notification");
        this.state = useState({
            loading: true,
            busy: false,
            blocked: false,
            blockReason: "",
            orderName: "",
            amountDisplay: "",
            currentMethodName: "",
            currentMethodKind: "",
            methods: [],
            newMethodId: null,
            reason: "",
        });
        this.confirm = useAsyncLockedMethod(this.confirm);
        onWillStart(() => this.loadOptions());
    }

    get canConfirm() {
        return Boolean(
            !this.state.loading &&
                !this.state.blocked &&
                !this.state.busy &&
                this.state.newMethodId &&
                this.state.reason.trim()
        );
    }

    async loadOptions() {
        try {
            const result = await this.pos.data.call(
                "pos.order",
                "avea_get_payment_correction_options",
                [[this.props.order.id]]
            );
            this.state.blocked = Boolean(result.blocked);
            this.state.blockReason = result.block_reason || "";
            this.state.orderName = result.order_name || this.props.order.getName();
            this.state.amountDisplay = result.amount_display || "";
            this.state.currentMethodName = result.current_method_name || "";
            this.state.currentMethodKind = result.current_method_kind || "";
            this.state.methods = result.methods || [];
            this.state.newMethodId = this.state.methods[0]?.id || null;
        } catch (error) {
            this.dialog.add(AlertDialog, {
                title: _t("Correct Payment Method"),
                body: this._errorMessage(error),
            });
            this.props.close();
        } finally {
            this.state.loading = false;
        }
    }

    onMethodChange(ev) {
        this.state.newMethodId = parseInt(ev.target.value, 10) || null;
    }

    _errorMessage(error) {
        if (error instanceof RPCError && error.data?.message) {
            return error.data.message;
        }
        return error?.message || _t("The payment method could not be corrected.");
    }

    async confirm() {
        if (!this.canConfirm) {
            return;
        }
        this.state.busy = true;
        try {
            const result = await this.pos.data.call(
                "pos.order",
                "avea_correct_payment_method",
                [
                    [this.props.order.id],
                    this.state.newMethodId,
                    this.state.reason.trim(),
                ]
            );
            if (!result?.successful) {
                throw new Error(_t("The payment method could not be corrected."));
            }
            const method = this.pos.models["pos.payment.method"].get(
                result.payment_method_id
            );
            const payment = this.props.order.payment_ids.find(
                (line) => line.id === result.payment_id
            );
            if (payment && method) {
                payment.payment_method_id = method;
                payment.name = result.payment_method_name || method.name;
            }
            this.notification.add(
                _t("Payment method corrected to %(method)s.", {
                    method: result.payment_method_name || method?.name || "",
                }),
                { type: "success" }
            );
            this.props.close(result);
        } catch (error) {
            this.dialog.add(AlertDialog, {
                title: _t("Correct Payment Method"),
                body: this._errorMessage(error),
            });
        } finally {
            this.state.busy = false;
        }
    }
}
