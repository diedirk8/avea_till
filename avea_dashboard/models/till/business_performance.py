from markupsafe import Markup, escape

from odoo import _, api, fields, models
from odoo.tools.misc import formatLang

from .reporting_period import (
    PERIOD_CUSTOM,
    PERIOD_LAST_7,
    PERIOD_LAST_30,
    PERIOD_MTD,
    PERIOD_TODAY,
    PERIOD_YESTERDAY,
    PERIOD_WTD,
    PERIOD_YTD,
    normalize_period_key,
)


class AveaBusinessPerformanceLine(models.TransientModel):
    _name = "avea.business.performance.line"
    _description = "Business Performance Ranking Line"
    _order = "section, rank, id"

    dashboard_id = fields.Many2one(
        "avea.business.performance",
        string="Performance",
        required=True,
        ondelete="cascade",
    )
    currency_id = fields.Many2one(
        related="dashboard_id.currency_id",
    )
    section = fields.Selection(
        [
            ("top_product", "Top Product"),
            ("top_category", "Top Category"),
            ("profit_product", "Most Profitable Product"),
            ("profit_category", "Most Profitable Category"),
        ],
        required=True,
        readonly=True,
    )
    rank = fields.Integer(
        readonly=True,
    )
    product_id = fields.Many2one(
        "product.product",
        readonly=True,
    )
    category_id = fields.Many2one(
        "product.category",
        readonly=True,
    )
    name = fields.Char(
        string="Name",
        readonly=True,
    )
    quantity_sold = fields.Float(
        string="Qty",
        digits="Product Unit",
        readonly=True,
    )
    revenue_ex_tax = fields.Monetary(
        string="Revenue EX Tax",
        currency_field="currency_id",
        readonly=True,
    )
    gross_profit = fields.Monetary(
        string="Gross Profit",
        currency_field="currency_id",
        readonly=True,
    )
    cost_total = fields.Monetary(
        string="COGS",
        currency_field="currency_id",
        readonly=True,
    )
    discount_given = fields.Monetary(
        string="Discounts Given",
        currency_field="currency_id",
        readonly=True,
    )
    gross_margin_percent = fields.Float(
        string="Gross Margin %",
        digits=(16, 1),
        readonly=True,
    )


class AveaBusinessPerformancePromotionLine(models.TransientModel):
    _name = "avea.business.performance.promotion.line"
    _description = "Business Performance Promotion"
    _order = "discount_given desc, sales_ex_tax desc, id"

    dashboard_id = fields.Many2one(
        "avea.business.performance",
        string="Performance",
        required=True,
        ondelete="cascade",
    )
    currency_id = fields.Many2one(related="dashboard_id.currency_id")
    promotion_id = fields.Many2one("avea.promotion", readonly=True)
    name = fields.Char(string="Promotion", readonly=True)
    deal_summary = fields.Char(string="Deal", readonly=True)
    deal_type_label = fields.Char(string="Type", readonly=True)
    order_count = fields.Integer(string="Tickets", readonly=True)
    quantity = fields.Float(string="Qty", digits="Product Unit", readonly=True)
    discount_given = fields.Monetary(
        string="Discount",
        currency_field="currency_id",
        readonly=True,
    )
    discount_display = fields.Char(string="Discount", readonly=True)
    sales_ex_tax = fields.Monetary(
        string="Sold for",
        currency_field="currency_id",
        readonly=True,
    )


class AveaBusinessPerformancePromotionProductLine(models.TransientModel):
    _name = "avea.business.performance.promotion.product.line"
    _description = "Business Performance Promotion Product"
    _order = "quantity desc, discount_given desc, id"

    dashboard_id = fields.Many2one(
        "avea.business.performance",
        string="Performance",
        required=True,
        ondelete="cascade",
    )
    currency_id = fields.Many2one(related="dashboard_id.currency_id")
    promotion_id = fields.Many2one("avea.promotion", readonly=True)
    promotion_name = fields.Char(string="Promotion", readonly=True)
    product_id = fields.Many2one("product.product", readonly=True)
    product_display = fields.Char(string="Product", readonly=True)
    deal_type_label = fields.Char(string="Type", readonly=True)
    quantity = fields.Float(string="Qty", digits="Product Unit", readonly=True)
    discount_given = fields.Monetary(
        string="Discount",
        currency_field="currency_id",
        readonly=True,
    )
    discount_display = fields.Char(string="Discount", readonly=True)
    sales_ex_tax = fields.Monetary(
        string="Sold for",
        currency_field="currency_id",
        readonly=True,
    )


