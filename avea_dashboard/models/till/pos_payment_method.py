from odoo import models


class PosPaymentMethod(models.Model):
    _inherit = "pos.payment.method"

    def _avea_tender_kind(self):
        """Classify a POS tender for correction and cashier-facing styling."""
        self.ensure_one()
        if self.is_avea_store_credit:
            return "store_credit"
        if self.type == "cash" or self.is_cash_count:
            return "cash"
        name = (self.name or "").casefold()
        if self.type == "bank":
            if "eft" in name or "transfer" in name:
                return "eft"
            return "card"
        return "other"

    def _avea_is_open_session_correctable_tender(self):
        return self._avea_tender_kind() in ("cash", "card", "eft")
