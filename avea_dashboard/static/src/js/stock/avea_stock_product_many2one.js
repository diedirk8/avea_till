/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { markup } from "@odoo/owl";
import { patch } from "@web/core/utils/patch";
import { highlightText, odoomark } from "@web/core/utils/html";
import { Many2One } from "@web/views/fields/many2one/many2one";
import { Many2XAutocomplete } from "@web/views/fields/relational_utils";

const RICH_PRODUCT_SPECIFICATION = {
    display_name: {},
    default_code: {},
    barcode: {},
    qty_available: {},
};

export function aveaUsesRichProductM2o(context = {}) {
    return !!(
        context.avea_stock_receive_create ||
        context.avea_receive_id ||
        context.avea_rich_product_m2o
    );
}

/** Mirrors product.product._avea_plain_name (Python). */
function productPlainName(record) {
    const reference = String(record.default_code || "").trim();
    const raw = String(record.display_name || record.name || "").trim();
    if (!raw) {
        return _t("Unnamed");
    }
    const bracketMatch = raw.match(/^\[([^\]]+)\]\s*([\s\S]*)/);
    if (bracketMatch) {
        const name = (bracketMatch[2] || "").trim();
        if (name) {
            return name;
        }
    }
    if (reference && raw.startsWith(`[${reference}]`)) {
        const stripped = raw.slice(`[${reference}]`.length).trim();
        if (stripped) {
            return stripped;
        }
    }
    const lines = raw.split("\n").map((line) => line.trim()).filter(Boolean);
    if (lines.length > 1 && /^\[[^\]]+\]$/.test(lines[0])) {
        return lines.slice(1).join(" ");
    }
    return lines[0] || _t("Unnamed");
}

function escapeHtml(text) {
    return String(text)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
}

function formatQty(qty) {
    if (qty === undefined || qty === null || Number.isNaN(Number(qty))) {
        return "";
    }
    const value = Number(qty);
    return Number.isInteger(value) ? String(value) : value.toFixed(2);
}

function buildRichProductOptionMarkup(request, record) {
    const name = productPlainName(record);
    const nameHtml = highlightText(request, odoomark(name), "text-primary fw-bold");
    const metaParts = [];
    if (record.default_code) {
        metaParts.push(`${_t("SKU")} ${escapeHtml(record.default_code)}`);
    }
    if (record.barcode) {
        metaParts.push(`${_t("Barcode")} ${escapeHtml(record.barcode)}`);
    }
    const qtyLabel = formatQty(record.qty_available);
    if (qtyLabel !== "") {
        metaParts.push(`${_t("On hand")} ${escapeHtml(qtyLabel)}`);
    }
    const metaHtml = metaParts.length
        ? `<div class="o_avea_product_m2o_meta">${metaParts.join('<span class="o_avea_product_m2o_sep">·</span>')}</div>`
        : "";
    return markup(
        `<div class="o_avea_product_m2o_option"><div class="o_avea_product_m2o_name">${nameHtml}</div>${metaHtml}</div>`
    );
}

patch(Many2One.prototype, {
    get many2XAutocompleteProps() {
        const props = super.many2XAutocompleteProps;
        if (this.props.relation !== "product.product" || !aveaUsesRichProductM2o(this.props.context)) {
            return props;
        }
        return {
            ...props,
            specification: RICH_PRODUCT_SPECIFICATION,
        };
    },
});

patch(Many2XAutocomplete.prototype, {
    buildRecordSuggestion(request, record) {
        const suggestion = super.buildRecordSuggestion(request, record);
        if (
            this.props.resModel !== "product.product" ||
            !aveaUsesRichProductM2o(this.props.context)
        ) {
            return suggestion;
        }
        return {
            ...suggestion,
            cssClass: `${suggestion.cssClass || ""} o_avea_product_m2o_dropdown_option`.trim(),
            label: buildRichProductOptionMarkup(request, record),
        };
    },
});
