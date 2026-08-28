/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { parseFloat } from "@web/views/fields/parsers";
import { Component, onWillStart, useState } from "@odoo/owl";
import { usePos } from "@point_of_sale/app/hooks/pos_hook";
import { Dialog } from "@web/core/dialog/dialog";
import { Input } from "@point_of_sale/app/components/inputs/input/input";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { useAsyncLockedMethod } from "@point_of_sale/app/hooks/hooks";
import { RPCError } from "@web/core/network/rpc";
import { waitImages } from "@point_of_sale/utils";
import { CashUpReceipt } from "./cash_up_receipt";

export class CashUpPopup extends Component {
    static template = "avea_till.CashUpPopup";
    static components = { Dialog, Input };
    static props = {
        close: Function,
        getPayload: { type: Function, optional: true },
        completedResult: { type: Object, optional: true },
        printError: { type: String, optional: true },
    };

    setup() {
        this.pos = usePos();
        this.dialog = useService("dialog");
        this.hardwareProxy = useService("hardware_proxy");
        this.renderer = useService("renderer");
        this.printer = useService("printer");
        this.state = useState({
            loading: !this.props.completedResult,
            busy: false,
            phase: this.props.completedResult ? "complete" : "form",
            counted: "",
            preview: null,
            result: this.props.completedResult || null,
            printError: this.props.printError || "",
        });
        this.confirm = useAsyncLockedMethod(this.confirm);
        this.reprint = useAsyncLockedMethod(this.reprint);
        onWillStart(() => this.loadPreview());
    }

    get cashierName() {
        return this.pos.getCashierName?.() || this.pos.user?.name || "";
    }

    formatAmount(amount) {
        return this.env.utils.formatCurrency(amount || 0);
    }

    get countedValue() {
        return this.env.utils.isValidFloat(this.state.counted)
            ? parseFloat(this.state.counted)
            : this.state.preview?.expected_cash_amount || 0;
    }

    get difference() {
        if (!this.state.preview) {
            return 0;
        }
        return this.countedValue - this.state.preview.expected_cash_amount;
    }

    get cashToSafe() {
        if (!this.state.preview) {
            return 0;
        }
        return Math.max(this.countedValue - this.state.preview.opening_cash_amount, 0);
    }

    get dialogTitle() {
        return this.state.phase === "complete" ? _t("Cash Up Complete") : _t("Cash Up");
    }

    async loadPreview() {
        if (this.state.phase === "complete") {
            this.state.loading = false;
            return;
        }
        try {
            const preview = await this.pos.data.call(
                "avea.cash.up",
                "pos_get_cash_up_preview",
                [this.pos.session.id]
            );
            this.state.preview = preview;
            this.state.counted = String(preview.expected_cash_amount ?? "");
        } catch (error) {
            this.dialog.add(AlertDialog, {
                title: _t("Cash Up"),
                body: this._errorMessage(error),
            });
            this.props.close();
        } finally {
            this.state.loading = false;
        }
    }

    _errorMessage(error) {
        if (error instanceof RPCError && error.data?.message) {
            return error.data.message;
        }
        return error?.body || error?.message || _t("Cash Up failed.");
    }

    _createReceiptOrder() {
        return this.pos.models["pos.order"].create({
            session_id: this.pos.session,
            company_id: this.pos.company,
            config_id: this.pos.config,
            user_id: this.pos.user,
            ticket_code: "",
            tracking_number: "",
            sequence_number: 0,
            pos_reference: "",
        });
    }

