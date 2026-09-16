/** @odoo-module **/

import { describe, expect, test } from "@odoo/hoot";
import {
    buildAveaPaymentMethodList,
    normalizePaymentMethodSource,
} from "@avea_till/pos/payment_method_visual";

describe("normalizePaymentMethodSource", () => {
    test("returns an empty array when the source is undefined", () => {
        expect(normalizePaymentMethodSource(undefined)).toEqual([]);
    });

    test("materializes POS relation collections", () => {
        const cash = { id: 1, name: "Cash" };
        const card = { id: 2, name: "Card" };
        const collection = {
            map(fn) {
                return [cash, card].map(fn);
            },
        };
        expect(normalizePaymentMethodSource(collection)).toEqual([cash, card]);
    });
});

describe("buildAveaPaymentMethodList", () => {
    test("returns an empty array when the source is undefined", () => {
        expect(buildAveaPaymentMethodList(undefined)).toEqual([]);
    });

    test("appends store credit when it is missing from the till config", () => {
        const cash = { id: 1, name: "Cash", type: "cash", sequence: 2 };
        const storeCredit = {
            id: 99,
            name: "Store Credit",
            type: "bank",
            is_avea_store_credit: true,
            sequence: 1,
        };
        const methods = buildAveaPaymentMethodList([cash], storeCredit);
        expect(methods.map((method) => method.id)).toEqual([99, 1]);
    });

    test("does not duplicate store credit when it is already configured", () => {
        const storeCredit = {
            id: 99,
            name: "Store Credit",
            type: "bank",
            is_avea_store_credit: true,
            sequence: 1,
        };
        const methods = buildAveaPaymentMethodList([storeCredit], storeCredit);
        expect(methods).toHaveLength(1);
    });
});
