/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { parseFloat } from "@web/views/fields/parsers";
import { Component, onWillStart, useState } from "@odoo/owl";
import { usePos } from "@point_of_sale/app/hooks/pos_hook";
import { Dialog } from "@web/core/dialog/dialog";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { useAsyncLockedMethod } from "@point_of_sale/app/hooks/hooks";
import { RPCError } from "@web/core/network/rpc";
import { waitImages } from "@point_of_sale/utils";
import { CashUpReceipt } from "./cash_up_receipt";

const PAYMENT_KINDS = ["cash", "card", "eft", "store_credit", "other"];
const DEFAULT_LABELS = {
    cash: "Cash",
    card: "Card",
    eft: "EFT",
    store_credit: "Store Credit",
    other: "Other",
};
const SUMMARY_LABELS = {
    cash: "Cash Payments",
    card: "Card Payments",
    eft: "EFT Payments",
    store_credit: "Store Credit",
    other: "Other",
};

export class CashUpPopup extends Component {
    static template = "avea_till.CashUpPopup";
    static components = { Dialog };
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
            countedPayments: {},
            varianceReason: "",
            preview: null,
            transactionCount: 0,
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

    get currencySymbol() {
        return this.pos.currency.symbol || "";
    }

    get currencyBefore() {
        return this.pos.currency.position === "before";
    }

    formatAmount(amount) {
        return this.env.utils.formatCurrency(amount || 0);
    }

