/** @odoo-module **/

import { FormController } from "@web/views/form/form_controller";
import { formView } from "@web/views/form/form_view";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { useEffect } from "@odoo/owl";
import { patch } from "@web/core/utils/patch";
import { ViewButton } from "@web/views/view_button/view_button";

const PRICING_BUTTON = "action_open_pricing_wizard";
const ADD_UNMATCHED_BUTTON = "action_add_to_receive";

let _aveaReceiveButtonBusy = false;

function _aveaReceiveRoot(record) {
    const root = record?.model?.root;
    return root?.resModel === "avea.stock.receive" ? root : null;
}

/** Odoo 19 many2one values are {id, display_name}. Older data used [id, name]. */
function _aveaM2oId(value) {
    if (!value) {
        return null;
    }
    if (Array.isArray(value)) {
        return value[0] || null;
    }
    if (typeof value === "number") {
        return value;
    }
    return value.id || null;
}

function _aveaSameCost(left, right) {
    return Math.abs((left || 0) - (right || 0)) < 0.00005;
}

function _aveaNotify(env, message) {
    env.services.notification?.add(message, { type: "danger" });
}

async function _aveaSaveReceive(root, lineRecord) {
    if (!root.resId || lineRecord?.isNew || (await root.isDirty())) {
        return Boolean(await root.save());
    }
    return true;
}

function _aveaFindReceiveLine(root, productId, priceUnit) {
    const lines = root.data?.line_ids?.records || [];
    if (!productId) {
        return null;
    }
    const matches = lines.filter(
        (line) => _aveaM2oId(line.data?.product_id) === productId
    );
    if (!matches.length) {
        return null;
    }
    if (typeof priceUnit === "number") {
        const exact = matches.find((line) =>
            _aveaSameCost(line.data.price_unit, priceUnit)
        );
        if (exact?.resId) {
            return exact;
        }
    }
    return matches.find((line) => line.resId) || matches[matches.length - 1];
}

function _aveaFindUnmatchedLine(root, snapshot) {
    let matches = (root.data?.unmatched_line_ids?.records || []).filter(
        (line) => (line.data?.description || "") === snapshot.description
    );
    if (!matches.length) {
        return null;
    }
    if (typeof snapshot.priceUnit === "number") {
        const priced = matches.filter((line) =>
            _aveaSameCost(line.data.price_unit, snapshot.priceUnit)
        );
        if (priced.length) {
            matches = priced;
        }
    }
    if (snapshot.productId) {
        const withProduct = matches.filter(
            (line) => _aveaM2oId(line.data?.product_id) === snapshot.productId
        );
        if (withProduct.length) {
            matches = withProduct;
        }
    }
    return matches.find((line) => line.resId) || null;
}

async function _aveaOpenPricingWizard(env, lineRecord) {
    const root = _aveaReceiveRoot(lineRecord);
    if (!root || _aveaReceiveButtonBusy) {
        return false;
    }
    _aveaReceiveButtonBusy = true;
    try {
        if (typeof root.isDirty === "function") {
            await root.isDirty();
        }
        const data = lineRecord.data || {};
        const productId = _aveaM2oId(data.product_id);
        const priceUnit = data.price_unit;
        if (!productId) {
            _aveaNotify(env, "Choose a product first.");
            return false;
        }
        if (!(await _aveaSaveReceive(root, lineRecord))) {
            return false;
        }
        await root.load();
        const persisted = _aveaFindReceiveLine(root, productId, priceUnit);
        if (!persisted?.resId) {
            _aveaNotify(env, "Could not open pricing for this line. Try again.");
            return false;
        }
        const action = await env.services.orm.call(
            "avea.stock.receive.line",
            PRICING_BUTTON,
            [[persisted.resId]]
        );
        if (!action) {
            return false;
        }
        await env.services.action.doAction(action, {
            onClose: async () => {
                try {
                    await root.load();
                } catch (_e) {
                    // ignore reload errors after dialog close
                }
            },
        });
        return true;
    } finally {
        _aveaReceiveButtonBusy = false;
    }
}

async function _aveaAddUnmatchedLine(env, lineRecord) {
    const root = _aveaReceiveRoot(lineRecord);
    if (!root || _aveaReceiveButtonBusy) {
        return false;
    }
    _aveaReceiveButtonBusy = true;
    try {
        if (typeof root.isDirty === "function") {
            await root.isDirty();
        }
        const data = lineRecord.data || {};
        const snapshot = {
            description: data.description || "",
            priceUnit: data.price_unit,
            productId: _aveaM2oId(data.product_id),
        };
        if (!snapshot.productId) {
            _aveaNotify(env, "Choose the product that matches this invoice line.");
            return false;
        }
        if (!(await _aveaSaveReceive(root, lineRecord))) {
            return false;
        }
        await root.load();
        const persisted = _aveaFindUnmatchedLine(root, snapshot);
        if (!persisted?.resId) {
            _aveaNotify(env, "Could not add this line. Try again.");
            return false;
        }
        await env.services.orm.call(
            "avea.stock.receive.unmatched",
            ADD_UNMATCHED_BUTTON,
            [[persisted.resId]]
        );
        await root.load();
        return true;
    } finally {
        _aveaReceiveButtonBusy = false;
    }
}

/**
 * Editable x2many rows block object buttons until the parent is saved
 * ("Please save your changes first"). Invoice reading fills those rows
 * without saving, so Add and Pricing save the receive, then run.
 */
patch(ViewButton.prototype, {
    async onClick(ev, newWindow) {
        const name = this.clickParams?.name;
        const record = this.props.record;
        const receiveRoot = _aveaReceiveRoot(record);
        if (name === PRICING_BUTTON && receiveRoot) {
            ev?.preventDefault?.();
            ev?.stopPropagation?.();
            await _aveaOpenPricingWizard(this.env, record);
            return;
        }
        if (
            name === ADD_UNMATCHED_BUTTON &&
            receiveRoot &&
            record?.resModel === "avea.stock.receive.unmatched"
        ) {
            ev?.preventDefault?.();
            ev?.stopPropagation?.();
            await _aveaAddUnmatchedLine(this.env, record);
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
        if (root.resId && !(await root.isDirty())) {
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
            const productId = _aveaM2oId(data.product_id);
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
