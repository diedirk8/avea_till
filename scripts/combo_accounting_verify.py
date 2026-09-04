#!/usr/bin/env python3
"""DEV-only Combo Price accounting verification. Run via odoo shell stdin."""
from odoo import Command
from odoo.tools import float_compare, float_is_zero, float_round

company = env.company
currency = company.currency_id
promo = env["avea.promotion"].search([("name", "=", "Cursor Combo Price Test")], limit=1)
assert promo, "Combo test promo missing"
p1 = promo.combo_line_ids[0].product_id
p2 = promo.combo_line_ids[1].product_id
disc_product = promo.program_id.reward_ids.discount_line_product_id[:1]
assert disc_product, "Discount product missing"
combo_price = promo.combo_price
tax15 = p1.taxes_id[:1]
assert tax15, "Product tax missing"
disc_incl_one = currency.round(p1.lst_price + p2.lst_price - combo_price)

main = env["pos.config"].search([("name", "ilike", "Till 1")], limit=1)
Journal = env["account.journal"]
cash_journal = Journal.search([("code", "=", "ACBTC"), ("company_id", "=", company.id)], limit=1)
if not cash_journal:
    cash_journal = Journal.create(
        {
            "name": "Avea Combo Test Cash",
            "code": "ACBTC",
            "type": "cash",
            "company_id": company.id,
        }
    )
PM = env["pos.payment.method"]
pm = PM.search([("name", "=", "Avea Combo Test Cash"), ("company_id", "=", company.id)], limit=1)
if not pm:
    pm = PM.create(
        {
            "name": "Avea Combo Test Cash",
            "journal_id": cash_journal.id,
            "company_id": company.id,
        }
    )

Config = env["pos.config"]
config = Config.search([("name", "=", "Avea Combo Accounting Test")], limit=1)
if not config:
    config = Config.create(
        {
            "name": "Avea Combo Accounting Test",
            "journal_id": main.journal_id.id,
            "invoice_journal_id": main.invoice_journal_id.id if main.invoice_journal_id else False,
            "payment_method_ids": [Command.set(pm.ids)],
            "module_pos_hr": False,
        }
    )
else:
    config.write({"payment_method_ids": [Command.set(pm.ids)]})

# Close leftover open session on test till only
if config.current_session_id and config.current_session_id.state != "closed":
    sess = config.current_session_id
    if sess.order_ids.filtered(lambda o: o.state != "cancel"):
        # Force-cancel unpaid drafts only; paid orders block — abort
        unpaid = sess.order_ids.filtered(lambda o: o.state == "draft")
        unpaid.write({"state": "cancel"})
    if sess.order_ids.filtered(lambda o: o.state in ("paid", "done", "invoiced")):
        raise SystemExit("Test session already has paid orders; close manually first")
    sess.action_pos_session_closing_control()

session = env["pos.session"].create({"user_id": env.uid, "config_id": config.id})
session.action_pos_session_open()
if session.state == "opening_control":
    session.action_pos_session_open()
print("SESSION", session.name, session.state)


def line_amounts(product, qty, price_unit, taxes):
    price = price_unit
    if taxes:
        taxes_res = taxes.compute_all(
            price, currency, qty, product=product, partner=False
        )
        return taxes_res["total_excluded"], taxes_res["total_included"]
    return price * qty, price * qty


