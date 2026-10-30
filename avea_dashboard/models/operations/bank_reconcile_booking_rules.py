# -*- coding: utf-8 -*-
"""Suggest how to book unmatched bank statement lines (rules, not auto-posting).

Products like Xero and QuickBooks use **bank rules**: when description contains X,
suggest a category and GL account; the user confirms (or enables auto-apply later).
Avea follows the same pattern — suggestions on each line, one click to book.
"""
import re

from odoo import _, models

from .withdraw_cash_wizard import SALARY_WAGES_ACCOUNT_CODE

# Outflows at or below this amount with a date-only label are treated as bank fees/charges.
_BANK_FEE_MAX_AMOUNT = 100.0

_DATE_ONLY_LABEL = re.compile(
    r"^\s*(\d{1,2}\s+\w{3,9}|\d{4}-\d{2}-\d{2}|\d{2}/\d{2}/\d{4})\s*$",
    re.IGNORECASE,
)

_KEYWORD_RULES = (
    {
        "keys": (
            "accrued bank",
            "bank charge",
            "bank fee",
            "service fee",
            "monthly fee",
            "admin fee",
            "transaction fee",
            "cash handling",
        ),
        "label": "Record as bank charge",
        "import_action": "expense",
        "account_codes": (),
        "account_names": ("bank charge", "bank fee", "bank cost", "finance charge"),
        "partner_role": "bank",
    },
    {
        "keys": ("salary", "wages", "payroll", "payshap"),
        "label": "Record salary / wages payment",
        "import_action": "expense",
        "account_codes": (SALARY_WAGES_ACCOUNT_CODE,),
        "account_names": ("salary", "wages", "payroll"),
        "require_any": ("salary", "wages", "payroll"),
        "partner_role": "employee",
    },
    {
        "keys": (
            "fuel",
            "petrol",
            "diesel",
            "engen",
            "shell",
            "sasol",
            " bp ",
            "total energies",
            "garage",
        ),
        "label": "Record as fuel expense",
        "import_action": "expense",
        "account_codes": (),
        "account_names": ("fuel", "petrol", "diesel", "vehicle"),
        "partner_role": "merchant",
    },
    {
        "keys": (
            "prepaid airtime",
            "airtime",
            "vodacom",
            "mtn",
            "cell c",
            "telkom mobile",
        ),
        "label": "Record as telephone / airtime",
        "import_action": "expense",
        "account_codes": (),
        "account_names": ("telephone", "airtime", "mobile", "communication"),
    },
    {
        "keys": (
            "checkers",
            "pick n pay",
            "shoprite",
            "woolworths",
            "spar",
            "sixty60",
            "pos purchase",
        ),
        "label": "Record as retail / operating expense",
        "import_action": "expense",
        "account_codes": (),
        "account_names": ("office", "operating", "general expense", "consumables"),
    },
    {
        "keys": ("rent", "lease"),
        "label": "Record as rent expense",
        "import_action": "expense",
        "account_codes": (),
        "account_names": ("rent", "lease"),
    },
    {
        "keys": ("insurance", "discovery", "outsurance"),
        "label": "Record as insurance expense",
        "import_action": "expense",
        "account_codes": (),
        "account_names": ("insurance",),
    },
    {
        "keys": (
            "payment from",
            "deposit",
            "customer payment",
            "eft credit",
            "received from",
        ),
        "label": "Record as customer / other income",
        "import_action": "income",
        "account_codes": (),
        "account_names": ("sales", "income", "other income"),
        "income": True,
    },
)


