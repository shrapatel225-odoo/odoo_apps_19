# -*- coding: utf-8 -*-

from odoo import api, fields, models, _


class InventoryNegativeStockProduct(models.Model):
    _name = "inventory.negative.stock.product"
    _description = "Negative Stock Product Summary"
    _order = "last_negative_date desc, current_qty, id"

    name = fields.Char(
        compute="_compute_name",
        store=True,
        help="Product and location used as the dashboard row label.",
    )
    product_id = fields.Many2one(
        "product.product",
        string="Product",
        required=True,
        index=True,
        ondelete="cascade",
        help="Product that experienced at least one negative-stock incident.",
    )
    default_code = fields.Char(
        related="product_id.default_code",
        string="Internal Reference",
        store=True,
    )
    categ_id = fields.Many2one(
        related="product_id.categ_id",
        string="Product Category",
        store=True,
    )
    company_id = fields.Many2one(
        "res.company",
        string="Company",
        required=True,
        index=True,
        default=lambda self: self.env.company,
        help="Company of the analyzed location.",
    )
    location_id = fields.Many2one(
        "stock.location",
        string="Location",
        required=True,
        index=True,
        ondelete="cascade",
        help="Stock location of the incidents shown on this dashboard row.",
    )
    warehouse_id = fields.Many2one(
        "stock.warehouse",
        string="Warehouse",
        index=True,
        help="Warehouse of the location when it can be determined.",
    )
    current_qty = fields.Float(
        string="Current Quantity",
        digits="Product Unit",
        help="Current on-hand quantity at this location from stock quants.",
    )
    lowest_qty = fields.Float(
        string="Lowest Quantity",
        digits="Product Unit",
        help="Most negative running balance detected for this product and location.",
    )
    incident_count = fields.Integer(
        string="Negative Incidents",
        help="Number of separate periods where the running balance crossed below zero.",
    )
    last_negative_date = fields.Datetime(
        string="Last Negative Date",
        help="Date of the most recent negative-creating movement.",
    )
    status = fields.Selection(
        [
            ("active", "Active"),
            ("corrected", "Corrected"),
            ("investigating", "Investigating"),
            ("unknown", "Unknown"),
        ],
        string="Status",
        default="active",
        help="Active when the location is currently negative. Corrected when stock recovered.",
    )
    incident_ids = fields.One2many(
        "inventory.negative.stock.incident",
        "product_summary_id",
        string="Incidents",
        help="Negative-stock incidents detected for this product and location.",
    )

    _product_location_company_unique = models.Constraint(
        "unique(product_id, location_id, company_id)",
        "A summary already exists for this product, location and company.",
    )

    @api.depends("product_id", "location_id")
    def _compute_name(self):
        for rec in self:
            product = rec.product_id.display_name or ""
            location = rec.location_id.complete_name or ""
            rec.name = "%s — %s" % (product, location) if product and location else product or _("Product")

    def action_open_analyzer(self):
        """Open the dashboard client action focused on this product/location."""
        self.ensure_one()
        return {
            "type": "ir.actions.client",
            "tag": "sh_inventory_negative_stock_analyzer.dashboard",
            "name": _("Negative Stock Analyzer"),
            "params": {"summary_id": self.id},
            "target": "current",
        }

    def action_view_incidents(self):
        """Open the incident list for this product and location."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Negative Stock Incidents"),
            "res_model": "inventory.negative.stock.incident",
            "view_mode": "list,form",
            "domain": [("product_summary_id", "=", self.id)],
            "context": {
                "default_product_id": self.product_id.id,
                "default_location_id": self.location_id.id,
                "default_company_id": self.company_id.id,
            },
        }

    def _refresh_current_quantities(self):
        """Refresh stored on-hand quantity from stock.quant without browsing each quant."""
        if not self:
            return
        groups = self.env["stock.quant"]._read_group(
            [
                ("product_id", "in", self.mapped("product_id").ids),
                ("location_id", "in", self.mapped("location_id").ids),
            ],
            groupby=["product_id", "location_id"],
            aggregates=["quantity:sum"],
        )
        qty_map = {
            (product.id, location.id): quantity
            for product, location, quantity in groups
            if product and location
        }
        for rec in self:
            rec.current_qty = qty_map.get((rec.product_id.id, rec.location_id.id), 0.0)
            rec.status = rec._status_from_incidents()

    @api.model
    def _sync_from_incidents(self, product, location, company, warehouse, incidents, lowest_qty=None):
        """Create or update the dashboard row after a product/location scan."""
        if not incidents:
            existing = self.search(
                [
                    ("product_id", "=", product.id),
                    ("location_id", "=", location.id),
                    ("company_id", "=", company.id),
                ]
            )
            if existing:
                existing.unlink()
            return self.browse()

        values = {
            "product_id": product.id,
            "location_id": location.id,
            "company_id": company.id,
            "warehouse_id": warehouse.id if warehouse else False,
            "lowest_qty": lowest_qty
            if lowest_qty is not None
            else min(incidents.mapped("stock_after") or [0.0]),
            "incident_count": len(incidents),
            "last_negative_date": max(
                incidents.mapped("incident_datetime") or [False]
            ),
        }
        record = self.search(
            [
                ("product_id", "=", product.id),
                ("location_id", "=", location.id),
                ("company_id", "=", company.id),
            ],
            limit=1,
        )
        if record:
            record.write(values)
        else:
            record = self.create(values)
        incidents.write({"product_summary_id": record.id})
        record._refresh_current_quantities()
        return record

    def _status_from_incidents(self):
        """Derive the dashboard status from current quantity and incident states."""
        self.ensure_one()
        if self.current_qty < 0:
            return "active"
        states = set(self.incident_ids.mapped("state"))
        if "investigating" in states and not self.incident_ids.filtered(lambda rec: rec.state == "active"):
            return "investigating"
        if self.incident_ids and all(inc.is_corrected or inc.state == "corrected" for inc in self.incident_ids):
            return "corrected"
        if states == {"unknown"} or (not self.incident_ids and self.current_qty >= 0):
            return "unknown"
        return "corrected"
