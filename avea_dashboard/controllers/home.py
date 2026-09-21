from odoo.addons.web.controllers.home import Home
from odoo.addons.web.controllers.utils import is_user_internal
from odoo.http import request


def _is_web_root(redirect):
    if not redirect:
        return True
    path = redirect.split("?", 1)[0].split("#", 1)[0].rstrip("/")
    return path in ("", "/web", "/odoo")


class AveaHome(Home):
    def _login_redirect(self, uid, redirect=None):
        if not _is_web_root(redirect) or not is_user_internal(uid):
            return super()._login_redirect(uid, redirect=redirect)
        user = request.env["res.users"].sudo().browse(uid)
        home_url = user._avea_home_url()
        if home_url:
            return super()._login_redirect(uid, redirect=home_url)
        return super()._login_redirect(uid, redirect=redirect)