    formatSessionDate(dateStr) {
        if (!dateStr) {
            return "";
        }
        const parsed = new Date(dateStr.replace(" ", "T"));
        if (Number.isNaN(parsed.getTime())) {
            return dateStr;
        }
        const months = [
            "January",
            "February",
            "March",
            "April",
            "May",
            "June",
            "July",
            "August",
            "September",
            "October",
            "November",
            "December",
        ];
        const hours = String(parsed.getHours()).padStart(2, "0");
        const minutes = String(parsed.getMinutes()).padStart(2, "0");
        return `${parsed.getDate()} ${months[parsed.getMonth()]} ${parsed.getFullYear()} • ${hours}:${minutes}`;
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

    get remainingCash() {
        if (!this.state.preview) {
            return 0;
        }
        const opening = this.state.preview.opening_cash_amount || 0;
        if (this.countedValue < opening) {
            return this.countedValue;
        }
        return opening;
    }

    _lineMap() {
        const lines = {};
        for (const line of this.state.preview?.payment_lines || []) {
            lines[line.kind] = line;
        }
        return lines;
    }

    get cashPaymentsExpectedAmount() {
        const preview = this.state.preview;
        if (
            preview?.cash_payments_expected_amount !== undefined &&
            preview?.cash_payments_expected_amount !== null
        ) {
            return preview.cash_payments_expected_amount;
        }
        const cashLine = preview?.payment_lines?.find((line) => line.kind === "cash");
        const opening = preview?.opening_cash_amount || 0;
        const drawerExpected = preview?.expected_cash_amount || 0;
        const raw = cashLine?.expected_amount || 0;
        if (opening > 0 && Math.abs(raw - drawerExpected) < 0.00001) {
            return raw - opening;
        }
        return raw;
    }

    get cashPaymentsExpectedLabel() {
        const preview = this.state.preview;
        if (preview?.cash_payments_expected) {
            return preview.cash_payments_expected;
        }
        return this.formatAmount(this.cashPaymentsExpectedAmount);
    }

    paymentExpectedAmount(line) {
        if (line.kind === "cash") {
            return this.state.preview?.expected_cash_amount || 0;
        }
        return line.expected_amount || 0;
    }

    get tallyLines() {
        if (!this.state.preview) {
            return [];
        }
        const byKind = this._lineMap();
        const preview = this.state.preview;
        return PAYMENT_KINDS.map((kind) => {
            const line = byKind[kind];
            const expectedAmount =
                kind === "cash"
                    ? preview.expected_cash_amount || 0
                    : line?.expected_amount || 0;
            const expectedLabel =
                kind === "cash"
                    ? preview.expected_cash || this.formatAmount(expectedAmount)
                    : line?.expected || this.formatAmount(0);
            return {
                kind,
                label: line?.label || DEFAULT_LABELS[kind],
                expected: expectedLabel,
                expected_amount: expectedAmount,
                is_active: Math.abs(expectedAmount) > 0.0000001,
            };
        });
    }

    get transactionCount() {
        return this.state.transactionCount;
    }

    get paymentSummaryLines() {
        const preview = this.state.preview;
        const summary = preview?.payment_summary;
        const cashAmount = this.cashPaymentsExpectedAmount;
        const cashLabel = this.cashPaymentsExpectedLabel;
        if (summary?.length) {
            return summary.map((item) => {
                if (item.kind === "cash") {
                    return {
                        ...item,
                        amount: cashLabel,
                        amount_value: cashAmount,
                    };
                }
                return item;
            });
        }
        return this.tallyLines.map((line) => ({
            kind: line.kind,
            label: SUMMARY_LABELS[line.kind] || line.label,
            amount: line.kind === "cash" ? cashLabel : line.expected,
            amount_value: line.expected_amount,
        }));
    }

    countedInputValue(line) {
        if (line.kind === "cash") {
            return this.state.counted;
        }
        return this.state.countedPayments[line.kind] ?? "";
    }

    onCountedInput(line, ev) {
        if (line.kind === "cash") {
            this.state.counted = ev.target.value;
            return;
        }
        this.state.countedPayments[line.kind] = ev.target.value;
    }

    countedPaymentValue(kind, expectedAmount = 0) {
        const raw = this.state.countedPayments[kind];
        if (raw === undefined || raw === "") {
            return expectedAmount;
        }
        return this.env.utils.isValidFloat(raw) ? parseFloat(raw) : expectedAmount;
    }

    paymentDifference(line) {
        const expected = this.paymentExpectedAmount(line);
        const counted =
            line.kind === "cash"
                ? this.countedValue
                : this.countedPaymentValue(line.kind, expected);
        return counted - expected;
    }

    get totalPaymentsCounted() {
        if (!this.state.preview) {
            return 0;
        }
        let total = this.cashPaymentsExpectedAmount;
        for (const line of this.tallyLines) {
            if (line.kind === "cash") {
                continue;
            }
            total += this.countedPaymentValue(line.kind, this.paymentExpectedAmount(line));
        }
        return total;
    }

    get totalPaymentsDifference() {
        if (!this.state.preview) {
            return 0;
        }
        return (
            this.totalPaymentsCounted -
            (this.state.preview.total_payments_expected_amount || 0)
        );
    }

    isZero(value) {
        return Math.abs(value || 0) < 0.0000001;
    }

    get hasVariance() {
        if (!this.state.preview) {
            return false;
        }
        if (!this.isZero(this.totalPaymentsDifference)) {
            return true;
        }
        if (!this.isZero(this.difference)) {
            return true;
        }
        return this.tallyLines.some(
            (line) => line.kind !== "cash" && !this.isZero(this.paymentDifference(line))
        );
    }

    varianceClass(value) {
        if (this.isZero(value)) {
            return "text-success";
        }
        return "text-warning fw-bold";
    }

    rowClass(line) {
        return line.is_active ? "" : "text-muted";
    }

    get canConfirm() {
        if (this.state.loading || this.state.busy || !this.state.preview) {
            return false;
        }
        if (this.hasVariance && !(this.state.varianceReason || "").trim()) {
            return false;
        }
        return true;
    }

    get dialogTitle() {
        if (this.state.phase === "complete") {
            return _t("Cash Up Complete");
        }
        return _t("Cash Up");
    }

    _initCountedPayments(preview) {
        const countedPayments = {};
        const byKind = {};
        for (const line of preview.payment_lines || []) {
            byKind[line.kind] = line;
        }
        for (const kind of PAYMENT_KINDS) {
            if (kind === "cash") {
                continue;
            }
            const line = byKind[kind];
            countedPayments[kind] = String(line?.expected_amount ?? "");
        }
        return countedPayments;
    }

    _setCountedPayments(countedPayments) {
        for (const key of Object.keys(this.state.countedPayments)) {
            delete this.state.countedPayments[key];
        }
        Object.assign(this.state.countedPayments, countedPayments);
    }

    _countedPaymentsPayload() {
        const payload = {};
        for (const kind of PAYMENT_KINDS) {
            if (kind === "cash") {
                continue;
            }
            const raw = this.state.countedPayments[kind];
            if (raw !== undefined && raw !== "") {
                payload[kind] = parseFloat(raw);
            }
        }
        return payload;
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
            this.state.transactionCount = this._coerceTransactionCount(
                preview?.transaction_count
            );
            this.state.counted = String(preview.expected_cash_amount ?? "");
            this._setCountedPayments(this._initCountedPayments(preview));
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

    _coerceTransactionCount(value) {
        if (typeof value === "number" && Number.isFinite(value)) {
            return value;
        }
        if (typeof value === "string" && value.trim() !== "") {
            const parsed = Number(value);
            if (Number.isFinite(parsed)) {
                return parsed;
            }
        }
        return 0;
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
        if (this.hasVariance && !(this.state.varianceReason || "").trim()) {
            this.dialog.add(AlertDialog, {
                title: _t("Cash Up"),
                body: _t("Enter a reason for the variance before confirming Cash Up."),
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
                [
                    this.pos.session.id,
                    counted,
                    this._countedPaymentsPayload(),
                    this.state.varianceReason,
                    this.cashierName,
                ],
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
