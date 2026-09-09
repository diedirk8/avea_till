/** @odoo-module **/

const PRINT_RECEIPT_COMPANY_FIELDS = [
    "avea_customize_printed_receipt",
    "avea_print_receipt_show_logo",
    "avea_print_receipt_logo_size",
    "avea_print_receipt_logo_max_height",
    "avea_print_receipt_show_order_number",
    "avea_print_receipt_show_datetime",
    "avea_print_receipt_show_customer",
    "avea_print_receipt_show_cashier",
    "avea_print_receipt_show_products",
    "avea_print_receipt_show_sku",
    "avea_print_receipt_show_quantity",
    "avea_print_receipt_show_unit_price",
    "avea_print_receipt_show_discounts",
    "avea_print_receipt_show_tax",
    "avea_print_receipt_show_subtotal",
    "avea_print_receipt_show_total",
    "avea_print_receipt_show_payment_method",
    "avea_print_receipt_show_amount_paid",
    "avea_print_receipt_show_change",
    "avea_print_receipt_show_loyalty_balance",
    "avea_print_receipt_show_store_credit_balance",
    "avea_print_receipt_show_customer_account_balance",
    "avea_print_receipt_footer_message",
    "avea_print_receipt_layout",
];

function isCompanyRecord(record) {
    return (
        record &&
        (Object.prototype.hasOwnProperty.call(record, "avea_customize_printed_receipt") ||
            Object.prototype.hasOwnProperty.call(record, "avea_print_receipt_layout"))
    );
}

export function getPrintReceiptCompany(source, pos) {
    if (!source) {
        return pos?.company || null;
    }
    if (isCompanyRecord(source)) {
        return source;
    }
    const nested = source.company || source.company_id;
    if (nested && typeof nested === "object") {
        return nested;
    }
    return pos?.company || null;
}

export function isAveaPrintCustomizeEnabled(source, pos) {
    const company = getPrintReceiptCompany(source, pos);
    return Boolean(company?.avea_customize_printed_receipt);
}

export function aveaPrintShow(source, fieldName, pos) {
    const company = getPrintReceiptCompany(source, pos);
    if (!isAveaPrintCustomizeEnabled(company, pos)) {
        return true;
    }
    if (company[fieldName] === undefined) {
        return true;
    }
    return Boolean(company[fieldName]);
}

export function aveaPrintLayoutClass(source, pos) {
    const company = getPrintReceiptCompany(source, pos);
    if (!isAveaPrintCustomizeEnabled(company, pos)) {
        return "";
    }
    const layout = company.avea_print_receipt_layout || "standard";
    return `avea-pos-receipt--${layout}`;
}

export function aveaPrintLogoClass(source, pos) {
    const company = getPrintReceiptCompany(source, pos);
    if (!isAveaPrintCustomizeEnabled(company, pos)) {
        return "";
    }
    if (company.avea_print_receipt_logo_max_height > 0) {
        return "";
    }
    const size = company.avea_print_receipt_logo_size || "medium";
    return `avea-pos-receipt-logo--${size}`;
}

export function aveaPrintLogoStyle(source, pos) {
    const company = getPrintReceiptCompany(source, pos);
    if (!isAveaPrintCustomizeEnabled(company, pos)) {
        return "";
    }
    const maxHeight = company.avea_print_receipt_logo_max_height || 0;
    if (!maxHeight) {
        return "";
    }
    return `max-height: ${maxHeight}px; max-width: 100%; width: auto; height: auto; object-fit: contain;`;
}

export async function loadAveaPrintReceiptCompanySettings(pos) {
    const company = pos?.company;
    if (!company?.id || !pos?.data?.call) {
        return company;
    }
    const settings = await pos.data.call(
        "res.company",
        "get_avea_print_receipt_pos_settings",
        [[company.id]]
    );
    if (settings) {
        Object.assign(company, settings);
        const configCompany = pos.config?.company_id;
        if (configCompany && configCompany.id === company.id) {
            Object.assign(configCompany, settings);
        }
    }
    return company;
}

export { PRINT_RECEIPT_COMPANY_FIELDS };