def make_order(label, *, multi=1, leftover=False, with_tax_on_discount=True, refund_of=None):
    lines_cmds = []
    if refund_of:
        for src in refund_of.lines:
            sub, incl = line_amounts(src.product_id, -src.qty, src.price_unit, src.tax_ids)
            lines_cmds.append(
                Command.create(
                    {
                        "product_id": src.product_id.id,
                        "qty": -src.qty,
                        "price_unit": src.price_unit,
                        "tax_ids": [Command.set(src.tax_ids.ids)],
                        "price_type": "manual",
                        "price_subtotal": sub,
                        "price_subtotal_incl": incl,
                        "full_product_name": src.full_product_name,
                        "avea_combo_program_id": src.avea_combo_program_id,
                        "is_reward_line": False,
                    }
                )
            )
    else:
        for _ in range(multi):
            for product in (p1, p2):
                sub, incl = line_amounts(product, 1, product.lst_price, product.taxes_id)
                lines_cmds.append(
                    Command.create(
                        {
                            "product_id": product.id,
                            "qty": 1,
                            "price_unit": product.lst_price,
                            "tax_ids": [Command.set(product.taxes_id.ids)],
                            "price_type": "manual",
                            "price_subtotal": sub,
                            "price_subtotal_incl": incl,
                        }
                    )
                )
        if leftover:
            sub, incl = line_amounts(p1, 1, p1.lst_price, p1.taxes_id)
            lines_cmds.append(
                Command.create(
                    {
                        "product_id": p1.id,
                        "qty": 1,
                        "price_unit": p1.lst_price,
                        "tax_ids": [Command.set(p1.taxes_id.ids)],
                        "price_type": "manual",
                        "price_subtotal": sub,
                        "price_subtotal_incl": incl,
                    }
                )
            )
        disc_taxes = tax15 if with_tax_on_discount else env["account.tax"]
        disc_amount = -currency.round(disc_incl_one * multi)
        sub, incl = line_amounts(disc_product, 1, disc_amount, disc_taxes)
        lines_cmds.append(
            Command.create(
                {
                    "product_id": disc_product.id,
                    "qty": 1,
                    "price_unit": disc_amount,
                    "tax_ids": [Command.set(disc_taxes.ids)] if disc_taxes else False,
                    "price_type": "manual",
                    "price_subtotal": sub,
                    "price_subtotal_incl": incl,
                    "full_product_name": f"{promo.name} × {multi}" if multi > 1 else promo.name,
                    "avea_combo_program_id": promo.program_id.id,
                    "is_reward_line": False,
                }
            )
        )

    order = env["pos.order"].create(
        {
            "session_id": session.id,
            "config_id": config.id,
            "company_id": company.id,
            "amount_tax": 0,
            "amount_total": 0,
            "amount_paid": 0,
            "amount_return": 0,
            "lines": lines_cmds,
        }
    )
    amount_total = sum(order.lines.mapped("price_subtotal_incl"))
    amount_tax = sum(l.price_subtotal_incl - l.price_subtotal for l in order.lines)
    order.write({"amount_total": amount_total, "amount_tax": amount_tax, "amount_paid": amount_total})
    env["pos.payment"].create(
        {
            "pos_order_id": order.id,
            "amount": amount_total,
            "payment_method_id": pm.id,
            "session_id": session.id,
        }
    )
    order.action_pos_order_paid()
    print(f"\n=== {label} {order.name} total={order.amount_total} tax={order.amount_tax} ===")
    for l in order.lines:
        print(
            f"  {l.full_product_name!r} qty={l.qty} pu={l.price_unit} "
            f"sub={l.price_subtotal} incl={l.price_subtotal_incl} "
            f"taxes={l.tax_ids.mapped('name')} type={l.product_id.type} "
            f"combo={bool(l.avea_combo_program_id)} cost={l.total_cost}"
        )
    return order


order_fixed = make_order("FIXED_1", multi=1, leftover=False, with_tax_on_discount=True)
order_multi = make_order("MULTI_2", multi=2, leftover=False, with_tax_on_discount=True)
order_left = make_order("LEFTOVER", multi=1, leftover=True, with_tax_on_discount=True)
order_broken = make_order("BROKEN_NO_TAX", multi=1, leftover=False, with_tax_on_discount=False)
order_refund = make_order("REFUND", refund_of=order_fixed)

