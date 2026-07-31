"""Module rename migration (disabled).

The module directory is deployed as ``avea_till``. Renaming ``ir_module_module.name``
to ``avea_dashboard`` during upgrade breaks Odoo's module loading because the
technical name must match the addon directory name.

Re-enable only when the addon folder is renamed to ``avea_dashboard``.
"""


def migrate(cr, version):
    pass
