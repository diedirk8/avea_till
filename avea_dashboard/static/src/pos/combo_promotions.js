/** @odoo-module **/

import { PosStore } from "@point_of_sale/app/services/pos_store";
import { PosOrder } from "@point_of_sale/app/models/pos_order";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";

function _aveaRoundMoney(order, amount) {
    const currency = order.currency;
    if (currency?.round) {
        return currency.round(amount);
    }
    return Math.round((amount + Number.EPSILON) * 100) / 100;
}

function _aveaIsComboProgram(program) {
    return Boolean(program?.avea_is_combo);
}

function _aveaComboIsCodeActivated(order, program) {
    if (program.trigger !== "with_code") {
        return true;
    }
    if (order._code_activated_coupon_ids?.some((coupon) => coupon.program_id?.id === program.id)) {
        return true;
    }
    return Object.values(order.uiState?.couponPointChanges || {}).some(
        (change) => change.program_id === program.id
    );
}

function _aveaProductLines(order) {
    return (order.getOrderlines?.() || order.lines || []).filter(
        (line) => !line.is_reward_line && !line.avea_combo_program_id && !line.combo_parent_id
    );
}

function _aveaCountCompleteComboSets(order, components) {
    if (!components?.length) {
        return 0;
    }
    const qtyByProduct = new Map();
    for (const line of _aveaProductLines(order)) {
        const productId = line.getProduct?.()?.id || line.product_id?.id;
        if (!productId) {
            continue;
        }
        const qty = Number(line.getQuantity?.() ?? line.qty) || 0;
        qtyByProduct.set(productId, (qtyByProduct.get(productId) || 0) + qty);
    }
    let sets = Infinity;
    for (const component of components) {
        const required = Number(component.quantity) || 0;
        if (required <= 0) {
            return 0;
        }
        const available = qtyByProduct.get(component.product_id) || 0;
        sets = Math.min(sets, Math.floor(available / required));
    }
    return Number.isFinite(sets) ? sets : 0;
}

/**
 * Build tax-split discount amounts the same way native loyalty does:
 * allocate the tax-included combo discount across the tax groups of the
 * products that make up the combo sets, using each line's tax-excluded base.
 */
function _aveaComboDiscountByTax(order, components, sets, discountIncl) {
    const remaining = new Map(
        components.map((component) => [component.product_id, component.quantity * sets])
    );
    const discountablePerTax = new Map(); // taxKey -> { taxes, baseExcl, inclShare }
    let catalogIncl = 0;
    let catalogBase = 0;

    for (const line of _aveaProductLines(order)) {
        const productId = line.getProduct?.()?.id || line.product_id?.id;
        const need = remaining.get(productId) || 0;
        if (need <= 0) {
            continue;
        }
        const lineQty = Number(line.getQuantity?.() ?? line.qty) || 0;
        if (lineQty <= 0) {
            continue;
        }
        const take = Math.min(need, lineQty);
        const lineIncl = Number(line.prices?.total_included ?? line.price_subtotal_incl) || 0;
        const lineBase =
            Number(line.basePrice ?? line.prices?.total_excluded ?? line.price_subtotal) || 0;
        const shareIncl = (lineIncl / lineQty) * take;
        const shareBase = (lineBase / lineQty) * take;
        catalogIncl += shareIncl;
        catalogBase += shareBase;

        const taxes = (line.tax_ids || []).filter((tax) => tax.amount_type !== "fixed");
        const taxKey = taxes.map((tax) => tax.id).join(",");
        if (!discountablePerTax.has(taxKey)) {
            discountablePerTax.set(taxKey, { taxes, base: 0 });
        }
        discountablePerTax.get(taxKey).base += shareBase;
        remaining.set(productId, need - take);
    }

    if (catalogIncl <= 0 || discountIncl <= 0) {
        return { catalogIncl: 0, parts: [] };
    }

    // Native loyalty: price_unit is the negative tax-excluded base share times
    // (discountIncl / catalogIncl), with the product taxes attached. For
    // price-included taxes POS stores/display uses included amounts on normal
    // lines; real posted loyalty discounts use price_unit = -included with taxes.
    // Match posted loyalty behaviour: split the included discount by base weight.
    const parts = [];
    const entries = [...discountablePerTax.entries()].filter(([, value]) => value.base);
    const totalBase = entries.reduce((sum, [, value]) => sum + value.base, 0) || catalogBase;
    let allocated = 0;
    entries.forEach(([taxKey, value], index) => {
        let partIncl;
        if (index === entries.length - 1) {
            partIncl = _aveaRoundMoney(order, discountIncl - allocated);
        } else {
            partIncl = _aveaRoundMoney(order, (discountIncl * value.base) / totalBase);
            allocated += partIncl;
        }
        if (Math.abs(partIncl) < 0.0001) {
            return;
        }
        parts.push({
            taxKey,
            taxes: value.taxes,
            // Tax-included negative unit, same as native loyalty reward lines.
            priceUnit: -partIncl,
        });
    });
    return { catalogIncl, parts };
}

