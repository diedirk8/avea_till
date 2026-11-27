/** @odoo-module **/

import { PosOrder } from "@point_of_sale/app/models/pos_order";
import { ProductScreen } from "@point_of_sale/app/screens/product_screen/product_screen";
import { patch } from "@web/core/utils/patch";

patch(PosOrder.prototype, {
    updatePricelistAndFiscalPosition(newPartner) {
        if (newPartner?.id) {
            this.pos?._aveaPreparePlatformPartnerSync?.(newPartner);
        }
        super.updatePricelistAndFiscalPosition(...arguments);
        this.pos?._aveaApplyPlatformPricelistToOrder?.(this, newPartner);
    },
});

patch(ProductScreen.prototype, {
    getProductDisplayPrice(product) {
        const order = this.currentOrder;
        const pricelist = order?.pricelist_id || this.pos.config.pricelist_id;
        const template = product.product_tmpl_id || product;
        const variant = product.product_tmpl_id ? product : false;
        const config = this.pos.config;
        let amount = template.getPrice(pricelist, 1, 0, false, variant);
        if (config.iface_tax_included === "total") {
            const details = template.getTaxDetails({
                overridedValues: {
                    price: amount,
                    pricelist,
                    fiscalPosition: order?.fiscal_position_id || false,
                },
            });
            amount = details.total_included;
        }
        return this.env.utils.formatCurrency(amount, config.currency_id.id);
    },
});
