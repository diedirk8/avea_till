#!/usr/bin/env python3
"""Manual POS receipt-email QA on DEV.

Run inside Odoo shell (rolls back at the end — no data or SMTP kept):

    docker exec -i odoo-dev odoo shell -d petsempire_dev --no-http < scripts/pos_receipt_email_qa.py

Uses only synthetic @dev.local customers. Mail delivery is patched off.
"""
from __future__ import annotations

import traceback
import uuid
from unittest.mock import patch

from odoo import fields

# noqa: F821 — env is provided by odoo shell
PosOrder = env["pos.order"]
Partner = env["res.partner"]
Company = env["res.company"].search([], limit=1)
Config = env["pos.config"].search([("active", "=", True)], limit=1)
Session = env["pos.session"].search(
    [("state", "=", "opened"), ("config_id", "=", Config.id)],
    limit=1,
)
Product = env["product.product"].search(
    [("sale_ok", "=", True), ("available_in_pos", "=", True)],
    limit=1,
)
CashPm = Config.payment_method_ids.filtered(lambda pm: pm.is_cash_count)[:1]
if not CashPm:
    CashPm = Config.payment_method_ids[:1]

if not Session:
    raise SystemExit("No open POS session on DEV — open Pets Empire Till 1 first.")

TEST_PREFIX = "POS Receipt QA"
results = []


def log(scenario, ok, detail=""):
    results.append((scenario, ok, detail))
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] {scenario}: {detail}")


def make_partner(name, email=None):
    vals = {"name": f"{TEST_PREFIX} {name}"}
    if email is not None:
        vals["email"] = email
    return Partner.create(vals)


def create_paid_order(partner=None, tag="qa", is_invoiced=False):
    uid = f"{tag}-{uuid.uuid4().hex[:8]}"
    fiscal_position = (
        partner.property_account_position_id
        if partner
        else Config.default_fiscal_position_id
    )
    price_unit = Config.pricelist_id._get_product_price(Product, 1)
    tax_ids = fiscal_position.map_tax(
        Product.taxes_id.filtered_domain(
            env["account.tax"]._check_company_domain(env.company)
        )
    )
    if tax_ids:
        tax_values = tax_ids.compute_all(price_unit, env.company.currency_id, 1)
    else:
        tax_values = {
            "total_excluded": price_unit,
            "total_included": price_unit,
        }
    line = (
        0,
        0,
        {
            "product_id": Product.id,
            "qty": 1,
            "price_unit": price_unit,
            "price_subtotal": tax_values["total_excluded"],
            "price_subtotal_incl": tax_values["total_included"],
            "discount": 0,
            "tax_ids": [(6, 0, tax_ids.ids)],
        },
    )
    total = tax_values["total_included"]
    payment = (
        0,
        0,
        {
            "amount": total,
            "name": fields.Datetime.now(),
            "payment_method_id": CashPm.id,
        },
    )
    order_data = {
        "amount_paid": total,
        "amount_return": 0,
        "amount_tax": total - tax_values["total_excluded"],
        "amount_total": total,
        "date_order": fields.Datetime.to_string(fields.Datetime.now()),
        "fiscal_position_id": fiscal_position.id,
        "pricelist_id": Config.pricelist_id.id,
        "name": f"Order {uid}",
        "last_order_preparation_change": "{}",
        "lines": [line],
        "partner_id": partner.id if partner else False,
        "session_id": Session.id,
        "payment_ids": [payment],
        "uuid": uid,
        "user_id": env.uid,
        "to_invoice": is_invoiced,
    }
    sync = PosOrder.sync_from_ui([order_data])
    order = PosOrder.browse(sync["pos.order"][0]["id"])
    return order


def send_receipt(order):
    with patch.object(
        type(order),
        "_avea_schedule_receipt_mail_delivery",
        return_value=None,
    ):
        return order.avea_send_receipt_email_automatic()


def mails_for(order):
    return env["mail.mail"].search(
        [("model", "=", "pos.order"), ("res_id", "=", order.id)]
    )


print("=== POS receipt email QA (DEV) ===")
print(f"Company: {Company.name} | auto_email={Company.avea_auto_email_receipt}")
print(f"Session: {Session.id} | Product: {Product.display_name}")
print()