class AveaBankReconcileBookingRules(models.AbstractModel):
    _name = "avea.bank.reconcile.booking.rules"
    _description = "Bank reconciliation booking suggestions"

    @classmethod
    def _avea_blob(cls, description, reference):
        return " ".join(filter(None, [(description or ""), (reference or "")])).lower()

    @classmethod
    def _avea_is_date_only_label(cls, description, bank_date):
        text = (description or "").strip()
        if not text:
            return True
        if _DATE_ONLY_LABEL.match(text):
            return True
        if bank_date:
            for fmt in ("%d %b", "%d %B", "%d/%m/%Y", "%Y-%m-%d"):
                try:
                    if text.lower() == bank_date.strftime(fmt).lower():
                        return True
                except (TypeError, ValueError):
                    continue
        return False

    @classmethod
    def _avea_match_keywords(cls, blob, rule):
        if not any(key in blob for key in rule["keys"]):
            return False
        required = rule.get("require_any")
        if required and not any(token in blob for token in required):
            return False
        return True

    @classmethod
    def infer(cls, env, *, company, description, reference, amount, bank_date, currency):
        """Return dict with booking_suggestion, import_action, expense/income account ids."""
        currency = currency or company.currency_id
        blob = cls._avea_blob(description, reference)
        result = {
            "booking_suggestion": False,
            "import_action": False,
            "suggested_expense_account_id": False,
            "suggested_income_account_id": False,
            "partner_role": "supplier",
            "matched_rule": None,
        }
        if currency.compare_amounts(amount, 0.0) == 0:
            result["import_action"] = "skip"
            result["booking_suggestion"] = _("No amount — skip")
            return result

        matched_rule = None
        if currency.compare_amounts(amount, 0.0) < 0:
            if cls._avea_is_date_only_label(description, bank_date) and abs(amount) <= _BANK_FEE_MAX_AMOUNT:
                matched_rule = _KEYWORD_RULES[0]
            else:
                for rule in _KEYWORD_RULES:
                    if rule.get("income"):
                        continue
                    if cls._avea_match_keywords(blob, rule):
                        matched_rule = rule
                        break
            if not matched_rule:
                result["import_action"] = "expense"
                result["booking_suggestion"] = _("Record expense")
                return result
        else:
            for rule in _KEYWORD_RULES:
                if not rule.get("income"):
                    continue
                if cls._avea_match_keywords(blob, rule):
                    matched_rule = rule
                    break
            if not matched_rule:
                result["import_action"] = "income"
                result["booking_suggestion"] = _("Record income")
                return result

        result["import_action"] = matched_rule["import_action"]
        result["booking_suggestion"] = _(matched_rule["label"])
        result["partner_role"] = matched_rule.get("partner_role", "supplier")
        result["matched_rule"] = matched_rule
        Account = env["account.account"].sudo()
        if matched_rule.get("income"):
            account = cls._avea_resolve_account(
                Account, company, matched_rule, income=True
            )
            result["suggested_income_account_id"] = account.id if account else False
        else:
            account = cls._avea_resolve_account(
                Account, company, matched_rule, income=False
            )
            result["suggested_expense_account_id"] = account.id if account else False
        return result

    @classmethod
    def _avea_resolve_account(cls, Account, company, rule, income=False):
        types = ("income", "income_other") if income else (
            "expense",
            "expense_other",
            "expense_direct_cost",
        )
        base_domain = [
            ("active", "=", True),
            ("account_type", "in", types),
            ("company_ids", "in", company.id),
        ]
        for code in rule.get("account_codes") or ():
            account = Account.search([("code", "=", code)] + base_domain, limit=1)
            if account:
                return account
        for hint in rule.get("account_names") or ():
            account = Account.search(
                base_domain + [("name", "ilike", hint)],
                limit=1,
            )
            if account:
                return account
        return Account.browse()

    @classmethod
    def _avea_extract_employee_name(cls, description):
        text = re.sub(r"(?i)payshap account off-us", "", (description or "")).strip()
        text = re.sub(r"(?i)payshap", "", text).strip()
        text = re.sub(r"(?i)\b(salary|wages|payroll)\b", "", text).strip()
        text = re.sub(r"\s+", " ", text)
        return text if len(text) >= 2 else False

    @classmethod
    def _avea_extract_merchant_name(cls, description):
        text = (description or "").strip()
        match = re.search(r"(?i)pos purchase\s+(.+)", text)
        if match:
            return match.group(1).strip()
        match = re.search(r"(?i)(?:payment to|paid to)\s+(.+)", text)
        if match:
            return match.group(1).strip()
        return False

    @classmethod
    def suggest_partner(cls, env, *, company, partner_role, description, reference):
        """Best-effort payee for vendor bill + bank payment (not a product supplier)."""
        Partner = env["res.partner"].sudo()
        company_domain = [
            "|",
            ("company_id", "=", False),
            ("company_id", "in", company.id),
        ]

        def _search_name(name, *, prefer_supplier=False, prefer_person=False):
            if not name or len(name) < 2:
                return Partner.browse()
            domain = company_domain + [("name", "ilike", name)]
            if prefer_supplier:
                domain.append(("supplier_rank", ">", 0))
            candidates = Partner.search(domain, limit=8)
            if prefer_person:
                people = candidates.filtered(lambda partner: not partner.is_company)
                if people:
                    return people[0]
            exact = candidates.filtered(
                lambda partner: partner.name.strip().lower() == name.lower()
            )
            if exact:
                return exact[0]
            return candidates[:1]

        if partner_role == "employee":
            payee = cls._avea_extract_employee_name(description)
            if payee:
                partner = _search_name(payee, prefer_person=True)
                if partner:
                    return partner
                if " " in payee:
                    partner = _search_name(payee.split()[-1], prefer_person=True)
                    if partner:
                        return partner
            return Partner.browse()

        if partner_role == "bank":
            for term in ("First National Bank", "FNB"):
                partner = _search_name(term, prefer_supplier=True)
                if partner:
                    return partner
            return Partner.browse()

        if partner_role == "merchant":
            merchant = cls._avea_extract_merchant_name(description)
            if merchant:
                partner = _search_name(merchant, prefer_supplier=True)
                if partner:
                    return partner
                token = merchant.split()[0].strip("*")
                if len(token) >= 3:
                    partner = _search_name(token, prefer_supplier=True)
                    if partner:
                        return partner
            return Partner.browse()

        return Partner.browse()

    @classmethod
    def partner_hint_for_role(cls, partner_role):
        if partner_role == "employee":
            return _(
                "Salary is paid to a person, not a shop. Choose the employee "
                "(or type their name to add them). Odoo needs a payee contact "
                "to post the payment."
            )
        if partner_role == "bank":
            return _(
                "Bank charges are usually posted to your bank as payee "
                "(e.g. FNB). Search FNB or add them once if missing."
            )
        return False
