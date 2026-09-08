/** @odoo-module **/

import { FormController } from "@web/views/form/form_controller";
import { formView } from "@web/views/form/form_view";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { useEffect } from "@odoo/owl";

/**
 * When a receive line's EX-tax cost differs from the product cost, open the
 * compact Avea pricing popup (once per pending line).
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
            const lineId = record.resId;
            if (!lineId || !data.avea_open_pricing_wizard) {
                continue;
            }
            if (this._aveaOpenedLineIds.has(lineId)) {
                continue;
            }
            this._aveaPricingBusy = true;
            this._aveaOpenedLineIds.add(lineId);
            try {
                await record.update({ avea_open_pricing_wizard: false });
                const action = await this.orm.call(
                    "avea.stock.receive.line",
                    "action_open_pricing_wizard",
                    [[lineId]]
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
                this._aveaOpenedLineIds.delete(lineId);
                this._aveaPricingBusy = false;
            }
        }
    }
}

registry.category("views").add("avea_stock_receive_form", {
    ...formView,
    Controller: AveaStockReceiveFormController,
});
