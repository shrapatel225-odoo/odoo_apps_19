# -*- coding: utf-8 -*-

from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    nsa_timeline_window = fields.Integer(
        string="Timeline Window",
        config_parameter="sh_inventory_negative_stock_analyzer.timeline_window",
        default=5,
        help="Number of stock movements shown before and after the negative-creating move.",
    )
    nsa_auto_scan = fields.Boolean(
        string="Automatic Incremental Scan",
        config_parameter="sh_inventory_negative_stock_analyzer.auto_scan",
        default=True,
        help="Run a scheduled scan of current negatives and recent stock movements.",
    )
