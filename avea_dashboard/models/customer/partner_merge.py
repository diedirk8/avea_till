# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class BasePartnerMergeAutomaticWizard(models.TransientModel):
    _inherit = "base.partner.merge.automatic.wizard"

    group_by_phone = fields.Boolean(
        string="Phone",
        help="Group customers with the same phone number (ignoring spaces and symbols).",
    )

    @api.model
    def _generate_query(self, fields_list, maximum_group=100):
        if not self.env.context.get("avea_customers_only"):
            return super()._generate_query(fields_list, maximum_group=maximum_group)

        sql_fields = []
        for field in fields_list:
            if field == "email":
                sql_fields.append("lower(email)")
            elif field == "name":
                sql_fields.append("lower(name)")
            elif field == "phone":
                sql_fields.append(
                    "regexp_replace(coalesce(phone, ''), '[^0-9]+', '', 'g')"
                )
            elif field == "vat":
                sql_fields.append("replace(vat, ' ', '')")
            else:
                sql_fields.append(field)
        if not sql_fields:
            return super()._generate_query(fields_list, maximum_group=maximum_group)

        group_fields = ", ".join(sql_fields)
        filters = ["customer_rank > 0"]
        for field in fields_list:
            if field == "email":
                filters.append("email IS NOT NULL AND trim(email) != ''")
            elif field == "name":
                filters.append("name IS NOT NULL AND trim(name) != ''")
            elif field == "phone":
                filters.append("phone IS NOT NULL AND trim(phone) != ''")
            elif field == "vat":
                filters.append("vat IS NOT NULL AND trim(vat) != ''")
            elif field == "is_company":
                filters.append("is_company IS NOT NULL")
            elif field == "parent_id":
                filters.append("parent_id IS NOT NULL")
        criteria = " AND ".join(filters)

        text = [
            "SELECT min(id), array_agg(id)",
            "FROM res_partner",
            f"WHERE {criteria}",
            f"GROUP BY {group_fields}",
            "HAVING COUNT(*) >= 2",
            "ORDER BY min(id)",
        ]
        if maximum_group:
            text.append(f"LIMIT {maximum_group}")
        return " ".join(text)

    def action_avea_start_customer_dedupe(self):
        """Start manual duplicate review for retail customers only."""
        self.ensure_one()
        return self.with_context(avea_customers_only=True).action_start_manual_process()


class ResPartner(models.Model):
    _inherit = "res.partner"

    @api.model
    def _avea_min_duplicate_phone_digits(self):
        return 7

    @api.model
    def _avea_duplicate_customer_candidate_ids(self, partner=None):
        """Partner ids that share a non-empty email or phone with another customer."""
        min_phone = self._avea_min_duplicate_phone_digits()
        params = {"min_phone": min_phone}
        anchor_clause = ""
        if partner:
            partner = partner.exists()
            if not partner or partner.customer_rank <= 0:
                return []
            params.update(
                {
                    "email_key": (partner.email or "").strip().lower(),
                    "phone_key": "".join(
                        ch for ch in (partner.phone or "") if ch.isdigit()
                    ),
                }
            )
            anchor_clause = """
                AND (
                    (trim(coalesce(%(email_key)s, '')) != ''
                        AND lower(trim(coalesce(email, ''))) = %(email_key)s)
                    OR (
                        length(regexp_replace(coalesce(phone, ''), '[^0-9]+', '', 'g')) >= %(min_phone)s
                        AND regexp_replace(coalesce(phone, ''), '[^0-9]+', '', 'g') = %(phone_key)s
                        AND length(%(phone_key)s) >= %(min_phone)s
                    )
                )
            """

        query = f"""
            WITH normalized AS (
                SELECT
                    id,
                    lower(trim(coalesce(email, ''))) AS email_key,
                    regexp_replace(coalesce(phone, ''), '[^0-9]+', '', 'g') AS phone_key
                FROM res_partner
                WHERE customer_rank > 0
                  {anchor_clause}
            ),
            email_groups AS (
                SELECT array_agg(id) AS ids
                FROM normalized
                WHERE email_key != ''
                GROUP BY email_key
                HAVING COUNT(*) >= 2
            ),
            phone_groups AS (
                SELECT array_agg(id) AS ids
                FROM normalized
                WHERE length(phone_key) >= %(min_phone)s
                GROUP BY phone_key
                HAVING COUNT(*) >= 2
            )
            SELECT DISTINCT unnest(ids) AS partner_id
            FROM (
                SELECT ids FROM email_groups
                UNION ALL
                SELECT ids FROM phone_groups
            ) groups
        """
        self.env.cr.execute(query, params)
        return [row[0] for row in self.env.cr.fetchall()]

    def action_avea_merge_customers(self):
        partners = self.exists().filtered(lambda p: p.customer_rank > 0)
        if len(partners) < 2:
            raise UserError(_("Select at least two customers to merge."))
        if len(partners) > 3:
            raise UserError(
                _(
                    "For safety, merge at most three customers at a time. "
                    "Repeat the merge for any remaining duplicates."
                )
            )
        return {
            "type": "ir.actions.act_window",
            "name": _("Merge customers"),
            "res_model": "base.partner.merge.automatic.wizard",
            "view_mode": "form",
            "views": [(False, "form")],
            "target": "new",
            "context": {
                **self.env.context,
                "active_model": "res.partner",
                "active_ids": partners.ids,
                "avea_customer_workspace": True,
            },
        }

    @api.model
    def action_avea_show_possible_duplicates(self):
        ids = self._avea_duplicate_customer_candidate_ids()
        if not ids:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("No possible duplicates"),
                    "message": _(
                        "No customers share the same email address or phone number."
                    ),
                    "type": "success",
                    "sticky": False,
                },
            }
        action = self.env.ref("avea_till.action_avea_customer_centre").read()[0]
        action["domain"] = [("id", "in", ids)]
        action["context"] = dict(
            self.env.context,
            avea_customer_workspace=True,
            avea_duplicate_review=True,
        )
        action["name"] = _("Possible duplicates")
        return action

    def action_avea_show_related_duplicates(self):
        self.ensure_one()
        ids = self._avea_duplicate_customer_candidate_ids(partner=self)
        if len(ids) <= 1:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("No duplicates for this customer"),
                    "message": _(
                        "No other customers share this email address or phone number."
                    ),
                    "type": "info",
                    "sticky": False,
                },
            }
        action = self.env.ref("avea_till.action_avea_customer_centre").read()[0]
        action["domain"] = [("id", "in", ids)]
        action["context"] = dict(
            self.env.context,
            avea_customer_workspace=True,
            avea_duplicate_review=True,
            default_partner_id=self.id,
        )
        action["name"] = _("Possible duplicates")
        return action

    @api.model
    def action_avea_open_customer_dedupe_wizard(self):
        wizard = self.env["base.partner.merge.automatic.wizard"].create(
            {
                "group_by_email": True,
                "group_by_phone": True,
                "maximum_group": 100,
            }
        )
        return wizard.with_context(avea_customers_only=True).action_avea_start_customer_dedupe()
