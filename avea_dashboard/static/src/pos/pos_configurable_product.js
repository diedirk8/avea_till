/** @odoo-module **/

import { PosStore } from "@point_of_sale/app/services/pos_store";
import { patch } from "@web/core/utils/patch";

function _aveaResolveVariantProduct(values, productTemplate, opts = {}) {
    if (values?.product_id) {
        return values.product_id;
    }
    if (opts?.presetVariant) {
        return opts.presetVariant;
    }
    if (opts?.product) {
        return opts.product;
    }
    const variants = productTemplate?.product_variant_ids || [];
    if (variants.length === 1) {
        return variants[0];
    }
    return null;
}

function _aveaIsVariantProductError(error) {
    const message = error?.message || "";
    return (
        message.includes("product_template_variant_value_ids") ||
        message.includes("product_template_attribute_value_ids")
    );
}

patch(PosStore.prototype, {
    async addLineToOrder(vals, opts = {}, configure = true) {
        const productTemplate =
            typeof vals.product_tmpl_id === "number"
                ? this.models["product.template"].get(vals.product_tmpl_id)
                : vals.product_tmpl_id;
        if (productTemplate && !vals.product_id) {
            const resolved = _aveaResolveVariantProduct(vals, productTemplate, opts);
            if (resolved) {
                vals.product_id = resolved;
            }
        }
        return super.addLineToOrder(vals, opts, configure);
    },

    async handleConfigurableProduct(values, productTemplate, opts = {}, configure = true) {
        const needsConfigurator = productTemplate?.isConfigurable?.() && configure;
        if (!needsConfigurator || opts?.presetVariant || opts?.product) {
            const resolved = _aveaResolveVariantProduct(values, productTemplate, opts);
            if (resolved) {
                values.product_id = resolved;
            }
        }
        try {
            return await super.handleConfigurableProduct(
                values,
                productTemplate,
                opts,
                configure
            );
        } catch (error) {
            if (!_aveaIsVariantProductError(error)) {
                throw error;
            }
            const resolved = _aveaResolveVariantProduct(values, productTemplate, opts);
            if (!resolved) {
                throw error;
            }
            values.product_id = resolved;
            return await super.handleConfigurableProduct(
                values,
                productTemplate,
                { ...opts, presetVariant: resolved },
                false
            );
        }
    },
});
