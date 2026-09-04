"""Mirror Combo Price exclusive allocation (DEV) and assert required scenarios.

This reimplements the POS ranking/pool rules from combo_promotions.js so we can
verify competing promotions without driving the browser. Accounting VAT remains
covered by combo_accounting_verify.py.
"""

from collections import defaultdict


def count_sets(components, available):
    sets = None
    for comp in components:
        req = float(comp["quantity"] or 0)
        if req <= 0:
            return 0
        avail = float(available.get(comp["product_id"], 0) or 0)
        fit = int(avail // req)
        sets = fit if sets is None else min(sets, fit)
    return sets or 0


def consume(components, available, sets):
    for comp in components:
        pid = comp["product_id"]
        available[pid] = available.get(pid, 0) - float(comp["quantity"]) * sets


def catalog_one(components, unit_prices):
    total = 0.0
    for comp in components:
        total += unit_prices.get(comp["product_id"], 0.0) * float(comp["quantity"])
    return total


def allocate(programs, cart_qty, unit_prices):
    """programs: list of dicts with id, name, combo_price, components."""
    available = dict(cart_qty)
    ranked = []
    for prog in programs:
        comps = prog["components"]
        saving = catalog_one(comps, unit_prices) - float(prog["combo_price"])
        ranked.append((saving, prog["id"], prog))
    ranked.sort(key=lambda row: (-row[0], row[1]))

    applied = []
    for saving, _pid, prog in ranked:
        sets = count_sets(prog["components"], available)
        if sets <= 0:
            continue
        catalog = catalog_one(prog["components"], unit_prices) * sets
        discount = catalog - float(prog["combo_price"]) * sets
        if discount <= 0.0001:
            continue
        consume(prog["components"], available, sets)
        applied.append(
            {
                "id": prog["id"],
                "name": prog["name"],
                "sets": sets,
                "saving_per_set": saving,
                "discount": discount,
            }
        )
    return applied, available


def assert_eq(label, got, expected):
    if got != expected:
        raise AssertionError(f"{label}: got {got!r}, expected {expected!r}")
    print(f"  OK {label}: {got}")


# --- Synthetic products (generic; not Jock-specific logic) ---
BASE = 100
P_A = 201
P_B = 202
prices = {BASE: 539.0, P_A: 65.0, P_B: 65.0}

promo_a = {
    "id": 12,
    "name": "Base+A",
    "combo_price": 569.0,
    "components": [
        {"product_id": BASE, "quantity": 1},
        {"product_id": P_A, "quantity": 1},
    ],
}
promo_b = {
    "id": 13,
    "name": "Base+B",
    "combo_price": 569.0,
    "components": [
        {"product_id": BASE, "quantity": 1},
        {"product_id": P_B, "quantity": 1},
    ],
}
programs = [promo_a, promo_b]

print("=== ALLOCATION SCENARIOS ===")

# 1 Base + 1 A + 1 B → exactly one combo
applied, rem = allocate(programs, {BASE: 1, P_A: 1, P_B: 1}, prices)
assert_eq("scenario1 applied count", len(applied), 1)
assert_eq("scenario1 sets", applied[0]["sets"], 1)
assert_eq("scenario1 winner is lower id when savings equal", applied[0]["id"], 12)
assert_eq("scenario1 leftover B", rem.get(P_B, 0), 1.0)
assert_eq("scenario1 leftover A", rem.get(P_A, 0), 0.0)
assert_eq("scenario1 leftover Base", rem.get(BASE, 0), 0.0)

# 2 Base + 1 A + 1 B → two combos
applied, rem = allocate(programs, {BASE: 2, P_A: 1, P_B: 1}, prices)
assert_eq("scenario2 applied count", len(applied), 2)
assert_eq("scenario2 total sets", sum(a["sets"] for a in applied), 2)
assert_eq("scenario2 no leftovers", (rem.get(BASE, 0), rem.get(P_A, 0), rem.get(P_B, 0)), (0.0, 0.0, 0.0))

# 2 Base + 2 A + 2 B → two of each combo (4 sets) without double-consume
applied, rem = allocate(programs, {BASE: 2, P_A: 2, P_B: 2}, prices)
# Only 2 Base → at most 2 sets total across both promos
assert_eq("scenario3 total sets capped by Base", sum(a["sets"] for a in applied), 2)
assert_eq("scenario3 Base remaining", rem.get(BASE, 0), 0.0)
# One partner flavour will have leftovers (2 - sets allocated to that promo)
partner_left = rem.get(P_A, 0) + rem.get(P_B, 0)
assert_eq("scenario3 partner leftovers", partner_left, 2.0)

# Multiple copies of same combo: 3 Base + 3 A, only promo_a
applied, rem = allocate([promo_a], {BASE: 3, P_A: 3}, prices)
assert_eq("scenario4 multi same combo sets", applied[0]["sets"], 3)

# Higher saving wins over lower id
promo_rich = {
    "id": 99,
    "name": "Rich",
    "combo_price": 500.0,  # saves 539+65-500 = 104
    "components": [
        {"product_id": BASE, "quantity": 1},
        {"product_id": P_A, "quantity": 1},
    ],
}
promo_poor = {
    "id": 1,
    "name": "Poor",
    "combo_price": 590.0,  # saves 14
    "components": [
        {"product_id": BASE, "quantity": 1},
        {"product_id": P_A, "quantity": 1},
    ],
}
applied, rem = allocate([promo_poor, promo_rich], {BASE: 1, P_A: 1}, prices)
assert_eq("scenario5 higher saving wins", applied[0]["id"], 99)

print("\n=== DEV DB: mirror live Jock/Cuthbert program data if present ===")
Promo = env["avea.promotion"]  # noqa: F821
promos = Promo.search(
    [("deal_type", "=", "combo_price"), ("active", "=", True), ("name", "ilike", "Jock")],
    order="id",
)
if len(promos) >= 2:
    live_programs = []
    unit_prices = {}
    for p in promos[:2]:
        comps = []
        for line in p.combo_line_ids:
            comps.append({"product_id": line.product_id.id, "quantity": line.quantity})
            unit_prices[line.product_id.id] = line.product_id.lst_price
        live_programs.append(
            {
                "id": p.program_id.id,
                "name": p.name,
                "combo_price": p.combo_price,
                "components": comps,
            }
        )
    base_id = None
    partners = []
    for comp in live_programs[0]["components"]:
        # shared product appears in both
        in_both = all(
            any(c["product_id"] == comp["product_id"] for c in prog["components"])
            for prog in live_programs
        )
        if in_both:
            base_id = comp["product_id"]
        else:
            partners.append(comp["product_id"])
    for comp in live_programs[1]["components"]:
        if comp["product_id"] != base_id:
            partners.append(comp["product_id"])
    partners = partners[:2]
    cart = {base_id: 1, partners[0]: 1, partners[1]: 1}
    applied, rem = allocate(live_programs, cart, unit_prices)
    print(f"  Live cart {cart}")
    print(f"  Applied: {[(a['name'], a['sets']) for a in applied]}")
    assert_eq("live 1+1+1 applied count", len(applied), 1)
    assert_eq("live 1+1+1 total sets", sum(a["sets"] for a in applied), 1)
else:
    print("  (no Jock combo promos on this DB — synthetic tests only)")

print("\nALL ALLOCATION CHECKS PASSED")
