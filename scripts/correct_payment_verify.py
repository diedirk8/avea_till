"""DEV verification for Correct Payment eligibility and corrections."""
from collections import defaultdict

admin = env.ref("base.user_admin")  # noqa: F821
env = env(user=admin)  # noqa: F821
Order = env["pos.order"]
Session = env["pos.session"]

open_sessions = Session.search([("state", "=", "opened")])
orders = Order.search(
    [
        ("session_id", "in", open_sessions.ids),
        ("state", "in", ("paid", "done", "invoiced")),
    ],
    order="id desc",
    limit=100,
)
print(f"=== OPEN-SESSION ORDERS: {len(orders)} ===")
by_reason = defaultdict(list)
allowed = []
for o in orders:
    tenders = o._avea_non_change_payments()
    methods = tenders.mapped("payment_method_id")
    change = o._avea_change_payments()
    block = o._avea_payment_correction_block_reason()
    row = {
        "id": o.id,
        "ref": o.pos_reference or o.name,
        "state": o.state,
        "total": o.amount_total,
        "partner": o.partner_id.name or "(walk-in)",
        "methods": [(m.name, m._avea_tender_kind()) for m in methods],
        "change_lines": len(change),
        "invoice": bool(o.account_move),
        "block": block or "",
    }
    by_reason[block or "ALLOWED"].append(row)
    if not block:
        allowed.append(row)

print("\n--- Eligibility summary ---")
for reason, rows in sorted(by_reason.items(), key=lambda x: (-len(x[1]), x[0])):
    print(f"{len(rows):3d}  {reason}")

print("\n--- ALLOWED ---")
for r in allowed:
    print(
        f"  #{r['id']} {r['ref']} total={r['total']} partner={r['partner']} "
        f"methods={r['methods']} change={r['change_lines']}"
    )

print("\n=== CORRECTION TESTS (rollback) ===")
cr = env.cr


def pick_target(order, current, prefer=None):
    targets = order._avea_open_session_correction_methods().filtered(
        lambda m: m.id != current.id
    )
    if prefer:
        preferred = targets.filtered(lambda m: m._avea_tender_kind() == prefer)
        if preferred:
            return preferred[:1]
    kind = current._avea_tender_kind()
    if kind == "cash":
        preferred = targets.filtered(lambda m: m._avea_tender_kind() in ("card", "eft"))
    else:
        preferred = targets.filtered(lambda m: m._avea_tender_kind() == "cash")
    return (preferred[:1] or targets[:1])


# Focus on newly created + existing allowed
focus_ids = [r["id"] for r in allowed]
pairs = [
    # (order_id or None for all allowed), prefer target kind
    (None, None),
]

# Explicit matrix on newest test orders if present
for oid, prefer in [
    (1643, "card"),  # cash exact -> card
    (1643, "eft"),  # cash exact -> eft
    (1644, "card"),  # cash+change -> card
    (1645, "cash"),  # card -> cash
    (1646, "cash"),  # eft -> cash
    (1634, "card"),  # prior real cash order
]:
    if Order.browse(oid).exists() and not Order.browse(oid)._avea_payment_correction_block_reason():
        pairs.append((oid, prefer))