    /**
     * Print the Cash Up slip through the same 80mm POS receipt path as
     * order receipts: render the OWL receipt to HTML, then
     * hardware_proxy.printer.printReceipt, or Odoo's pos-receipt web fallback.
     *
     * Do not use PosPrinterService.printHtml: it closeAll()s this dialog
     * on error. Await the web fallback so a print failure is not treated
     * as success.
     */
    async printSlip(receipt, order) {
        this.printer.setPrinter(this.hardwareProxy.printer);
        const el = await this.renderer.toHtml(CashUpReceipt, {
            receipt,
            order,
        });
        try {
            await waitImages(el);
        } catch {
            // Logo load failure should not block the till slip.
        }
        if (this.printer.device?.printReceipt) {
            const printResult = await this.printer.device.printReceipt(el);
            if (!printResult?.successful) {
                return (
                    printResult || {
                        successful: false,
                        message: {
                            title: _t("Printing Error"),
                            body: _t(
                                "The Cash Up slip did not print. The till is closed. Check the receipt printer and tap Reprint."
                            ),
                        },
                    }
                );
            }
            return printResult;
        }
        try {
            await this.renderer.whenMounted({
                el,
                callback: async (mountedEl) => {
                    try {
                        await waitImages(mountedEl);
                    } catch {
                        // Logo load failure should not block the till slip.
                    }
                    window.print(mountedEl);
                },
            });
            return { successful: true };
        } catch (error) {
            return {
                successful: false,
                message: {
                    title: error.title || _t("Printing Error"),
                    body:
                        error.body ||
                        error.message ||
                        _t(
                            "The Cash Up slip did not print. The till is closed. Check the receipt printer and tap Reprint."
                        ),
                },
            };
        }
    }

    _printErrorMessage(printResult) {
        if (printResult?.successful) {
            return "";
        }
        return (
            printResult?.message?.body ||
            _t(
                "The Cash Up slip did not print. The till is closed. Check the receipt printer and tap Reprint."
            )
        );
    }

    async confirm() {
        if (!this.state.preview || this.state.phase !== "form" || this.state.busy) {
            return;
        }
        const counted = this.countedValue;
        if (counted < 0) {
            this.dialog.add(AlertDialog, {
                title: _t("Cash Up"),
                body: _t("Counted Cash cannot be negative."),
            });
            return;
        }
        this.state.busy = true;
        this.pos.aveaSuppressSessionReload = true;
        const syncSuccess = await this.pos.pushOrdersWithClosingPopup();
        if (!syncSuccess) {
            this.pos.aveaSuppressSessionReload = false;
            this.state.busy = false;
            return;
        }
        let order;
        try {
            order = this._createReceiptOrder();
            const result = await this.pos.data.call(
                "avea.cash.up",
                "pos_confirm_cash_up",
                [this.pos.session.id, counted, this.cashierName],
                {
                    context: {
                        device_identifier: this.pos.device.identifier,
                    },
                }
            );
            if (!result?.successful) {
                throw new Error(result?.message || _t("Cash Up failed."));
            }
            this.pos.session.state = "closed";
            this.state.result = result;
            this.state.phase = "complete";
            try {
                const printResult = await this.printSlip(result.receipt, order);
                this.state.printError = this._printErrorMessage(printResult);
            } catch (printError) {
                this.state.printError =
                    this._errorMessage(printError) ||
                    _t(
                        "The Cash Up slip did not print. The till is closed. Check the receipt printer and tap Reprint."
                    );
            }
        } catch (error) {
            if (this.state.result?.successful) {
                this.state.printError = this._errorMessage(error);
                this.state.phase = "complete";
            } else {
                this.pos.aveaSuppressSessionReload = false;
                this.dialog.add(AlertDialog, {
                    title: _t("Cash Up"),
                    body: this._errorMessage(error),
                });
            }
        } finally {
            if (order) {
                this.pos.models["pos.order"].delete(order);
            }
            this.state.busy = false;
        }
    }

    async reprint() {
        if (!this.state.result?.receipt || this.state.busy) {
            return;
        }
        this.state.busy = true;
        let order;
        try {
            order = this._createReceiptOrder();
            const printResult = await this.printSlip(this.state.result.receipt, order);
            this.state.printError = this._printErrorMessage(printResult);
        } catch (error) {
            this.state.printError = this._errorMessage(error);
        } finally {
            if (order) {
                this.pos.models["pos.order"].delete(order);
            }
            this.state.busy = false;
        }
    }

    done() {
        this.props.close(this.state.result);
        this.pos.router.close();
    }
}
