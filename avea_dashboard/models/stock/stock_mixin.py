from datetime import datetime, time

from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_compare, float_round


AVEA_RECEIVE_ORIGIN = "Avea Receive Stock"
AVEA_STOCK_TAKE_ORIGIN = "Avea Stock Take"
AVEA_INTERNAL_USE_ORIGIN = "Avea Use Stock"
AVEA_SUPPLIER_COST_PRECISION = "Avea Supplier Cost"
AVEA_PRODUCT_COST_PRECISION = "Product Price"


class AveaStockMixin(models.AbstractModel):
    _name = "avea.stock.mixin"
    _description = "Avea Stock Helpers"

    @api.model
    def _avea_product_cost_digits(self):
        return self.env["decimal.precision"].precision_get(AVEA_PRODUCT_COST_PRECISION)

    @api.model
    def _avea_supplier_cost_digits(self):
        return self.env["decimal.precision"].precision_get(AVEA_SUPPLIER_COST_PRECISION)

    @api.model
    def _avea_round_product_cost(self, amount):
        return float_round(amount or 0.0, precision_digits=self._avea_product_cost_digits())

    @api.model
    def _avea_round_supplier_cost(self, amount):
        return float_round(amount or 0.0, precision_digits=self._avea_supplier_cost_digits())

    @api.model
    def _avea_round_percent(self, amount):
        return float_round(amount or 0.0, precision_digits=2)

    @api.model
    def _avea_compare_product_cost(self, left, right):
        return float_compare(
            left or 0.0,
            right or 0.0,
            precision_digits=self._avea_product_cost_digits(),
        )

    @api.model
    def _avea_compare_supplier_cost(self, left, right):
        return float_compare(
            left or 0.0,
            right or 0.0,
            precision_digits=self._avea_supplier_cost_digits(),
        )

    @api.model
    def _avea_supplier_cost_matches_product_cost(self, supplier_cost, product_cost):
        """True when a 4dp supplier cost equals a 2dp Avea product cost."""
        return (
            self._avea_compare_product_cost(supplier_cost, product_cost) == 0
            or self._avea_compare_product_cost(
                self._avea_round_supplier_cost(supplier_cost), product_cost
            )
            == 0
        )

    @api.model
    def _avea_default_stock_location(self, company=None):
        company = company or self.env.company
        warehouse = self.env["stock.warehouse"].search(
            [("company_id", "=", company.id)], limit=1
        )
        if not warehouse:
            raise UserError(_("No warehouse is configured for this company."))
        return warehouse.lot_stock_id

    @api.model
    def _avea_apply_inventory_count(self, product, location, counted_qty, origin=None):
        """Set on-hand quantity through native Odoo inventory adjustment."""
        Quant = self.env["stock.quant"].sudo()
        quant = Quant.search(
            [
                ("product_id", "=", product.id),
                ("location_id", "=", location.id),
            ],
            limit=1,
        )
        inventory_context = {
            "inventory_mode": True,
            "inventory_name": origin or AVEA_STOCK_TAKE_ORIGIN,
        }
        if quant:
            quant = quant.with_context(**inventory_context)
            quant.inventory_quantity = counted_qty
        else:
            quant = Quant.with_context(**inventory_context).create(
                {
                    "product_id": product.id,
                    "location_id": location.id,
                    "inventory_quantity": counted_qty,
                }
            )
        quant.action_apply_inventory()
        return quant

    def _avea_datetime_at_noon(self, date_value):
        if not date_value:
            return fields.Datetime.now()
        if isinstance(date_value, datetime):
            return date_value
        return datetime.combine(date_value, time(12, 0, 0))

    def _avea_complete_picking(self, picking, date_done=None):
        """Confirm and validate a picking without exposing Odoo wizards."""
        self.ensure_one()
        picking = picking.sudo()
        if not picking:
            raise UserError(_("There is no stock receipt to complete."))
        if picking.state == "draft":
            picking.action_confirm()
        for move in picking.move_ids.filtered(lambda move: move.state != "cancel"):
            if move.product_uom.is_zero(move.quantity) and not move.product_uom.is_zero(
                move.product_uom_qty
            ):
                move.quantity = move.product_uom_qty
            move.picked = True
        picking.with_context(
            skip_backorder=True,
            skip_sanity_check=True,
            cancel_backorder=True,
            button_validate_picking_ids=picking.ids,
        ).button_validate()
        if picking.state != "done":
            picking._action_done()
        if picking.state != "done":
            raise UserError(
                _("The stock receipt could not be completed. Ask your administrator to check Inventory.")
            )
        if date_done:
            done_at = self._avea_datetime_at_noon(date_done)
            picking.write({"date_done": done_at, "scheduled_date": done_at})
            picking.move_ids.write({"date": done_at})
        return picking

    def _avea_incoming_picking(self, purchase_order):
        pickings = purchase_order.sudo().picking_ids.filtered(
            lambda picking: picking.state not in ("done", "cancel")
            and picking.picking_type_code == "incoming"
        )
        return pickings[:1]

    def _avea_supplier_payable_account(self, partner, company):
        payable = partner.with_company(company).property_account_payable_id
        if not payable:
            raise UserError(
                _("This supplier has no payable account. Ask your accountant to set one up.")
            )
        return payable

    def _avea_pay_vendor_bill(
        self, bill, journal, partner, company, pay_date, payment_ref, amount=None
    ):
        """Pay a vendor bill from an Avea cash/bank journal.

        Matches Operational Expense: statement line + payable reconciliation.
        """
        payable = self._avea_supplier_payable_account(partner, company)
        residual = bill.amount_residual
        pay_amount = residual if amount is None else amount
        pay_amount = bill.currency_id.round(pay_amount or 0.0)
        if bill.currency_id.is_zero(pay_amount):
            return self.env["account.bank.statement.line"]
        if bill.currency_id.compare_amounts(pay_amount, residual) > 0:
            raise UserError(_("You cannot pay more than the amount still open."))
        statement_line = (
            self.env["account.bank.statement.line"]
            .sudo()
            .with_context(no_retrieve_partner=True)
            .create(
                {
                    "journal_id": journal.id,
                    "amount": -pay_amount,
                    "date": pay_date,
                    "payment_ref": payment_ref,
                    "partner_id": partner.id,
                    "counterpart_account_id": payable.id,
                }
            )
        )
        bill_lines = bill.line_ids.filtered(
            lambda line: line.account_id == payable and not line.reconciled
        )
        statement_lines = statement_line.move_id.line_ids.filtered(
            lambda line: line.account_id == payable and not line.reconciled
        )
        to_reconcile = bill_lines | statement_lines
        if len(to_reconcile) >= 2:
            to_reconcile.sudo().reconcile()
        return statement_line

    @api.model
    def _avea_allocate_oldest_first(self, bills, payment_amount, currency):
        """Spread ``payment_amount`` across open bills, oldest due first.

        Returns ``(allocations, leftover)`` where ``allocations`` is a list of
        ``(bill, amount)`` pairs (zero amounts included so the UI can clear
        later bills) and ``leftover`` is money that stays on the supplier.
        """
        remaining = currency.round(payment_amount or 0.0)
        if currency.compare_amounts(remaining, 0.0) < 0:
            remaining = 0.0
        allocated = []
        for bill in bills:
            if currency.compare_amounts(remaining, 0.0) <= 0:
                allocated.append((bill, 0.0))
                continue
            due = abs(bill.amount_residual or 0.0)
            apply = currency.round(min(due, remaining))
            allocated.append((bill, apply))
            remaining = currency.round(remaining - apply)
        return allocated, remaining

    def _avea_pay_vendor_bills(
        self,
        allocations,
        journal,
        partner,
        company,
        pay_date,
        payment_ref,
        payment_amount=None,
    ):
        """Pay several vendor bills with one cash/bank statement line.

        ``allocations`` is a list of ``(bill, amount)`` pairs. Partial amounts
        are allowed. ``payment_amount`` is the EFT that left the bank. When it
        is larger than the bills applied, the extra stays as a credit on the
        supplier (paid on account). When omitted, the statement line total is
        the sum of allocations.
        """
        currency = (
            (allocations[0][0].currency_id if allocations else None)
            or company.currency_id
        )
        payable = self._avea_supplier_payable_account(partner, company)
        cleaned = []
        for bill, amount in allocations or ():
            pay_amount = currency.round(amount or 0.0)
            if currency.is_zero(pay_amount):
                continue
            residual = bill.amount_residual
            if currency.compare_amounts(pay_amount, residual) > 0:
                raise UserError(
                    _("You cannot pay more than the amount still open on %s.")
                    % (bill.ref or bill.name or _("this bill"))
                )
            cleaned.append((bill, pay_amount))
        applied = currency.round(sum(amount for _bill, amount in cleaned))
        if payment_amount is None:
            total = applied
        else:
            total = currency.round(payment_amount or 0.0)
            if currency.compare_amounts(total, 0.0) <= 0:
                raise UserError(_("Enter the amount that left the bank."))
            if currency.compare_amounts(applied, total) > 0:
                raise UserError(
                    _(
                        "The amounts on the bills are more than this payment. "
                        "Lower what you apply, or enter the full EFT amount."
                    )
                )
        if currency.is_zero(total):
            return self.env["account.bank.statement.line"]
        refs = [bill.ref or bill.name for bill, _amount in cleaned if bill.ref or bill.name]
        statement_line = (
            self.env["account.bank.statement.line"]
            .sudo()
            .with_context(no_retrieve_partner=True)
            .create(
                {
                    "journal_id": journal.id,
                    "amount": -total,
                    "date": pay_date,
                    "payment_ref": (payment_ref or ", ".join(refs) or _("Supplier payment"))[:255],
                    "partner_id": partner.id,
                    "counterpart_account_id": payable.id,
                }
            )
        )
        for bill, pay_amount in cleaned:
            self._avea_apply_statement_line_to_bill(
                statement_line, bill, payable, currency, pay_amount
            )
        return statement_line

    def _avea_apply_statement_line_to_bill(
        self, statement_line, bill, payable, currency, amount
    ):
        amount = currency.round(amount or 0.0)
        if currency.is_zero(amount):
            return
        bill_lines = bill.line_ids.filtered(
            lambda line: line.account_id == payable and not line.reconciled
        )
        leftover = amount
        for bill_line in bill_lines:
            if currency.is_zero(leftover):
                break
            payment_line = statement_line.move_id.line_ids.filtered(
                lambda line: line.account_id == payable and not line.reconciled
            )[:1]
            if not payment_line:
                raise UserError(_("Could not apply this payment to %s.") % (bill.ref or bill.name))
            bill_left = abs(bill_line.amount_residual_currency or bill_line.amount_residual)
            pay_left = abs(payment_line.amount_residual_currency or payment_line.amount_residual)
            apply = min(leftover, bill_left, pay_left)
            apply = currency.round(apply)
            if currency.is_zero(apply):
                continue
            self._avea_reconcile_aml_amount(payment_line, bill_line, apply, currency)
            leftover = currency.round(leftover - apply)

    def _avea_reconcile_aml_amount(self, payment_line, bill_line, amount, currency):
        """Reconcile ``amount`` of a payment AML onto a bill payable AML."""
        bill_left = abs(bill_line.amount_residual_currency or bill_line.amount_residual)
        pay_left = abs(payment_line.amount_residual_currency or payment_line.amount_residual)
        apply = currency.round(min(amount, bill_left, pay_left))
        if currency.is_zero(apply):
            return
        amls = payment_line | bill_line
        if (
            currency.compare_amounts(apply, bill_left) >= 0
            or currency.compare_amounts(apply, pay_left) >= 0
        ):
            amls.sudo().reconcile()
            return
        bill_sign = 1 if bill_line.amount_residual >= 0 else -1
        bill_curr_sign = 1 if bill_line.amount_residual_currency >= 0 else -1
        values_list = [
            {
                "aml": payment_line,
                "amount_residual": payment_line.amount_residual,
                "amount_residual_currency": payment_line.amount_residual_currency,
                "parent_state": payment_line.parent_state,
            },
            {
                "aml": bill_line,
                "amount_residual": apply * bill_sign,
                "amount_residual_currency": apply * bill_curr_sign,
                "parent_state": bill_line.parent_state,
            },
        ]
        pre = amls._reconcile_pre_hook()
        results, _fully = amls._prepare_reconciliation_amls(values_list)
        partials_vals = [
            result["partial_values"]
            for result in results
            if result.get("partial_values")
        ]
        if partials_vals:
            self.env["account.partial.reconcile"].sudo().create(partials_vals)
        amls._reconcile_post_hook(pre)

    @api.model
    def _avea_statement_lines_for_bill(self, bill):
        """Cash/bank statement lines that paid this vendor bill."""
        Statement = self.env["account.bank.statement.line"]
        if not bill:
            return Statement
        amls = bill.line_ids
        counterparts = (
            amls.matched_debit_ids.debit_move_id
            | amls.matched_debit_ids.credit_move_id
            | amls.matched_credit_ids.debit_move_id
            | amls.matched_credit_ids.credit_move_id
        ) - amls
        from_aml = counterparts.mapped("statement_line_id")
        from_move = Statement.sudo().search(
            [("move_id", "in", counterparts.move_id.ids)]
        )
        return from_aml | from_move

    @api.model
    def _avea_journal_from_bill_payment(self, bill):
        """Resolve cash/bank journal from how the vendor bill was reconciled."""
        lines = self._avea_statement_lines_for_bill(bill)
        if lines[:1].journal_id:
            return lines[:1].journal_id
        if not bill:
            return self.env["account.journal"]
        partner = bill.partner_id
        company = bill.company_id
        try:
            payable = self._avea_supplier_payable_account(partner, company)
        except UserError:
            payable = self.env["account.account"].search(
                [
                    ("account_type", "=", "liability_payable"),
                    ("company_id", "=", company.id),
                ],
                limit=1,
            )
        bill_lines = bill.line_ids.filtered(
            lambda line: line.account_id == payable and line.reconciled
        )
        for bill_line in bill_lines:
            partials = bill_line.matched_debit_ids | bill_line.matched_credit_ids
            for partial in partials:
                candidates = (partial.debit_move_id, partial.credit_move_id)
                for aml in candidates:
                    if not aml or aml.id == bill_line.id:
                        continue
                    payment = aml.payment_id
                    if payment and payment.journal_id:
                        return payment.journal_id
        return self.env["account.journal"]

    @api.model
    def _avea_supplier_credit_available(self, partner, company):
        """Posted vendor credit notes with an open balance for this supplier."""
        if not partner:
            return 0.0
        credits = (
            self.env["account.move"]
            .sudo()
            .with_company(company)
            .search(
                [
                    ("partner_id", "=", partner.id),
                    ("company_id", "=", company.id),
                    ("move_type", "=", "in_refund"),
                    ("state", "=", "posted"),
                ]
            )
        )
        total = 0.0
        for credit in credits:
            residual = abs(credit.amount_residual)
            if not credit.currency_id.is_zero(residual):
                total += residual
        return company.currency_id.round(total)

    @api.model
    def _avea_apply_supplier_credits_to_bill(self, bill, partner, company):
        """Reconcile open vendor credit notes against a vendor bill (oldest credits first)."""
        if not bill or bill.currency_id.is_zero(bill.amount_residual):
            return 0.0
        payable = self._avea_supplier_payable_account(partner, company)
        amount_before = bill.amount_residual
        credits = (
            self.env["account.move"]
            .sudo()
            .with_company(company)
            .search(
                [
                    ("partner_id", "=", partner.id),
                    ("company_id", "=", company.id),
                    ("move_type", "=", "in_refund"),
                    ("state", "=", "posted"),
                ],
                order="invoice_date asc, id asc",
            )
        )
        for credit in credits:
            if bill.currency_id.is_zero(bill.amount_residual):
                break
            if credit.currency_id.is_zero(abs(credit.amount_residual)):
                continue
            bill_lines = bill.line_ids.filtered(
                lambda line: line.account_id == payable and not line.reconciled
            )
            credit_lines = credit.line_ids.filtered(
                lambda line: line.account_id == payable and not line.reconciled
            )
            if not bill_lines or not credit_lines:
                continue
            (bill_lines + credit_lines).sudo().reconcile()
        return company.currency_id.round(amount_before - bill.amount_residual)

    @api.model
    def _avea_partner_store_credit_balance(self, partner):
        """Posted Pets Empire store credit still available for the customer to spend."""
        if not partner:
            return 0.0
        partner.invalidate_recordset(["avea_credit_balance"])
        currency = partner.avea_credit_currency_id or partner.company_id.currency_id
        if not currency:
            currency = self.env.company.currency_id
        return currency.round(partner.avea_credit_balance or 0.0)

    @api.model
    def _avea_store_credit_trade_reason(self):
        reason = self.env.ref(
            "avea_till.credit_reason_animal_trade",
            raise_if_not_found=False,
        )
        if reason:
            return reason
        return self.env["avea.credit.reason"].search(
            [("active", "=", True), ("manual_issue", "=", True)],
            order="sequence, name, id",
            limit=1,
        )

    @api.model
    def _avea_apply_store_credit_to_vendor_bill(
        self,
        bill,
        partner,
        company,
        amount,
        already_issued=True,
        pay_date=None,
        payment_ref=None,
    ):
        """Settle a vendor bill with Pets Empire store credit.

        Store credit is a customer liability (they can spend it in the shop). It
        is not a supplier credit note from a stock return.

        If the credit was already issued, reverse the issuance expense against
        accounts payable so the stock — not a gift — carries the cost. Remaining
        wallet balance can be lower if they already spent some in the shop; this
        path does not consume or grant wallet credit. If it was not issued yet,
        grant Animal Trade credit and post payable against the store-credit
        liability.
        """
        if not bill or not partner:
            return 0.0
        currency = bill.currency_id
        pay_amount = currency.round(amount or 0.0)
        if currency.is_zero(pay_amount):
            return 0.0
        residual = bill.amount_residual
        if currency.is_zero(residual):
            return 0.0
        if currency.compare_amounts(pay_amount, residual) > 0:
            pay_amount = residual
        if currency.compare_amounts(pay_amount, 0.0) <= 0:
            return 0.0

        company = company or bill.company_id
        company.sudo()._avea_credit_ensure_accounting_setup()
        payable = self._avea_supplier_payable_account(partner, company)
        expense = company.avea_credit_issuance_expense_account_id
        liability = company._avea_credit_ref("liability_account")
        journal = company.avea_credit_issuance_journal_id
        if not expense or not liability or not journal:
            raise UserError(
                _("Store Credit issuance accounting is not configured for this company.")
            )

        partner._avea_credit_ensure_customer()
        if partner.supplier_rank < 1:
            partner.sudo().write({"supplier_rank": 1})

        pay_date = pay_date or fields.Date.context_today(self)
        reference = payment_ref or bill.ref or bill.name or _("Store credit")
        line_name = _("Store credit — %s") % reference
        counterpart = expense if already_issued else liability
        move = (
            self.env["account.move"]
            .sudo()
            .with_company(company)
            .create(
                {
                    "move_type": "entry",
                    "journal_id": journal.id,
                    "date": pay_date,
                    "ref": line_name,
                    "company_id": company.id,
                    "line_ids": [
                        Command.create(
                            {
                                "name": line_name,
                                "account_id": payable.id,
                                "partner_id": partner.id,
                                "debit": pay_amount,
                                "credit": 0.0,
                            }
                        ),
                        Command.create(
                            {
                                "name": line_name,
                                "account_id": counterpart.id,
                                "partner_id": partner.id if not already_issued else False,
                                "debit": 0.0,
                                "credit": pay_amount,
                            }
                        ),
                    ],
                }
            )
        )
        move.action_post()

        bill_lines = bill.line_ids.filtered(
            lambda line: line.account_id == payable and not line.reconciled
        )
        settle_lines = move.line_ids.filtered(
            lambda line: line.account_id == payable and not line.reconciled
        )
        to_reconcile = bill_lines | settle_lines
        if len(to_reconcile) >= 2:
            to_reconcile.sudo().reconcile()

        if not already_issued:
            reason = self._avea_store_credit_trade_reason()
            if not reason:
                raise UserError(
                    _("No store credit issue reason is configured for animal trades.")
                )
            self.env["avea.credit.ledger.entry"].sudo().create_issued_credit(
                partner=partner,
                amount=pay_amount,
                reason=reason,
                notes=line_name,
                account_move=move,
            )
            partner.invalidate_recordset(
                ["avea_credit_balance", "avea_credit_currency_id"]
            )
        return pay_amount
