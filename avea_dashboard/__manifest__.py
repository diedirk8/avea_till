{
    "name": "Avea Dashboard",
    "summary": "Retail dashboard for Odoo POS — till management, customer credit, and more.",
    "description": """
Avea Dashboard

A modular retail dashboard for Odoo Point of Sale.

Features:
- Session Dashboard
- Cash Ledger and till management
- Customer Credit (foundation)
""",
    "version": "19.0.2.10.15",
    "author": "Avea Software",
    "website": "https://github.com/diedirk8/avea_dashboard",
    "license": "LGPL-3",
    "category": "Point of Sale",
    "depends": [
        "point_of_sale",
        "account",
        "contacts",
    ],
    "data": [
        "security/till/ir.model.access.csv",
        "security/credit/credit_security.xml",
        "security/credit/ir.model.access.csv",
        "data/credit/sequence.xml",
        "data/credit/credit_reason_data.xml",
        "views/till/till_movement_views.xml",
        "views/till/till_dashboard_views.xml",
        "views/till/session_dashboard_views.xml",
        "views/credit/credit_dashboard_views.xml",
        "views/credit/credit_ledger_views.xml",
        "views/credit/credit_issue_wizard_views.xml",
        "views/credit/credit_transactions_views.xml",
        "report/avea_report_layout.xml",
        "report/credit_report_templates.xml",
        "report/avea_report_branding.xml",
        "views/credit/credit_report_wizard_views.xml",
        "views/credit/credit_reason_views.xml",
        "views/credit/credit_config_views.xml",
        "views/res_partner_views.xml",
        "views/menu.xml",
        "views/till/till_menu.xml",
        "views/credit/credit_menu.xml",
    ],
    "assets": {
        "web.report_assets_common": [
            "avea_till/static/src/scss/report/avea_report.scss",
        ],
        "web.assets_backend": [
            "avea_till/static/src/scss/avea_workspace.scss",
            "avea_till/static/src/scss/till/till_dashboard.scss",
            "avea_till/static/src/scss/till/session_dashboard.scss",
            "avea_till/static/src/scss/till/till_ledger_amount.scss",
            "avea_till/static/src/scss/credit/credit_workspace.scss",
            "avea_till/static/src/scss/credit/credit_ledger.scss",
            "avea_till/static/src/credit/fields/credit_ledger_amount/credit_ledger_amount.xml",
            "avea_till/static/src/credit/fields/credit_ledger_amount/credit_ledger_amount.js",
            "avea_till/static/src/till/fields/till_ledger_amount/till_ledger_amount.xml",
            "avea_till/static/src/till/fields/till_ledger_amount/till_ledger_amount.js",
        ],
    },
    "installable": True,
    "application": True,
}
