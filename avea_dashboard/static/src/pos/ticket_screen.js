/** @odoo-module **/

import { TicketScreen } from "@point_of_sale/app/screens/ticket_screen/ticket_screen";
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

    async openCorrectPaymentMethod() {
        const order = this.getSelectedOrder();
        if (!order || !this.showCorrectPaymentMethod) {
            return;
        }
        await makeAwaitable(this.dialog, CorrectPaymentPopup, { order });
    },
});
