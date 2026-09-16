/** @odoo-module **/

import { Component } from "@odoo/owl";
import { ReceiptHeader } from "@point_of_sale/app/screens/receipt_screen/receipt/receipt_header/receipt_header";

export class CashUpReceipt extends Component {
    static template = "avea_till.CashUpReceipt";
    static components = { ReceiptHeader };
    static props = {
        receipt: Object,
        order: Object,
    };

    get hasVariance() {
        return Boolean(this.props.receipt?.has_variance);
    }

    get activePaymentLines() {
        const lines = this.props.receipt?.payment_lines || [];
        return lines.filter((line) => this._lineHasActivity(line));
    }

    get varianceLabel() {
        const receipt = this.props.receipt;
        const paymentDiff = receipt.total_payments_difference_amount || 0;
        const cashDiff = receipt.difference_amount || 0;
        if (Math.abs(paymentDiff) > 0.0000001) {
            return receipt.total_payments_difference;
        }
        return receipt.difference;
    }

    isNonZeroDifference(value) {
        return Math.abs(value || 0) > 0.0000001;
    }

    _lineHasActivity(line) {
        const expected = line.expected_amount || 0;
        const counted = line.counted_amount || 0;
        const difference = line.difference_amount || 0;
        return (
            Math.abs(expected) > 0.0000001 ||
            Math.abs(counted) > 0.0000001 ||
            Math.abs(difference) > 0.0000001
        );
    }
}
