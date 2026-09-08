/** @odoo-module **/

import { FormController } from "@web/views/form/form_controller";
import { formView } from "@web/views/form/form_view";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { useEffect } from "@odoo/owl";
import { patch } from "@web/core/utils/patch";
import { ViewButton } from "@web/views/view_button/view_button";

const PRICING_BUTTON = "action_open_pricing_wizard";

function _aveaReceiveRoot(record) {
    const root = record?.model?.root;
    return root?.resModel === "avea.stock.receive" ? root : null;
}

function _aveaFindReceiveLine(root, productId, priceUnit) {
    const lines = root.data?.line_ids?.records || [];
    if (!productId) {
        return null;
    }
    const matches = lines.filter(
        (line) => line.data?.product_id?.[0] === productId
    );
    if (!matches.length) {
        return null;
    }
    if (typeof priceUnit === "number") {
        const exact = matches.find(
            (line) => Math.abs((line.data.price_unit || 0) - priceUnit) < 0.00005
        );
        if (exact?.resId) {
            return exact;
        }
    }
    return matches.find((line) => line.resId) || matches[matches.length - 1];
}

async function _aveaOpenPricingWizard(env, lineRecord) {
    const root = _aveaReceiveRoot(lineRecord);
    if (!root) {
        return false;
    }
    const orm = env.services.orm;
    const actionService = env.services.action;
    const data = lineRecord.data || {};
    const productId = data.product_id?.[0];
    const priceUnit = data.price_unit;
    if (!productId) {
        return false;
    }
    if (root.isDirty && !(await root.save())) {
        return false;
    }
    await root.load();
    const persisted = _aveaFindReceiveLine(root, productId, priceUnit);
    if (!persisted?.resId) {
        return false;
    }
    const action = await orm.call(
        "avea.stock.receive.line",
        PRICING_BUTTON,
        [[persisted.resId]]
    );
    if (!action) {
        return false;
    }
    await actionService.doAction(action, {
        onClose: async () => {
            try {
                await root.load();
            } catch (_e) {
                // ignore reload errors after dialog close
            }
        },
    });
    return true;
}

/**
 * Odoo blocks object buttons on unsaved x2many rows ("Please save your changes first").
 * Intercept the Receive Stock pricing button and save the receive form first.
 */
patch(ViewButton.prototype, {
    async onClick(ev, newWindow) {
        if (
            this.props.onClick &&
            this.clickParams?.name === PRICING_BUTTON &&
            this.props.record?.isNew &&
            _aveaReceiveRoot(this.props.record)
        ) {
            ev?.preventDefault?.();
            ev?.stopPropagation?.();
            await _aveaOpenPricingWizard(this.env, this.props.record);
            return;
        }
        return super.onClick(ev, newWindow);
    },
});

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
        if (clickParams.name === PRICING_BUTTON) {
            if (!(await this._aveaEnsureReceiveSaved())) {
                return false;
            }
        }
        const saved = await super.beforeExecuteActionButton(clickParams);
        if (saved !== false && clickParams.name === PRICING_BUTTON) {
            await this.model.root.load();
        }
        return saved;
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
            let opened = false;
            try {
                await record.update({ avea_open_pricing_wizard: false });
                opened = await _aveaOpenPricingWizard(this.env, record);
                if (!opened) {
                    this._aveaOpenedLineIds.delete(lineKey);
                }
            } catch (_err) {
                this._aveaOpenedLineIds.delete(lineKey);
            } finally {
                this._aveaPricingBusy = false;
            }
            if (opened) {
                return;
            }
        }
    }
}

registry.category("views").add("avea_stock_receive_form", {
    ...formView,
    Controller: AveaStockReceiveFormController,
});