tested = 0
failures = 0
seen = set()
for oid, prefer in pairs:
    ids = [oid] if oid else focus_ids
    for order_id in ids:
        key = (order_id, prefer)
        if key in seen:
            continue
        seen.add(key)
        order = Order.browse(order_id)
        if not order.exists():
            continue
        if order._avea_payment_correction_block_reason():
            continue
        tender = order._avea_correctable_tender()
        current = tender.payment_method_id
        target = pick_target(order, current, prefer=prefer)
        if not target:
            print(f"  SKIP #{order.id}: no target")
            continue
        cr.execute("SAVEPOINT avea_correct_test")
        try:
            before = [(p.payment_method_id.name, p.amount, p.is_change) for p in order.payment_ids]
            before_mov = order._avea_till_find_cash_movements()
            cash_before = order.session_id.cash_register_balance_end or 0.0
            opts = order.avea_get_payment_correction_options()
            assert not opts["blocked"], opts
            assert opts["methods"], "no replacement methods returned"
            result = order.avea_correct_payment_method(
                target.id, f"Cursor verify {current.name}->{target.name}"
            )
            order.invalidate_recordset()
            order.session_id.invalidate_recordset()
            after = [(p.payment_method_id.name, p.amount, p.is_change) for p in order.payment_ids]
            after_mov = order._avea_till_find_cash_movements()
            cash_after = order.session_id.cash_register_balance_end or 0.0
            msgs = order.message_ids.filtered(
                lambda m: m.body and "Corrected payment method" in (m.body or "")
            )
            tender2 = order._avea_correctable_tender()
            ok = (
                result.get("successful")
                and len(order._avea_non_change_payments()) == 1
                and not order._avea_change_payments()
                and tender2.payment_method_id.id == target.id
                and abs(tender2.amount - order.amount_total) < 0.01
                and bool(msgs)
            )
            if target._avea_tender_kind() == "cash":
                ok = ok and bool(after_mov)
            else:
                ok = ok and not after_mov
            # Empty reason rejected
            try:
                # already corrected once — block may still allow same session re-correct
                pass
            except Exception:
                pass
            status = "OK" if ok else "FAIL"
            if not ok:
                failures += 1
            print(
                f"  {status} #{order.id} {current.name}->{target.name} "
                f"total={order.amount_total} {before} -> {after} "
                f"cash {cash_before}->{cash_after} "
                f"movements={len(before_mov)}->{len(after_mov)} audit={bool(msgs)}"
            )
            tested += 1
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"  FAIL #{order.id} EXCEPTION: {exc}")
        finally:
            cr.execute("ROLLBACK TO SAVEPOINT avea_correct_test")
            env.clear()
            Order = env["pos.order"]

# Reason required
print("\n=== REASON REQUIRED ===")
order = Order.browse(allowed[0]["id"]) if allowed else Order.browse()
if order:
    cr.execute("SAVEPOINT avea_reason")
    try:
        target = pick_target(order, order._avea_correctable_tender().payment_method_id)
        order.avea_correct_payment_method(target.id, "   ")
        print("  FAIL: empty reason accepted")
        failures += 1
    except Exception as exc:  # noqa: BLE001
        print(f"  OK empty reason rejected: {exc}")
    finally:
        cr.execute("ROLLBACK TO SAVEPOINT avea_reason")
        env.clear()
        Order = env["pos.order"]

print("\n=== REJECTION TESTS ===")
for reason_key, rows in by_reason.items():
    if reason_key == "ALLOWED":
        continue
    sample = rows[0]
    order = Order.browse(sample["id"])
    opts = order.avea_get_payment_correction_options()
    print(f"  blocked={opts.get('blocked')} #{order.id}: {opts.get('block_reason','')[:90]}")
    methods = order.session_id.config_id.payment_method_ids.filtered(
        lambda m: m._avea_is_open_session_correctable_tender()
    )
    if methods:
        cr.execute("SAVEPOINT avea_reject_test")
        try:
            order.avea_correct_payment_method(methods[0].id, "should fail")
            print(f"  UNEXPECTED SUCCESS on #{order.id}")
            failures += 1
        except Exception as exc:  # noqa: BLE001
            print(f"  correctly rejected #{order.id}: {str(exc)[:90]}")
        finally:
            cr.execute("ROLLBACK TO SAVEPOINT avea_reject_test")
            env.clear()
            Order = env["pos.order"]

closed = Order.search(
    [("session_id.state", "!=", "opened"), ("state", "in", ("paid", "done"))],
    order="id desc",
    limit=1,
)
if closed:
    print(f"\nClosed session #{closed.id}: {closed._avea_payment_correction_block_reason()}")

print(f"\nRESULT tested={tested} failures={failures}")
print("DONE")
