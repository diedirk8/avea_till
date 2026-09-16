/** @odoo-module **/

import { TicketScreen } from "@point_of_sale/app/screens/ticket_screen/ticket_screen";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";
import { makeAwaitable } from "@point_of_sale/app/utils/make_awaitable_dialog";
import { CorrectPaymentPopup } from "./correct_payment_popup";

/**
 * Client-side visibility is intentionally soft.
 *
 * Eligibility used to be re-implemented here and drifted from the backend:
 * blocking every `done` order hid legitimate open-session sales, while the
 * computed `avea_can_correct_payment` flag was unreliable on POS models whose
 * field list is empty (Odoo 19 loads all fields via read([])).
 *
 * The popup always asks the server (`avea_get_payment_correction_options`),
 * which is the source of truth for Cash/Card/EFT, Store Credit, split tender,
 * invoices and closed sessions.
 */
patch(TicketScreen.prototype, {
    _aveaOrderBelongsToOpenSession(order) {
        const currentSession = this.pos.session;
        if (!currentSession || currentSession.state !== "opened") {
            return false;
        }
        const orderSession = order.session_id;
        const orderSessionId = orderSession?.id ?? orderSession;
        if (orderSessionId && orderSessionId !== currentSession.id) {
            return false;
        }
        // If the related session record is loaded and already closed, hide.
        if (orderSession?.state && orderSession.state !== "opened") {
            return false;
        }
        return true;
    },

    get showCorrectPaymentMethod() {
        if (!this.pos.canCorrectPaymentMethod()) {
            return false;
        }
        const order = this.getSelectedOrder();
        if (!order || !this._aveaOrderBelongsToOpenSession(order)) {
            return false;
        }
        const completed =
            order.finalized || ["paid", "done"].includes(order.state);
        if (!completed || order.state === "cancel") {
            return false;
        }
        // Obvious hard blocks only — remaining rules are enforced by the server.
        if (order.account_move || order.state === "invoiced") {
            return false;
        }
        return true;
    },

    get showExchangeButton() {
        const order = this.getSelectedOrder();
        return Boolean(order && this.isOrderSynced && this.getHasItemsToRefund());
    },

    async openCorrectPaymentMethod() {
        const order = this.getSelectedOrder();
        if (!order || !this.showCorrectPaymentMethod) {
            return;
        }
        await makeAwaitable(this.dialog, CorrectPaymentPopup, { order });
    },

    async _aveaCreateReturnDestinationOrder({ exchange = false } = {}) {
        const order = this.getSelectedOrder();

        if (order && this._doesOrderHaveSoleItem(order)) {
            if (!this._prepareAutoRefundOnOrder(order)) {
                return null;
            }
        }

        if (!order || !this.getHasItemsToRefund()) {
            return null;
        }

        const partner = order.getPartner();
        const destinationOrder = this._getEmptyOrder(partner);

        if (exchange) {
            destinationOrder.avea_is_exchange = true;
        } else {
            destinationOrder.is_refund = true;
        }
        destinationOrder.pricelist_id = order.pricelist_id;

        const lines = [];
        for (const refundDetail of this._getRefundableDetails(partner, order)) {
            const refundLine = refundDetail.line;
            const alreadyRefundedLots = refundLine.refund_orderline_ids
                .filter((item) => !["cancel", "draft"].includes(item.order_id.state))
                .flatMap((item) => item.pack_lot_ids)
                .map((pack_lot) => pack_lot.lot_name);
            const options = refundLine.pack_lot_ids
                .map((p) => p.lot_name)
                .filter((lotName) => !alreadyRefundedLots.includes(lotName));
            const line = this.pos.models["pos.order.line"].create({
                qty: -refundDetail.qty,
                price_unit: refundLine.price_unit,
                product_id: refundLine.product_id,
                order_id: destinationOrder,
                discount: refundLine.discount,
                tax_ids: refundLine.tax_ids.map((tax) => ["link", tax]),
                refunded_orderline_id: refundLine,
                pack_lot_ids: options
                    .slice(0, refundDetail.qty)
                    .map((lotName) => ["create", { lot_name: lotName }]),
                price_type: "automatic",
                attribute_value_ids: refundLine.attribute_value_ids.map((attr) => ["link", attr]),
            });
            lines.push(line);
            refundDetail.destination_order_uuid = destinationOrder.uuid;
        }

        const refundComboParentLines = lines.filter(
            (l) => l.refunded_orderline_id.combo_line_ids.length > 0
        );
        for (const refundComboParent of refundComboParentLines) {
            const children = refundComboParent.refunded_orderline_id.combo_line_ids
                .map((l) => l.refund_orderline_ids)
                .flat();
            refundComboParent.combo_line_ids = [["link", ...children]];
        }

        if (order.fiscal_position_not_found) {
            this.dialog.add(AlertDialog, {
                title: _t("Fiscal Position not found"),
                body: _t(
                    "The fiscal position used in the original order is not loaded. Make sure it is loaded by adding it in the pos configuration."
                ),
            });
            return null;
        }

        if (order.fiscal_position_id) {
            destinationOrder.fiscal_position_id = order.fiscal_position_id;
        }
        this.setPartnerToRefundOrder(partner, destinationOrder);
        destinationOrder.refunded_order_id = order;
        this.pos.setOrder(destinationOrder);
        await this.addAdditionalRefundInfo(order, destinationOrder);
        this.postRefund(destinationOrder);
        this.pos.ticket_screen_mobile_pane = "left";
        return destinationOrder;
    },

    async onExchange() {
        const destinationOrder = await this._aveaCreateReturnDestinationOrder({
            exchange: true,
        });
        if (!destinationOrder) {
            return;
        }
        this.pos.updateRewards?.();
        destinationOrder.setScreenData({ name: "ProductScreen" });
        this.pos.navigate("ProductScreen", { orderUuid: destinationOrder.uuid });
    },
});
