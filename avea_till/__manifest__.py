{
    "name": "Avea Till",
    "summary": "Professional till ledger and cash management for Odoo POS.",
    "description": """
Avea Till

A professional till ledger for Odoo Point of Sale.

Features:
- Live till balance
- Cash ledger
- Cash In / Cash Out
- Dashboard
""",
    "version": "19.0.1.0.0",
    "author": "Avea Software",
    "website": "https://github.com/diedirk8/avea_till",
    "license": "LGPL-3",
    "category": "Point of Sale",
    "depends": [
        "point_of_sale",
        "account",
    ],
    "data": [
        "security/ir.model.access.csv",
        "views/till_movement_views.xml",
        "views/till_dashboard_views.xml",
        "views/menu.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "avea_till/static/src/scss/till_dashboard.scss",
        ],
    },
    "installable": True,
    "application": True,
}
