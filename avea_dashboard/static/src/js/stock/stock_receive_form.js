/** @odoo-module **/

import { FormController } from "@web/views/form/form_controller";
import { formView } from "@web/views/form/form_view";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { useEffect } from "@odoo/owl";

/**
 * Receive Stock form: pricing popup after cost changes, and save-before-pricing.
 */
export class AveaStockReceiveFormController extends FormController {
    setup() {
        super.setup();
        this.orm = useService("orm");
        this.action = useService("action");
        this._aveaPricingBusy = false;
        this._aveaOpenedLineIds = new Set();

        useEffect(() => {
            this._aveaMaybeOpenPricingWizard();
        });
    }

    async beforeExecuteActionButton(clickParams) {
        const saved = await super.beforeExecuteActionButton(clickParams);
        if (saved !== false && clickParams.name === "action_open_pricing_wizard") {
            await this.model.root.load();
        }
        return saved;
    }

    _aveaFindReceiveLine(productId, priceUnit) {
        const lines = this.model.root.data?.line_ids?.records || [];
        if (!productId) {
            return null;
        }
        const matches = lines.filter(
            (record) => record.data?.product_id?.[0] === productId
        );
        if (!matches.length) {
            return null;
        }
        if (typeof priceUnit === "number") {
            const exact = matches.find(
                (record) => Math.abs((record.data.price_unit || 0) - priceUnit) < 0.005
            );
            if (exact?.resId) {
                return exact;
            }
        }
        return matches.find((record) => record.resId) || matches[matches.length - 1];
    }

    async _aveaEnsureReceiveSaved() {
        const root = this.model.root;
        if (!root.isDirty) {
            return true;
        }
        return Boolean(await root.save());
    }

    async _aveaMaybeOpenPricingWizard() {
        if (this._aveaPricingBusy) {
            return;
        }
        const root = this.model?.root;
        if (!root || root.resModel !== "avea.stock.receive") {
            return;
        }
        const lines = root.data?.line_ids?.records || [];
        for (const record of lines) {
            const data = record.data || {};
            const productId = data.product_id?.[0];
            const priceUnit = data.price_unit;
            if (!productId || !data.avea_open_pricing_wizard) {
                continue;
            }
            const lineKey = record.resId || `new-${productId}-${priceUnit}`;
            if (this._aveaOpenedLineIds.has(lineKey)) {
                continue;
            }
            this._aveaPricingBusy = true;
            this._aveaOpenedLineIds.add(lineKey);
            try {
                await record.update({ avea_open_pricing_wizard: false });
                if (!(await this._aveaEnsureReceiveSaved())) {
                    this._aveaOpenedLineIds.delete(lineKey);
                    this._aveaPricingBusy = false;
                    continue;
                }
                await root.load();
                const persisted = this._aveaFindReceiveLine(productId, priceUnit);
                if (!persisted?.resId) {
                    this._aveaOpenedLineIds.delete(lineKey);
                    this._aveaPricingBusy = false;
                    continue;
                }
                const action = await this.orm.call(
                    "avea.stock.receive.line",
                    "action_open_pricing_wizard",
                    [[persisted.resId]]
                );
                if (action) {
                    await this.action.doAction(action, {
                        onClose: async () => {
                            try {
                                await this.model.root.load();
                            } catch (_e) {
                                // ignore reload errors after dialog close
                            }
                            this._aveaPricingBusy = false;
                        },
                    });
                    return;
                }
            } catch (_err) {
                this._aveaOpenedLineIds.delete(lineKey);
                this._aveaPricingBusy = false;
            }
        }
    }
}

registry.category("views").add("avea_stock_receive_form", {
    ...formView,
    Controller: AveaStockReceiveFormController,
});
