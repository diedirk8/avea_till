/** @odoo-module **/

import { describe, expect, test } from "@odoo/hoot";
import { getStoreCreditPaymentMethod } from "@avea_till/pos/store_credit";

describe("getStoreCreditPaymentMethod", () => {
    test("does not throw when config payment methods are missing", () => {
        const pos = {
            config: {
                avea_credit_enabled: true,
                payment_method_ids: undefined,
            },
            models: {
                "pos.payment.method": {
                    getAll() {
                        return [
                            {
                                id: 99,
                                name: "Store Credit",
                                is_avea_store_credit: true,
                            },
                        ];
                    },
                },
            },
        };
        expect(getStoreCreditPaymentMethod(pos)?.id).toBe(99);
    });
});
