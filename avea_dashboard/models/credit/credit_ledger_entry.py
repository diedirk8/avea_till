from odoo import Command, _, api, fields, models
from odoo.exceptions import AccessError, ValidationError


class AveaCreditLedgerEntry(models.Model):
    _name = "avea.credit.ledger.entry"
    _description = "Customer Credit Ledger Entry"
    _order = "transaction_date desc, id desc"
    _rec_name = "name"

    name = fields.Char(
        string="Reference",
        required=True,
        copy=False,
        readonly=True,
        default="/",
        index=True,
    )
    partner_id = fields.Many2one(
        "res.partner",
        string="Customer",
        required=True,
        ondelete="restrict",
        index=True,
    )
    transaction_date = fields.Datetime(
        string="Date",
        required=True,
        default=fields.Datetime.now,
        index=True,
    )
    reason_id = fields.Many2one(
        "avea.credit.reason",
        string="Reason",
        required=True,
        ondelete="restrict",
        index=True,
    )
    reason_is_outflow = fields.Boolean(
        related="reason_id.is_outflow",
    )
    amount = fields.Monetary(
        string="Amount",
        required=True,
        currency_field="currency_id",
    )
    notes = fields.Text(
        string="Notes",
    )
    user_id = fields.Many2one(
        "res.users",
        string="Recorded By",
        default=lambda self: self.env.user,
        required=True,
        readonly=True,
    )
    state = fields.Selection(
        [
            ("posted", "Confirmed"),
            ("cancelled", "Void"),
        ],
        string="Status",
        default="posted",
        required=True,
        readonly=True,
        index=True,
    )
    currency_id = fields.Many2one(
        "res.currency",
        string="Currency",
        required=True,
        default=lambda self: self.env.company.currency_id,
    )
    company_id = fields.Many2one(
        "res.company",
        string="Company",
        required=True,
        default=lambda self: self.env.company,
    )
    pos_order_id = fields.Many2one(
        "pos.order",
        string="POS Order",
        ondelete="set null",
        index=True,
        copy=False,
        readonly=True,
    )
    pos_payment_id = fields.Many2one(
        "pos.payment",
        string="POS Payment",
        ondelete="set null",
        index=True,
        copy=False,
        readonly=True,
    )
    account_move_id = fields.Many2one(
        "account.move",
        string="Accounting Entry",
        ondelete="set null",
        copy=False,
        readonly=True,
        index=True,
    )

    _pos_payment_uniq = models.Constraint(
        "unique (pos_payment_id)",
        "A store credit ledger entry already exists for this POS payment.",
    )
    _account_move_uniq = models.Constraint(
        "unique (account_move_id)",
        "Each accounting entry can only be linked to one store credit ledger entry.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "/") in ("/", False):
                vals["name"] = (
                    self.env["ir.sequence"].next_by_code("avea.credit.ledger.entry")
                    or "/"
                )
        return super().create(vals_list)

    @api.constrains("amount")
    def _check_amount_positive(self):
        for entry in self:
            if entry.currency_id.compare_amounts(entry.amount, 0.0) <= 0:
                raise ValidationError(
                    _("Ledger entry amount must be greater than zero.")
                )

    def _signed_amount(self):
        self.ensure_one()
        if self.reason_id.is_outflow:
            return -self.amount
        return self.amount

    @api.model
    def create_issued_credit(self, partner, amount, reason, notes=None):
        """Create a confirmed store credit statement entry."""
        partner._avea_credit_ensure_customer()
        reason_id = reason.id if hasattr(reason, "id") else reason
        entry = self.create(
            {
                "partner_id": partner.id,
                "amount": amount,
                "reason_id": reason_id,
                "notes": notes,
                "state": "posted",
            }
        )
        entry._avea_credit_create_issuance_account_move()
        return entry

    def _avea_credit_create_issuance_account_move(self):
        self.ensure_one()
        if self.account_move_id:
            return self.account_move_id

        company = self.company_id
        company._avea_credit_ensure_accounting_setup()
        expense_account = company.avea_credit_issuance_expense_account_id
        liability_account = company._avea_credit_ref("liability_account")
        journal = company.avea_credit_issuance_journal_id
        if not expense_account or not liability_account or not journal:
            raise ValidationError(
                _("Store Credit issuance accounting is not configured for this company.")
            )

        reference = self.name
        line_name = reference
        if self.notes:
            line_name = f"{reference} - {self.notes}"

        move_vals = {
            "move_type": "entry",
            "journal_id": journal.id,
            "date": fields.Date.to_date(self.transaction_date)
            or fields.Date.context_today(self),
            "ref": reference,
            "company_id": company.id,
            "line_ids": [
                Command.create(
                    {
                        "name": line_name,
                        "account_id": expense_account.id,
                        "debit": self.amount,
                        "credit": 0.0,
                    }
                ),
                Command.create(
                    {
                        "name": line_name,
                        "account_id": liability_account.id,
                        "debit": 0.0,
                        "credit": self.amount,
                        "partner_id": self.partner_id.id,
                    }
                ),
            ],
        }
        move = self.env["account.move"].sudo().with_company(company).create(move_vals)
        move.action_post()
        self.sudo().write({"account_move_id": move.id})
        return move

    @api.model
    def _get_default_manual_issue_reason(self):
        return self.env["avea.credit.reason"].search(
            [("active", "=", True), ("manual_issue", "=", True)],
            order="sequence, name, id",
            limit=1,
        )

    @api.model
    def pos_issue_store_credit(self, partner_id, amount, reason_id=None, notes=None):
        """Issue store credit from the POS for the selected customer."""
        if not self.env.user.has_group("avea_till.group_avea_credit_manager"):
            raise AccessError(
                _("You do not have permission to issue store credit.")
            )
        partner = self.env["res.partner"].browse(partner_id).exists()
        if not partner:
            raise ValidationError(_("Select a customer before issuing store credit."))
        if reason_id:
            reason = self.env["avea.credit.reason"].browse(reason_id).exists()
            if not reason or not reason.active or not reason.manual_issue:
                raise ValidationError(_("Select a valid store credit reason."))
        else:
            reason = self._get_default_manual_issue_reason()
            if not reason:
                raise ValidationError(
                    _("No store credit issue reason is configured.")
                )
        currency = partner.avea_credit_currency_id or self.env.company.currency_id
        if currency.compare_amounts(amount, 0.0) <= 0:
            raise ValidationError(
                _("Store credit amount must be greater than zero.")
            )
        notes_value = (notes or "").strip() or None
        self.create_issued_credit(
            partner=partner,
            amount=amount,
            reason=reason,
            notes=notes_value,
        )
        partner.invalidate_recordset(["avea_credit_balance", "avea_credit_currency_id"])
        return {
            "balance": partner.avea_credit_balance,
            "currency_id": partner.avea_credit_currency_id.id,
            "partner_name": partner.display_name,
        }

    @api.model
    def _get_pos_purchase_reason(self):
        return self.env.ref(
            "avea_till.credit_reason_pos_purchase",
            raise_if_not_found=False,
        )

    @api.model
    def _get_pos_refund_reason(self):
        return self.env.ref(
            "avea_till.credit_reason_refund",
            raise_if_not_found=False,
        )

    @api.model
    def _format_pos_reference(self, pos_order):
        if not pos_order:
            return ""
        if pos_order.pos_reference and pos_order.pos_reference != "/":
            return pos_order.pos_reference
        if pos_order.name and pos_order.name != "/":
            return pos_order.name
        return str(pos_order.id)

    @api.model
    def _validate_pos_amount(self, amount, currency):
        if currency.compare_amounts(amount, 0.0) <= 0:
            raise ValidationError(
                _("Store credit amount must be greater than zero.")
            )

    @api.model
    def get_partner_available_balance(self, partner, company=None):
        """Return the current posted store credit balance for POS checks."""
        company = company or self.env.company
        domain = self._credit_report_base_domain(company) + [
            ("partner_id", "=", partner.id),
        ]
        return self._sum_signed_amount_domain(domain)

    @api.model
    def create_pos_redemption(
        self,
        partner,
        amount,
        pos_order=None,
        pos_payment=None,
        notes=None,
    ):
        """Record a store credit redemption from a POS sale."""
        reason = self._get_pos_purchase_reason()
        if not reason:
            raise ValidationError(
                _("The POS Purchase store credit reason is not configured.")
            )
        currency = partner.avea_credit_currency_id or self.env.company.currency_id
        self._validate_pos_amount(amount, currency)
        company = pos_order.company_id if pos_order else self.env.company
        available = self.get_partner_available_balance(partner, company)
        if currency.compare_amounts(amount, available) > 0:
            raise ValidationError(
                _(
                    "Only %(amount)s Store Credit is available for this customer.",
                    amount=currency.format(available),
                )
            )
        reference = self._format_pos_reference(pos_order)
        payment_note = reference or _("POS redemption")
        return self.create(
            {
                "partner_id": partner.id,
                "amount": amount,
                "reason_id": reason.id,
                "notes": notes or payment_note,
                "state": "posted",
                "currency_id": currency.id,
                "company_id": pos_order.company_id.id if pos_order else self.env.company.id,
                "pos_order_id": pos_order.id if pos_order else False,
                "pos_payment_id": pos_payment.id if pos_payment else False,
            }
        )

    @api.model
    def create_pos_refund_credit(
        self,
        partner,
        amount,
        pos_order=None,
        pos_payment=None,
        notes=None,
    ):
        """Return store credit to a customer from a POS refund."""
        reason = self._get_pos_refund_reason()
        if not reason:
            raise ValidationError(
                _("The Refund store credit reason is not configured.")
            )
        currency = partner.avea_credit_currency_id or self.env.company.currency_id
        self._validate_pos_amount(amount, currency)
        reference = self._format_pos_reference(pos_order)
        payment_note = reference or _("POS refund")
        return self.create(
            {
                "partner_id": partner.id,
                "amount": amount,
                "reason_id": reason.id,
                "notes": notes or payment_note,
                "state": "posted",
                "currency_id": currency.id,
                "company_id": pos_order.company_id.id if pos_order else self.env.company.id,
                "pos_order_id": pos_order.id if pos_order else False,
                "pos_payment_id": pos_payment.id if pos_payment else False,
            }
        )

    @api.model
    def action_open_ledger(self, partner_id=None):
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "avea_till.action_avea_credit_ledger"
        )
        if partner_id:
            partner = self.env["res.partner"].browse(partner_id)
            action["domain"] = [("partner_id", "=", partner_id)]
            action["name"] = _("%s — Store Credit") % partner.display_name
            action["context"] = {
                "default_partner_id": partner_id,
                "search_default_posted": 1,
            }
        return action

    @api.model
    def _credit_report_base_domain(self, company=None):
        company = company or self.env.company
        return [
            ("company_id", "=", company.id),
            ("state", "=", "posted"),
        ]

    @staticmethod
    def _signed_amount_value(amount, is_outflow):
        return -amount if is_outflow else amount

    @api.model
    def _sum_signed_amount_domain(self, domain):
        inflow_groups = self.read_group(
            domain + [("reason_id.is_outflow", "=", False)],
            ["amount:sum"],
            [],
        )
        outflow_groups = self.read_group(
            domain + [("reason_id.is_outflow", "=", True)],
            ["amount:sum"],
            [],
        )
        inflow_total = inflow_groups[0]["amount"] if inflow_groups else 0.0
        outflow_total = outflow_groups[0]["amount"] if outflow_groups else 0.0
        return (inflow_total or 0.0) - (outflow_total or 0.0)

    @api.model
    def _get_partner_balance_at(self, partner, as_at_datetime, company=None):
        domain = self._credit_report_base_domain(company) + [
            ("partner_id", "=", partner.id),
            ("transaction_date", "<=", fields.Datetime.to_string(as_at_datetime)),
        ]
        return self._sum_signed_amount_domain(domain)

    @api.model
    def _get_statement_lines(self, partner, date_from, date_to, company=None):
        company = company or self.env.company
        period_start = self.env["avea.credit.report.mixin"]._date_to_datetime_start(
            date_from
        )
        period_end = self.env["avea.credit.report.mixin"]._date_to_datetime_end(
            date_to
        )
        domain = self._credit_report_base_domain(company) + [
            ("partner_id", "=", partner.id),
            ("transaction_date", "<=", fields.Datetime.to_string(period_end)),
        ]
        entries = self.search(domain, order="transaction_date asc, id asc")
        if not entries:
            return {
                "opening_balance": 0.0,
                "lines": [],
                "closing_balance": 0.0,
            }

        outflow_by_reason = {
            reason.id: reason.is_outflow for reason in entries.reason_id
        }
        reason_name_by_id = {
            reason.id: reason.display_name for reason in entries.reason_id
        }

        opening_balance = 0.0
        running_balance = 0.0
        lines = []
        for entry in entries:
            is_outflow = outflow_by_reason.get(entry.reason_id.id, False)
            signed_amount = self._signed_amount_value(entry.amount, is_outflow)
            if entry.transaction_date < period_start:
                opening_balance += signed_amount
                continue

            credit_added = entry.amount if signed_amount > 0 else 0.0
            credit_used = entry.amount if signed_amount < 0 else 0.0
            running_balance = (
                opening_balance + signed_amount
                if not lines
                else lines[-1]["running_balance"] + signed_amount
            )
            lines.append(
                {
                    "transaction_date": entry.transaction_date,
                    "name": entry.name,
                    "reason": reason_name_by_id.get(
                        entry.reason_id.id, entry.reason_id.display_name
                    ),
                    "credit_added": credit_added,
                    "credit_used": credit_used,
                    "running_balance": running_balance,
                }
            )
        closing_balance = running_balance if lines else opening_balance
        return {
            "opening_balance": opening_balance,
            "lines": lines,
            "closing_balance": closing_balance,
        }

    @api.model
    def _get_partner_balance_before(self, partner, before_datetime, company=None):
        if not before_datetime:
            return 0.0
        domain = self._credit_report_base_domain(company) + [
            ("partner_id", "=", partner.id),
            ("transaction_date", "<", fields.Datetime.to_string(before_datetime)),
        ]
        return self._sum_signed_amount_domain(domain)

    @api.model
    def _get_activity_lines(self, date_from, date_to, company=None, partner=None,
                            reason_id=None, user_id=None):
        company = company or self.env.company
        period_start = self.env["avea.credit.report.mixin"]._date_to_datetime_start(
            date_from
        )
        period_end = self.env["avea.credit.report.mixin"]._date_to_datetime_end(
            date_to
        )
        domain = self._credit_report_base_domain(company) + [
            ("transaction_date", ">=", fields.Datetime.to_string(period_start)),
            ("transaction_date", "<=", fields.Datetime.to_string(period_end)),
        ]
        if partner:
            domain.append(("partner_id", "=", partner.id))
        if reason_id:
            domain.append(("reason_id", "=", reason_id.id))
        if user_id:
            domain.append(("user_id", "=", user_id.id))
        entries = self.search(domain, order="transaction_date asc, id asc")
        if not entries:
            return []

        outflow_by_reason = {
            reason.id: reason.is_outflow for reason in entries.reason_id
        }
        reason_name_by_id = {
            reason.id: reason.display_name for reason in entries.reason_id
        }
        partner_name_by_id = {
            partner.id: partner.display_name for partner in entries.partner_id
        }
        user_name_by_id = {user.id: user.display_name for user in entries.user_id}

        lines = []
        for entry in entries:
            reason_id = entry.reason_id.id
            is_outflow = outflow_by_reason.get(reason_id, False)
            lines.append(
                {
                    "transaction_date": entry.transaction_date,
                    "partner": partner_name_by_id.get(
                        entry.partner_id.id, entry.partner_id.display_name
                    ),
                    "reason": reason_name_by_id.get(
                        reason_id, entry.reason_id.display_name
                    ),
                    "name": entry.name,
                    "amount": self._signed_amount_value(entry.amount, is_outflow),
                    "amount_display": entry.amount,
                    "is_outflow": is_outflow,
                    "employee": user_name_by_id.get(
                        entry.user_id.id, entry.user_id.display_name
                    ),
                }
            )
        return lines