partners = {
    "with_email": make_partner("With Email", "pos-receipt-qa-with@dev.local"),
    "no_email": make_partner("No Email"),
    "blank_email": make_partner("Blank Email", "   "),
    "invalid_email": make_partner("Invalid Email", "not-an-email"),
    "bad_domain": make_partner("Bad Domain", "user@"),
}

mail_before = env["mail.mail"].search_count([])
Company.avea_auto_email_receipt = True

try:
    order = create_paid_order(partner=None, tag="walkin")
    sent = send_receipt(order)
    mail = mails_for(order)
    log(
        "Walk-in (no customer)",
        sent is False and not mail and order.state == "paid",
        f"sent={sent}, mails={len(mail)}, state={order.state}",
    )
except Exception:
    log("Walk-in (no customer)", False, traceback.format_exc().splitlines()[-1])

try:
    order = create_paid_order(partner=partners["with_email"], tag="withemail")
    sent = send_receipt(order)
    mail = mails_for(order)
    log(
        "Customer with valid @dev.local email",
        sent is True and len(mail) == 1 and order.avea_receipt_email_sent,
        f"sent={sent}, to={mail.email_to if mail else None}",
    )
    sent2 = send_receipt(order)
    mail2 = mails_for(order)
    log(
        "Duplicate background send ignored",
        sent2 is False and len(mail2) == 1,
        f"second_sent={sent2}, mails={len(mail2)}",
    )
except Exception:
    log("Customer with valid @dev.local email", False, traceback.format_exc().splitlines()[-1])

for key, label in [
    ("no_email", "Customer without email"),
    ("blank_email", "Customer with blank email"),
    ("invalid_email", "Customer with invalid email"),
    ("bad_domain", "Customer with malformed email"),
]:
    try:
        order = create_paid_order(partner=partners[key], tag=key)
        sent = send_receipt(order)
        mail = mails_for(order)
        log(label, sent is False and not mail, f"sent={sent}, mails={len(mail)}")
    except Exception:
        log(label, False, traceback.format_exc().splitlines()[-1])

try:
    Company.avea_auto_email_receipt = False
    order = create_paid_order(partner=partners["with_email"], tag="settingoff")
    sent = send_receipt(order)
    mail = mails_for(order)
    log("Auto email setting disabled", sent is False and not mail, f"sent={sent}")
    Company.avea_auto_email_receipt = True
except Exception:
    Company.avea_auto_email_receipt = True
    log("Auto email setting disabled", False, traceback.format_exc().splitlines()[-1])

try:
    order = create_paid_order(
        partner=partners["with_email"],
        tag="invoiceflag",
        is_invoiced=True,
    )
    sent = send_receipt(order)
    mail = mails_for(order)
    log(
        "Invoiced flag from POS ignored",
        order.to_invoice is False and sent is True and len(mail) == 1,
        f"to_invoice={order.to_invoice}, sent={sent}",
    )
except Exception:
    log("Invoiced flag from POS ignored", False, traceback.format_exc().splitlines()[-1])

try:
    order = create_paid_order(partner=partners["with_email"], tag="htmlctx")
    html = Company._avea_receipt_email_body_html(order)
    log(
        "Email HTML body renders",
        bool(html) and TEST_PREFIX in html,
        f"len={len(html)}",
    )
except Exception:
    log("Email HTML body renders", False, traceback.format_exc().splitlines()[-1])

try:
    order = create_paid_order(partner=partners["with_email"], tag="smtpfail")
    template = env.ref("avea_till.email_template_avea_pos_receipt")
    with patch.object(type(template), "send_mail", side_effect=RuntimeError("smtp down")):
        sent = order.avea_send_receipt_email_automatic()
    log(
        "SMTP/template failure releases claim",
        sent is False and order.state == "paid" and not order.avea_receipt_email_sent,
        f"sent={sent}, state={order.state}, flag={order.avea_receipt_email_sent}",
    )
except Exception:
    log("SMTP/template failure releases claim", False, traceback.format_exc().splitlines()[-1])

mail_after = env["mail.mail"].search_count([])
passed = sum(1 for _, ok, _ in results if ok)
print()
print("--- Summary ---")
print(f"{passed}/{len(results)} scenarios passed")
print(f"mail.mail delta: {mail_after - mail_before} (queued in txn only)")
failed = [s for s, ok, d in results if not ok]
if failed:
    print("Failures:", ", ".join(failed))
else:
    print("No backend errors reproduced in these scenarios.")

env.cr.rollback()
print("Rolled back — synthetic partners, orders, and queued mails were not kept.")
