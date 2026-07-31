from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


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
        reason_id = reason.id if hasattr(reason, "id") else reason
        return self.create(
            {
                "partner_id": partner.id,
                "amount": amount,
                "reason_id": reason_id,
                "notes": notes,
                "state": "posted",
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