# Costs / stock: compute costs at session closing
session._compute_total_cost_at_session_closing() if hasattr(session, "_compute_total_cost_at_session_closing") else None
for order in (order_fixed, order_multi, order_left, order_broken, order_refund):
    order.lines._compute_total_cost(env["stock.move"])
    print(f"\nCOSTS {order.name}:")
    for l in order.lines:
        print(f"  {l.product_id.display_name}: total_cost={l.total_cost} type={l.product_id.type}")

# Close session -> create accounting move
print("\nClosing session...")
session.action_pos_session_closing_control()
session.invalidate_recordset()
move = session.move_id
print("MOVE", move.name, move.state, "amount", move.amount_total)

print("\nJOURNAL LINES:")
sales_credit = 0.0
tax_credit = 0.0
cogs_debit = 0.0
stock_credit = 0.0
for aml in move.line_ids.sorted(lambda l: (l.account_id.code or "", l.debit, l.credit)):
    print(
        f"  {aml.account_id.code} {aml.account_id.name} | {aml.name!r} | "
        f"D={aml.debit} C={aml.credit} tax={aml.tax_ids.mapped('name')} "
        f"product={aml.product_id.display_name or ''}"
    )
    code = aml.account_id.code or ""
    if code.startswith("500"):
        sales_credit += aml.credit - aml.debit
    if "Tax" in (aml.account_id.name or "") or code.startswith("200"):
        tax_credit += aml.credit - aml.debit
    if code.startswith("600"):
        cogs_debit += aml.debit - aml.credit
    if "Stock" in (aml.account_id.name or "") or code.startswith("1"):
        pass

# Expectations for FIXED order alone (also others in same move — analyse order-level)
print("\n--- ORDER-LEVEL CHECKS ---")

def check_order(order, expected_total, note):
    ok_total = float_is_zero(order.amount_total - expected_total, precision_rounding=currency.rounding)
    # VAT should be close to included-total * 15/115 when all lines share 15%
    expected_tax = currency.round(order.amount_total - (order.amount_total / 1.15))
    # For mixed broken order this will fail intentionally
    tax_diff = abs(order.amount_tax - expected_tax)
    print(
        f"{note}: total={order.amount_total} (expect {expected_total}, ok={ok_total}) "
        f"tax={order.amount_tax} (~{expected_tax} if fully 15% taxed, diff={tax_diff:.4f})"
    )
    # Discount line must not create COGS
    for l in order.lines.filtered("avea_combo_program_id"):
        assert float_is_zero(l.total_cost or 0.0, precision_rounding=currency.rounding), "Discount must not affect COGS"
        assert l.product_id.type == "service"
    # Product costs should equal qty * standard-ish cost (AVCO may differ) — just ensure non-zero for stockables
    for l in order.lines.filtered(lambda x: x.product_id.type in ("product", "consu") and not x.avea_combo_program_id):
        print(f"  stock line cost {l.product_id.display_name}: {l.total_cost} (std={l.product_id.standard_price})")

check_order(order_fixed, combo_price, "FIXED")
check_order(order_multi, combo_price * 2, "MULTI")
check_order(order_left, combo_price + p1.lst_price, "LEFTOVER")
check_order(order_broken, combo_price, "BROKEN")
check_order(order_refund, -combo_price, "REFUND")

print("\nNet session cash should be FIXED+MULTI+LEFTOVER+BROKEN+REFUND =",
      order_fixed.amount_total + order_multi.amount_total + order_left.amount_total + order_broken.amount_total + order_refund.amount_total)

# Compare tax of FIXED vs BROKEN
print("\nTAX COMPARISON (same sale, tax on discount vs not):")
print(f"  FIXED tax={order_fixed.amount_tax}")
print(f"  BROKEN tax={order_broken.amount_tax}")
print(f"  Diff (broken overstates VAT by)={order_broken.amount_tax - order_fixed.amount_tax}")

# Deactivate test till so it does not clutter UI
config.write({"active": False})
env.cr.commit()
print("\nDONE — test config deactivated; session closed and posted.")
