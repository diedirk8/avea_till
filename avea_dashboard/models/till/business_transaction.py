from odoo import _, api, fields, models, tools
from odoo.tools.misc import format_date, format_time


class AveaBusinessTransaction(models.Model):
    _name = "avea.business.transaction"
    _description = "Business Transaction"
    _auto = False
    _order = "transaction_datetime desc, id desc"
    _rec_name = "reference"

    company_id = fields.Many2one("res.company", readonly=True)
    transaction_datetime = fields.Datetime(readonly=True)
    transaction_date = fields.Date(readonly=True)
    transaction_date_label = fields.Char(
        string="Date",
        compute="_compute_transaction_labels",
    )
    transaction_time_label = fields.Char(
        string="Time",
        compute="_compute_transaction_labels",
    )
    transaction_type = fields.Selection(
        [
            ("pos_sale", "POS Sale"),
            ("pos_refund", "POS Refund"),
            ("expense", "Expense"),
            ("supplier_payment", "Supplier Payment"),
            ("customer_payment", "Customer Payment"),
            ("cash_withdrawal", "Cash Withdrawal"),
            ("cash_transfer", "Cash Transfer"),
            ("cash_up", "Cash Up"),
            ("store_credit", "Store Credit"),
            ("till_cash_in", "Till Cash In"),
            ("till_cash_out", "Till Cash Out"),
            ("manual_journal", "Manual Journal"),
        ],
        string="Type",
        readonly=True,
    )
    reference = fields.Char(string="Reference", readonly=True)
    amount = fields.Monetary(string="Amount", readonly=True, currency_field="currency_id")
    currency_id = fields.Many2one("res.currency", readonly=True)
    payment_method_id = fields.Many2one("pos.payment.method", string="Payment Method", readonly=True)
    journal_id = fields.Many2one("account.journal", string="Account", readonly=True)
    user_id = fields.Many2one("res.users", string="User", readonly=True)
    res_model = fields.Char(readonly=True)
    res_id = fields.Integer(readonly=True)
    search_text = fields.Char(readonly=True)

    @api.depends("transaction_datetime")
    def _compute_transaction_labels(self):
        for record in self:
            if not record.transaction_datetime:
                record.transaction_date_label = False
                record.transaction_time_label = False
                continue
            local_dt = fields.Datetime.context_timestamp(record, record.transaction_datetime)
            record.transaction_date_label = format_date(record.env, local_dt.date())
            record.transaction_time_label = format_time(
                record.env,
                local_dt.time(),
                tz=local_dt.tzinfo,
                time_format="short",
            )

    @api.model
    def _avea_paid_order_states_sql(self):
        states = self.env["pos.session"]._avea_paid_order_states()
        return ", ".join(f"'{state}'" for state in states) or "'paid'"

    @api.model
    def _avea_narration_contains_sql(self, column, needle):
        """Match Avea narrations stored as plain text or HTML markup."""
        escaped = needle.replace("'", "''")
        return f"{column}::text LIKE '%{escaped}%'"

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        paid_states = self._avea_paid_order_states_sql()
        narration_withdrawn = self._avea_narration_contains_sql(
            "am.narration", "Recorded from Avea. Withdrawn"
        )
        narration_transfer = self._avea_narration_contains_sql(
            "am.narration", "Recorded from Avea. Transfer"
        )
        narration_avea = self._avea_narration_contains_sql(
            "am.narration", "Recorded from Avea."
        )
        query = f"""
            CREATE OR REPLACE VIEW {self._table} AS (
                SELECT
                    (10000000 * 1 + po.id) AS id,
                    po.company_id AS company_id,
                    po.date_order AS transaction_datetime,
                    DATE(po.date_order) AS transaction_date,
                    CASE
                        WHEN po.is_refund OR po.amount_total < 0 THEN 'pos_refund'
                        ELSE 'pos_sale'
                    END AS transaction_type,
                    COALESCE(
                        NULLIF(po.pos_reference, '/'),
                        NULLIF(po.name, '/'),
                        po.id::text
                    ) AS reference,
                    ABS(po.amount_total) AS amount,
                    rc.currency_id AS currency_id,
                    primary_payment.payment_method_id AS payment_method_id,
                    NULL::integer AS journal_id,
                    po.user_id AS user_id,
                    'pos.order' AS res_model,
                    po.id AS res_id,
                    LOWER(CONCAT_WS(
                        ' ',
                        COALESCE(NULLIF(po.pos_reference, '/'), ''),
                        COALESCE(NULLIF(po.name, '/'), ''),
                        COALESCE(NULLIF(am_inv.name, '/'), ''),
                        COALESCE(NULLIF(am_inv.ref, '/'), '')
                    )) AS search_text
                FROM pos_order po
                JOIN res_company rc ON rc.id = po.company_id
                LEFT JOIN account_move am_inv ON am_inv.id = po.account_move
                LEFT JOIN LATERAL (
                    SELECT pp.payment_method_id
                    FROM pos_payment pp
                    JOIN pos_payment_method ppm ON ppm.id = pp.payment_method_id
                    WHERE pp.pos_order_id = po.id
                      AND COALESCE(pp.is_change, false) = false
                      AND COALESCE(ppm.is_avea_store_credit, false) = false
                    ORDER BY ABS(pp.amount) DESC, pp.id DESC
                    LIMIT 1
                ) primary_payment ON true
                WHERE po.state IN ({paid_states})

                UNION ALL

                SELECT
                    (10000000 * 2 + cle.id) AS id,
                    cle.company_id AS company_id,
                    cle.transaction_date AS transaction_datetime,
                    DATE(cle.transaction_date) AS transaction_date,
                    'store_credit' AS transaction_type,
                    cle.name AS reference,
                    cle.amount AS amount,
                    cle.currency_id AS currency_id,
                    NULL::integer AS payment_method_id,
                    NULL::integer AS journal_id,
                    cle.user_id AS user_id,
                    'avea.credit.ledger.entry' AS res_model,
                    cle.id AS res_id,
                    LOWER(CONCAT_WS(
                        ' ',
                        cle.name,
                        COALESCE(cle.notes, ''),
                        COALESCE(NULLIF(am_inv.name, '/'), ''),
                        COALESCE(NULLIF(am_inv.ref, '/'), '')
                    )) AS search_text
                FROM avea_credit_ledger_entry cle
                LEFT JOIN account_move am_inv ON am_inv.id = cle.account_move_id
                WHERE cle.state = 'posted'
                  AND cle.pos_order_id IS NULL

                UNION ALL

                SELECT
                    (10000000 * 3 + absl.id) AS id,
                    absl.company_id AS company_id,
                    CASE
                        WHEN {narration_withdrawn} THEN absl.create_date
                        ELSE COALESCE(am.date::timestamp, absl.create_date)
                    END AS transaction_datetime,
                    COALESCE(am.date, DATE(absl.create_date)) AS transaction_date,
                    CASE
                        WHEN {narration_withdrawn} THEN 'cash_withdrawal'
                        WHEN {narration_transfer} THEN 'cash_transfer'
                        ELSE 'expense'
                    END AS transaction_type,
                    COALESCE(
                        NULLIF(absl.payment_ref, ''),
                        NULLIF(am.ref, '/'),
                        NULLIF(am.name, '/'),
                        absl.id::text
                    ) AS reference,
                    ABS(absl.amount) AS amount,
                    COALESCE(absl.currency_id, rc.currency_id) AS currency_id,
                    NULL::integer AS payment_method_id,
                    absl.journal_id AS journal_id,
                    COALESCE(absl.create_uid, am.create_uid) AS user_id,
                    'account.bank.statement.line' AS res_model,
                    absl.id AS res_id,
                    LOWER(CONCAT_WS(
                        ' ',
                        COALESCE(absl.payment_ref, ''),
                        COALESCE(am.ref, ''),
                        COALESCE(am.name, ''),
                        COALESCE(rp.name, ''),
                        COALESCE(expense_bill.ref, ''),
                        COALESCE(expense_bill.name, '')
                    )) AS search_text
                FROM account_bank_statement_line absl
                JOIN account_move am ON am.id = absl.move_id
                JOIN res_company rc ON rc.id = absl.company_id
                LEFT JOIN res_partner rp ON rp.id = absl.partner_id
                LEFT JOIN LATERAL (
                    SELECT bill.id, bill.name, bill.ref
                    FROM account_move bill
                    JOIN account_move_line bill_line ON bill_line.move_id = bill.id
                    JOIN account_move_line st_line ON st_line.move_id = am.id
                    JOIN account_partial_reconcile apr ON (
                        (apr.debit_move_id = bill_line.id AND apr.credit_move_id = st_line.id)
                        OR (apr.credit_move_id = bill_line.id AND apr.debit_move_id = st_line.id)
                    )
                    WHERE bill.move_type = 'in_invoice'
                      AND bill.invoice_origin = 'Avea Operational Expense'
                    LIMIT 1
                ) expense_bill ON true
                WHERE am.state = 'posted'
                  AND (
                    {narration_withdrawn}
                    OR (
                        {narration_transfer}
                        AND absl.amount < 0
                    )
                    OR (
                        absl.pos_session_id IS NULL
                        AND expense_bill.id IS NOT NULL
                    )
                  )

                UNION ALL

                SELECT *
                FROM (
                    SELECT DISTINCT ON (am.id)
                        (10000000 * 4 + am.id) AS id,
                        am.company_id AS company_id,
                        am.date::timestamp AS transaction_datetime,
                        am.date AS transaction_date,
                        'manual_journal' AS transaction_type,
                        COALESCE(NULLIF(am.ref, '/'), NULLIF(am.name, '/'), am.id::text) AS reference,
                        ABS(liq.balance) AS amount,
                        am.currency_id AS currency_id,
                        NULL::integer AS payment_method_id,
                        aj.id AS journal_id,
                        am.create_uid AS user_id,
                        'account.move' AS res_model,
                        am.id AS res_id,
                        LOWER(CONCAT_WS(
                            ' ',
                            COALESCE(am.ref, ''),
                            COALESCE(am.name, ''),
                            COALESCE(am.narration, '')
                        )) AS search_text
                    FROM account_move am
                    JOIN account_move_line liq ON liq.move_id = am.id
                    JOIN account_account aa ON aa.id = liq.account_id
                    JOIN account_journal aj ON aj.id = am.journal_id
                    WHERE am.state = 'posted'
                      AND am.move_type = 'entry'
                      AND {narration_avea}
                      AND NOT ({narration_withdrawn})
                      AND NOT ({narration_transfer})
                      AND aj.type = 'general'
                      AND aa.account_type IN ('asset_cash', 'asset_current')
                      AND liq.balance <> 0
                    ORDER BY am.id, ABS(liq.balance) DESC
                ) manual_journal_rows

                UNION ALL

                SELECT
                    (10000000 * 5 + atm.id) AS id,
                    pc.company_id AS company_id,
                    atm.movement_date AS transaction_datetime,
                    DATE(atm.movement_date) AS transaction_date,
                    CASE
                        WHEN atm.reason = 'POS Cash In' THEN 'till_cash_in'
                        ELSE 'till_cash_out'
                    END AS transaction_type,
                    COALESCE(
                        NULLIF(atm.ledger_reference, ''),
                        NULLIF(atm.name, '/'),
                        atm.id::text
                    ) AS reference,
                    atm.amount AS amount,
                    rc.currency_id AS currency_id,
                    NULL::integer AS payment_method_id,
                    NULL::integer AS journal_id,
                    atm.user_id AS user_id,
                    'avea.till.movement' AS res_model,
                    atm.id AS res_id,
                    LOWER(CONCAT_WS(
                        ' ',
                        COALESCE(atm.ledger_reference, ''),
                        COALESCE(atm.name, ''),
                        COALESCE(atm.notes, ''),
                        COALESCE(atm.reason, '')
                    )) AS search_text
                FROM avea_till_movement atm
                JOIN pos_session ps ON ps.id = atm.session_id
                JOIN pos_config pc ON pc.id = ps.config_id
                JOIN res_company rc ON rc.id = pc.company_id
                WHERE atm.reason IN ('POS Cash In', 'POS Cash Out')

                UNION ALL

                SELECT
                    (10000000 * 6 + ap.id) AS id,
                    ap.company_id AS company_id,
                    ap.date::timestamp AS transaction_datetime,
                    ap.date AS transaction_date,
                    CASE
                        WHEN ap.payment_type = 'inbound' THEN 'customer_payment'
                        ELSE 'supplier_payment'
                    END AS transaction_type,
                    COALESCE(
                        NULLIF(ap.memo, '/'),
                        NULLIF(ap.name, '/'),
                        ap.payment_reference,
                        ap.id::text
                    ) AS reference,
                    ABS(ap.amount) AS amount,
                    ap.currency_id AS currency_id,
                    NULL::integer AS payment_method_id,
                    ap.journal_id AS journal_id,
                    ap.create_uid AS user_id,
                    'account.payment' AS res_model,
                    ap.id AS res_id,
                    LOWER(CONCAT_WS(
                        ' ',
                        COALESCE(ap.memo, ''),
                        COALESCE(ap.name, ''),
                        COALESCE(ap.payment_reference, ''),
                        COALESCE(rp.name, '')
                    )) AS search_text
                FROM account_payment ap
                LEFT JOIN res_partner rp ON rp.id = ap.partner_id
                WHERE ap.state IN ('paid', 'posted', 'in_process')
                  AND ap.partner_type IN ('customer', 'supplier')
                  AND NOT EXISTS (
                      SELECT 1
                      FROM pos_payment pp
                      WHERE pp.online_account_payment_id = ap.id
                  )

                UNION ALL

                SELECT
                    (10000000 * 7 + acu.id) AS id,
                    acu.company_id AS company_id,
                    acu.cash_up_date AS transaction_datetime,
                    DATE(acu.cash_up_date) AS transaction_date,
                    'cash_up' AS transaction_type,
                    COALESCE(NULLIF(acu.name, '/'), acu.id::text) AS reference,
                    acu.total_payments_counted AS amount,
                    acu.currency_id AS currency_id,
                    NULL::integer AS payment_method_id,
                    acu.till_journal_id AS journal_id,
                    acu.user_id AS user_id,
                    'avea.cash.up' AS res_model,
                    acu.id AS res_id,
                    LOWER(CONCAT_WS(
                        ' ',
                        COALESCE(acu.name, ''),
                        COALESCE(acu.session_id::text, ''),
                        COALESCE(ps.name, '')
                    )) AS search_text
                FROM avea_cash_up acu
                LEFT JOIN pos_session ps ON ps.id = acu.session_id
                WHERE acu.state = 'confirmed'
            )
        """
        self.env.cr.execute(query)

    @api.model
    def _avea_base_domain(self):
        return [("company_id", "in", self.env.companies.ids)]

    @api.model
    def action_avea_open_business_transactions(self):
        action = self.env.ref(
            "avea_till.action_avea_business_transactions_window"
        ).read()[0]
        action["domain"] = self._avea_base_domain()
        return action

    def action_open_source_record(self):
        self.ensure_one()
        if not self.res_model or not self.res_id:
            return False
        res_model = self.res_model
        res_id = self.res_id
        if res_model == "account.bank.statement.line":
            statement_line = self.env[res_model].browse(res_id).exists()
            if statement_line.move_id:
                res_model = "account.move"
                res_id = statement_line.move_id.id
        record = self.env[res_model].browse(res_id).exists()
        if not record:
            return False
        action = record.get_formview_action()
        action["name"] = self.reference or action.get("name") or _("Transaction")
        action["target"] = "current"
        return action