class AveaBusinessPerformance(models.TransientModel):
    _name = "avea.business.performance"
    _description = "Business Performance"
    _inherit = ["avea.reporting.workspace.mixin"]
    _rec_name = "period_label"

    period = fields.Selection(
        [
            ("today", "Today"),
            ("yesterday", "Yesterday"),
            ("wtd", "Week to Date"),
            ("mtd", "Month to Date"),
            ("last_7", "Last 7 Days"),
            ("last_30", "Last 30 Days"),
            ("ytd", "Year to Date"),
            ("custom", "Custom Period"),
        ],
        string="Period",
        default="today",
        required=True,
    )
    date_from = fields.Date(string="From")
    date_to = fields.Date(string="To")
    period_label = fields.Char(
        compute="_compute_period_labels",
    )
    period_range_display = fields.Char(
        compute="_compute_period_labels",
    )
    comparison_label = fields.Char(
        compute="_compute_period_labels",
    )
    comparison_range_display = fields.Char(
        compute="_compute_period_labels",
    )
    currency_id = fields.Many2one(
        "res.currency",
        default=lambda self: self.env.company.currency_id,
    )
    sales_ex_tax = fields.Monetary(
        string="Sales",
        compute="_compute_financial_summary",
        currency_field="currency_id",
    )
    cost_of_goods_sold = fields.Monetary(
        string="Cost of Goods Sold",
        compute="_compute_financial_summary",
        currency_field="currency_id",
    )
    gross_profit = fields.Monetary(
        string="Gross Profit",
        compute="_compute_financial_summary",
        currency_field="currency_id",
    )
    gross_margin_percent = fields.Float(
        string="Gross Margin %",
        compute="_compute_financial_summary",
        digits=(16, 1),
    )
    discounts_given = fields.Monetary(
        string="Discounts Given",
        compute="_compute_financial_summary",
        currency_field="currency_id",
    )
    previous_sales_ex_tax = fields.Monetary(
        compute="_compute_financial_summary",
        currency_field="currency_id",
    )
    previous_cost_of_goods_sold = fields.Monetary(
        compute="_compute_financial_summary",
        currency_field="currency_id",
    )
    previous_gross_profit = fields.Monetary(
        compute="_compute_financial_summary",
        currency_field="currency_id",
    )
    previous_discounts_given = fields.Monetary(
        compute="_compute_financial_summary",
        currency_field="currency_id",
    )
    sales_ex_tax_change_display = fields.Char(
        compute="_compute_financial_summary",
    )
    gross_profit_change_display = fields.Char(
        compute="_compute_financial_summary",
    )
    discounts_given_change_display = fields.Char(
        compute="_compute_financial_summary",
    )

    line_ids = fields.One2many(
        "avea.business.performance.line",
        "dashboard_id",
        string="Rankings",
        readonly=True,
    )
    top_product_line_ids = fields.One2many(
        "avea.business.performance.line",
        "dashboard_id",
        domain=[("section", "=", "top_product")],
        readonly=True,
    )
    top_category_line_ids = fields.One2many(
        "avea.business.performance.line",
        "dashboard_id",
        domain=[("section", "=", "top_category")],
        readonly=True,
    )
    profit_product_line_ids = fields.One2many(
        "avea.business.performance.line",
        "dashboard_id",
        domain=[("section", "=", "profit_product")],
        readonly=True,
    )
    profit_category_line_ids = fields.One2many(
        "avea.business.performance.line",
        "dashboard_id",
        domain=[("section", "=", "profit_category")],
        readonly=True,
    )

    show_top_products = fields.Boolean(compute="_compute_visibility")
    show_top_categories = fields.Boolean(compute="_compute_visibility")
    show_profit_products = fields.Boolean(compute="_compute_visibility")
    show_profit_categories = fields.Boolean(compute="_compute_visibility")
    platform_line_ids = fields.One2many(
        "avea.business.reporting.platform.line",
        "performance_id",
        string="Sales platforms",
        readonly=True,
    )
    show_platform_reporting = fields.Boolean(compute="_compute_platform_reporting")
    platform_sales_ex_tax = fields.Monetary(
        compute="_compute_platform_reporting",
        currency_field="currency_id",
    )
    platform_gross_profit = fields.Monetary(
        compute="_compute_platform_reporting",
        currency_field="currency_id",
    )
    platform_commission = fields.Monetary(
        compute="_compute_platform_reporting",
        currency_field="currency_id",
    )
    platform_contribution = fields.Monetary(
        compute="_compute_platform_reporting",
        currency_field="currency_id",
    )
    promotion_line_ids = fields.One2many(
        "avea.business.performance.promotion.line",
        "dashboard_id",
        string="Promotions",
        readonly=True,
    )
    promotion_product_line_ids = fields.One2many(
        "avea.business.performance.promotion.product.line",
        "dashboard_id",
        string="Promotion products",
        readonly=True,
    )
    show_promotions = fields.Boolean(compute="_compute_promotion_reporting")
    promo_ticket_count = fields.Integer(readonly=True)
    promo_unit_count = fields.Float(digits="Product Unit", readonly=True)
    promo_discount = fields.Monetary(
        string="Discount",
        currency_field="currency_id",
        readonly=True,
    )
    promo_sales_ex_tax = fields.Monetary(
        string="Sold for",
        currency_field="currency_id",
        readonly=True,
    )
    promotion_deal_cards_html = fields.Html(
        string="Promotion deal cards",
        compute="_compute_promotion_cards_html",
        sanitize=False,
    )
    promotion_product_cards_html = fields.Html(
        string="Promotion product cards",
        compute="_compute_promotion_cards_html",
        sanitize=False,
    )

    @api.model_create_multi
    def create(self, vals_list):
        dashboards = super().create(vals_list)
        dashboards._populate_rankings()
        return dashboards

    def write(self, vals):
        res = super().write(vals)
        if any(key in vals for key in ("period", "date_from", "date_to")):
            self._populate_rankings()
        return res

    @api.depends(
        "line_ids",
        "top_product_line_ids",
        "top_category_line_ids",
        "profit_product_line_ids",
        "profit_category_line_ids",
    )
    def _compute_visibility(self):
        for dashboard in self:
            dashboard.show_top_products = bool(dashboard.top_product_line_ids)
            dashboard.show_top_categories = bool(dashboard.top_category_line_ids)
            dashboard.show_profit_products = bool(dashboard.profit_product_line_ids)
            dashboard.show_profit_categories = bool(dashboard.profit_category_line_ids)

    @api.depends(
        "platform_line_ids",
        "platform_line_ids.sales_ex_tax",
        "platform_line_ids.gross_profit",
        "platform_line_ids.commission",
        "platform_line_ids.contribution",
    )
    def _compute_platform_reporting(self):
        for dashboard in self:
            lines = dashboard.platform_line_ids
            dashboard.show_platform_reporting = bool(lines)
            dashboard.platform_sales_ex_tax = sum(lines.mapped("sales_ex_tax"))
            dashboard.platform_gross_profit = sum(lines.mapped("gross_profit"))
            dashboard.platform_commission = sum(lines.mapped("commission"))
            dashboard.platform_contribution = sum(lines.mapped("contribution"))

    @api.depends("promotion_line_ids", "promotion_product_line_ids")
    def _compute_promotion_reporting(self):
        for dashboard in self:
            dashboard.show_promotions = bool(
                dashboard.promotion_line_ids or dashboard.promotion_product_line_ids
            )

    @api.depends(
        "promotion_line_ids",
        "promotion_line_ids.name",
        "promotion_line_ids.deal_summary",
        "promotion_line_ids.deal_type_label",
        "promotion_line_ids.order_count",
        "promotion_line_ids.quantity",
        "promotion_line_ids.discount_display",
        "promotion_line_ids.sales_ex_tax",
        "promotion_product_line_ids",
        "promotion_product_line_ids.product_display",
        "promotion_product_line_ids.promotion_name",
        "promotion_product_line_ids.deal_type_label",
        "promotion_product_line_ids.quantity",
        "promotion_product_line_ids.discount_display",
        "promotion_product_line_ids.sales_ex_tax",
        "currency_id",
    )
    def _compute_promotion_cards_html(self):
        for dashboard in self:
            dashboard.promotion_deal_cards_html = dashboard._build_promotion_deal_cards_html()
            dashboard.promotion_product_cards_html = (
                dashboard._build_promotion_product_cards_html()
            )

    def _currency_delta_display(self, delta):
        currency = self.env.company.currency_id
        if currency.is_zero(delta):
            return _("—")
        formatted = formatLang(self.env, abs(delta), currency_obj=currency)
        if delta > 0:
            return f"+{formatted}"
        return f"-{formatted}"

    @api.depends("period", "date_from", "date_to")
    def _compute_financial_summary(self):
        for dashboard in self:
            period = dashboard.period or PERIOD_TODAY
            windows = dashboard._period_windows(period)
            current_orders = dashboard._paid_orders_between(*windows["data_current"])
            previous_orders = dashboard._paid_orders_between(*windows["data_previous"])
            financial = dashboard._reporting_financial_summary_for_period(orders=current_orders)
            previous = dashboard._reporting_financial_summary_for_period(orders=previous_orders)
            dashboard.sales_ex_tax = financial["revenue_ex_tax"]
            dashboard.cost_of_goods_sold = financial["cost_total"]
            dashboard.gross_profit = financial["gross_profit"]
            dashboard.gross_margin_percent = financial["gross_margin_percent"]
            dashboard.discounts_given = financial["discounts_given"]
            dashboard.previous_sales_ex_tax = previous["revenue_ex_tax"]
            dashboard.previous_cost_of_goods_sold = previous["cost_total"]
            dashboard.previous_gross_profit = previous["gross_profit"]
            dashboard.previous_discounts_given = previous["discounts_given"]
            dashboard.sales_ex_tax_change_display = dashboard._currency_delta_display(
                financial["revenue_ex_tax"] - previous["revenue_ex_tax"]
            )
            dashboard.gross_profit_change_display = dashboard._currency_delta_display(
                financial["gross_profit"] - previous["gross_profit"]
            )
            dashboard.discounts_given_change_display = dashboard._currency_delta_display(
                financial["discounts_given"] - previous["discounts_given"]
            )

    @api.depends("period", "date_from", "date_to")
    def _compute_period_labels(self):
        for dashboard in self:
            windows = dashboard._period_windows(dashboard.period or PERIOD_TODAY)
            dashboard.period_label = windows["labels"][0]
            dashboard.period_range_display = dashboard._format_day_range(
                *windows["display_current"]
            )
            dashboard.comparison_label = windows["labels"][1]
            dashboard.comparison_range_display = _(
                "Compared with %s"
            ) % dashboard._format_day_range(*windows["display_previous"])

    @api.model
    def action_open_business_performance(
        self, period="today", date_from=None, date_to=None
    ):
        period = normalize_period_key(period)
        vals = {"period": period}
        if period == PERIOD_CUSTOM:
            start, end = self._normalize_custom_dates(date_from, date_to)
            vals["date_from"] = start
            vals["date_to"] = end
        dashboard = self.create(vals)
        return {
            "type": "ir.actions.act_window",
            "name": _("Performance"),
            "res_model": self._name,
            "view_mode": "form",
            "res_id": dashboard.id,
            "target": "current",
            "context": {"clear_breadcrumbs": True},
        }

    def action_period_today(self):
        return self.action_open_business_performance(period=PERIOD_TODAY)

    def action_period_yesterday(self):
        return self.action_open_business_performance(period=PERIOD_YESTERDAY)

    def action_period_wtd(self):
        return self.action_open_business_performance(period=PERIOD_WTD)

    def action_period_mtd(self):
        return self.action_open_business_performance(period=PERIOD_MTD)

    def action_period_last_7(self):
        return self.action_open_business_performance(period=PERIOD_LAST_7)

    def action_period_last_30(self):
        return self.action_open_business_performance(period=PERIOD_LAST_30)

    def action_period_ytd(self):
        return self.action_open_business_performance(period=PERIOD_YTD)

    def action_period_custom(self):
        today = fields.Date.context_today(self)
        return self.action_open_business_performance(
            period=PERIOD_CUSTOM,
            date_from=today.replace(day=1),
            date_to=today,
        )

    def action_apply_custom_period(self):
        self.ensure_one()
        return self.action_open_business_performance(
            period=PERIOD_CUSTOM,
            date_from=self.date_from,
            date_to=self.date_to,
        )

    def action_open_overview(self):
        return self.env["avea.business.overview"].action_open_business_overview()

    def action_open_profit_report(self):
        self.ensure_one()
        return self.env["avea.profit.report"].action_open_for_workspace(
            period=self.period,
            date_from=self.date_from,
            date_to=self.date_to,
            source_model=self._name,
        )

    def action_open_discount_report(self):
        self.ensure_one()
        return self.env["avea.discount.report"].action_open_for_workspace(
            period=self.period,
            date_from=self.date_from,
            date_to=self.date_to,
            source_model=self._name,
        )

    def action_refresh(self):
        self.ensure_one()
        return self.action_open_business_performance(
            period=self.period,
            date_from=self.date_from,
            date_to=self.date_to,
        )

    def _period_windows(self, period):
        return self._reporting_period_windows(
            period,
            date_from=self.date_from,
            date_to=self.date_to,
        )

    def _format_day_range(self, day_from, day_to):
        return self._reporting_format_day_range(day_from, day_to)

    def _paid_orders_between(self, day_from, day_to):
        return self._reporting_paid_orders_between(day_from, day_to)

    @api.model
    def _normalize_custom_dates(self, date_from=None, date_to=None):
        return self._reporting_normalize_custom_dates(date_from, date_to)

    def _populate_rankings(self):
        Line = self.env["avea.business.performance.line"]
        PosLine = self.env["pos.order.line"]
        for dashboard in self:
            if not dashboard.id:
                continue
            Line.search([("dashboard_id", "=", dashboard.id)]).unlink()
            windows = dashboard._period_windows(dashboard.period or PERIOD_TODAY)
            orders = dashboard._paid_orders_between(*windows["data_current"])
            rankings = PosLine._avea_performance_rankings(orders)
            rows = []
            section_map = {
                "top_products": ("top_product", "product"),
                "top_categories": ("top_category", "category"),
                "profit_products": ("profit_product", "product"),
                "profit_categories": ("profit_category", "category"),
            }
            for key, (section, kind) in section_map.items():
                for index, row in enumerate(rankings.get(key) or [], start=1):
                    vals = {
                        "dashboard_id": dashboard.id,
                        "section": section,
                        "rank": index,
                        "name": row["label"],
                        "quantity_sold": row["units_positive"],
                        "revenue_ex_tax": row["revenue_ex_tax"],
                        "cost_total": row["cost_total"],
                        "gross_profit": row["gross_profit"],
                        "discount_given": row["discount_given"],
                        "gross_margin_percent": row["gross_margin_percent"],
                    }
                    if kind == "product":
                        vals["product_id"] = row["record_id"]
                    else:
                        vals["category_id"] = row["record_id"] or False
                    rows.append(vals)
            if rows:
                Line.create(rows)
            dashboard._reporting_populate_platform_lines(dashboard, orders)
            dashboard._populate_promotions(orders)

    def _populate_promotions(self, orders):
        self.ensure_one()
        PromoLine = self.env["avea.business.performance.promotion.line"]
        ProductLine = self.env["avea.business.performance.promotion.product.line"]
        PromoLine.search([("dashboard_id", "=", self.id)]).unlink()
        ProductLine.search([("dashboard_id", "=", self.id)]).unlink()
        analysis = self.env["pos.order.line"]._avea_promotion_analysis(orders)
        summary = analysis["summary"]
        self.write(
            {
                "promo_ticket_count": summary["order_count"],
                "promo_unit_count": summary["unit_count"],
                "promo_discount": summary["discount_given"],
                "promo_sales_ex_tax": summary["sales_ex_tax"],
            }
        )
        promo_rows = [
            {
                "dashboard_id": self.id,
                "promotion_id": row["promotion_id"] or False,
                "name": row["name"],
                "deal_summary": row["deal_summary"],
                "deal_type_label": row["deal_type_label"],
                "order_count": row["order_count"],
                "quantity": row["quantity"],
                "discount_given": row["discount_given"],
                "discount_display": row["discount_display"],
                "sales_ex_tax": row["sales_ex_tax"],
            }
            for row in analysis["promotions"]
        ]
        if promo_rows:
            PromoLine.create(promo_rows)
        product_rows = [
            {
                "dashboard_id": self.id,
                "promotion_id": row["promotion_id"] or False,
                "promotion_name": row["promotion_name"],
                "product_id": row["product_id"] or False,
                "product_display": row["product_display"],
                "deal_type_label": row["deal_type_label"],
                "quantity": row["quantity"],
                "discount_given": row["discount_given"],
                "discount_display": row["discount_display"],
                "sales_ex_tax": row["sales_ex_tax"],
            }
            for row in analysis["products"]
        ]
        if product_rows:
            ProductLine.create(product_rows)

    def _format_promotion_qty(self, quantity):
        formatted = formatLang(self.env, quantity or 0.0, dp="Product Unit")
        if "," in formatted and "." not in formatted:
            return formatted.rstrip("0").rstrip(",")
        return formatted.rstrip("0").rstrip(".")

    def _format_promotion_money(self, amount):
        self.ensure_one()
        return formatLang(self.env, amount or 0.0, currency_obj=self.currency_id)

    def _promotion_card_stat(self, label, value):
        return (
            Markup('<div class="o_avea_promo_card_stat"><span class="o_avea_promo_card_stat_label">')
            + escape(label or "")
            + Markup('</span><span class="o_avea_promo_card_stat_value">')
            + escape(value or "")
            + Markup("</span></div>")
        )

    def _promotion_discount_stat(self, line):
        return self._promotion_card_stat(
            _("Discount"),
            line.discount_display or line.deal_type_label or "—",
        )

    def _promotion_card_html(self, *, title, subtitle, stats):
        subtitle_html = Markup("")
        if subtitle:
            subtitle_html = (
                Markup('<p class="o_avea_promo_card_subtitle">')
                + escape(subtitle)
                + Markup("</p>")
            )
        return (
            Markup('<article class="o_avea_promo_card"><h3 class="o_avea_promo_card_title">')
            + escape(title or "")
            + Markup("</h3>")
            + subtitle_html
            + Markup('<div class="o_avea_promo_card_stats">')
            + Markup("").join(stats)
            + Markup("</div></article>")
        )

    def _build_promotion_deal_cards_html(self):
        self.ensure_one()
        cards = []
        for line in self.promotion_line_ids:
            subtitle = line.deal_summary or line.deal_type_label
            cards.append(
                self._promotion_card_html(
                    title=line.name,
                    subtitle=subtitle if subtitle != line.name else False,
                    stats=[
                        self._promotion_card_stat(_("Tickets"), str(line.order_count or 0)),
                        self._promotion_card_stat(
                            _("Qty"),
                            self._format_promotion_qty(line.quantity),
                        ),
                        self._promotion_discount_stat(line),
                        self._promotion_card_stat(
                            _("Sold for"),
                            self._format_promotion_money(line.sales_ex_tax),
                        ),
                    ],
                )
            )
        if not cards:
            return False
        return Markup('<div class="o_avea_promo_card_list">') + Markup("").join(cards) + Markup("</div>")

    def _build_promotion_product_cards_html(self):
        self.ensure_one()
        cards = []
        for line in self.promotion_product_line_ids:
            cards.append(
                self._promotion_card_html(
                    title=line.product_display,
                    subtitle=line.promotion_name,
                    stats=[
                        self._promotion_card_stat(
                            _("Qty"),
                            self._format_promotion_qty(line.quantity),
                        ),
                        self._promotion_discount_stat(line),
                        self._promotion_card_stat(
                            _("Sold for"),
                            self._format_promotion_money(line.sales_ex_tax),
                        ),
                    ],
                )
            )
        if not cards:
            return False
        return Markup('<div class="o_avea_promo_card_list">') + Markup("").join(cards) + Markup("</div>")