function _aveaRemoveComboDiscountLines(order) {
    const lines = [...(order.getOrderlines?.() || order.lines || [])];
    for (const line of lines) {
        if (line.avea_combo_program_id) {
            line.delete();
        }
    }
}

function _aveaFindComboDiscountProduct(order, program) {
    const reward = program.reward_ids?.[0];
    if (reward?.discount_line_product_id) {
        return reward.discount_line_product_id;
    }
    return order.models["product.product"].find(
        (product) => product.default_code === "AVEA_COMBO_DISCOUNT"
    );
}

function _aveaComboLineLabel(program, sets) {
    if (sets > 1) {
        return _t("%(name)s × %(sets)s", { name: program.name, sets });
    }
    return program.name;
}

patch(PosOrder.prototype, {
    getClaimableRewards(coupon_id = false, program_id = false, auto = false) {
        const rewards = super.getClaimableRewards(coupon_id, program_id, auto) || [];
        return rewards.filter(({ reward }) => !_aveaIsComboProgram(reward?.program_id));
    },

    _updateRewardLines() {
        for (const line of [...(this.lines || [])]) {
            if (line.avea_combo_program_id) {
                continue;
            }
            if (line.is_reward_line && !line.reward_id) {
                line.delete();
            }
        }
        return super._updateRewardLines(...arguments);
    },

    _get_reward_lines() {
        const lines = super._get_reward_lines(...arguments) || [];
        return lines.filter((line) => !line.avea_combo_program_id);
    },
});

patch(PosStore.prototype, {
    updateRewards() {
        if (!this.models["loyalty.program"]?.length) {
            this._aveaApplyComboPrices();
            return;
        }
        return super.updateRewards(...arguments);
    },

    async orderUpdateLoyaltyPrograms() {
        const result = await super.orderUpdateLoyaltyPrograms(...arguments);
        this._aveaApplyComboPrices();
        return result;
    },

    _aveaApplyComboPrices() {
        if (this._aveaApplyingComboPrices) {
            return;
        }
        const order = this.getOrder();
        if (!order || order.finalized) {
            return;
        }
        this._aveaApplyingComboPrices = true;
        try {
            this._aveaApplyComboPricesInner(order);
        } finally {
            this._aveaApplyingComboPrices = false;
        }
    },

    _aveaApplyComboPricesInner(order) {
        const programs = (this.models["loyalty.program"]?.getAll?.() || []).filter(
            _aveaIsComboProgram
        );
        _aveaRemoveComboDiscountLines(order);

        for (const program of programs) {
            if (!_aveaComboIsCodeActivated(order, program)) {
                continue;
            }
            if (program.date_from || program.date_to) {
                const now = order.date_order ? new Date(order.date_order) : new Date();
                if (program.date_from) {
                    const start = new Date(program.date_from);
                    start.setHours(0, 0, 0, 0);
                    if (now < start) {
                        continue;
                    }
                }
                if (program.date_to) {
                    const end = new Date(program.date_to);
                    end.setHours(23, 59, 59, 999);
                    if (now > end) {
                        continue;
                    }
                }
            }

            const components = program.avea_combo_components || [];
            const sets = _aveaCountCompleteComboSets(order, components);
            if (sets <= 0) {
                continue;
            }
            const comboTotal = (Number(program.avea_combo_price) || 0) * sets;
            const catalogIncl = (() => {
                const remaining = new Map(
                    components.map((component) => [
                        component.product_id,
                        component.quantity * sets,
                    ])
                );
                let total = 0;
                for (const line of _aveaProductLines(order)) {
                    const productId = line.getProduct?.()?.id || line.product_id?.id;
                    const need = remaining.get(productId) || 0;
                    if (need <= 0) {
                        continue;
                    }
                    const lineQty = Number(line.getQuantity?.() ?? line.qty) || 0;
                    if (lineQty <= 0) {
                        continue;
                    }
                    const take = Math.min(need, lineQty);
                    const lineIncl =
                        Number(line.prices?.total_included ?? line.price_subtotal_incl) || 0;
                    total += (lineIncl / lineQty) * take;
                    remaining.set(productId, need - take);
                }
                return total;
            })();
            const discountIncl = _aveaRoundMoney(order, catalogIncl - comboTotal);
            if (discountIncl <= 0.0001) {
                continue;
            }
            const { parts: taxParts } = _aveaComboDiscountByTax(
                order,
                components,
                sets,
                discountIncl
            );
            if (!taxParts.length) {
                continue;
            }

            const discountProduct = _aveaFindComboDiscountProduct(order, program);
            if (!discountProduct) {
                console.warn("Avea combo discount product missing for", program.name);
                continue;
            }

            const label = _aveaComboLineLabel(program, sets);
            for (const part of taxParts) {
                order.models["pos.order.line"].create({
                    order_id: order,
                    product_id: discountProduct,
                    qty: 1,
                    price_unit: part.priceUnit,
                    price_type: "manual",
                    tax_ids: (part.taxes || []).map((tax) => ["link", tax]),
                    avea_combo_program_id: program.id,
                    is_reward_line: false,
                    full_product_name: label,
                });
            }
        }
    },
});
