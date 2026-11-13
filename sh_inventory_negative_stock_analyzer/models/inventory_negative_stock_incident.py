# -*- coding: utf-8 -*-

import logging
from datetime import timedelta

from odoo import api, fields, models, _
from odoo.tools.float_utils import float_compare, float_is_zero

_logger = logging.getLogger(__name__)

TIMELINE_DEFAULT_WINDOW = 5
DASHBOARD_PRODUCT_LIMIT = 200
MOVE_READ_FIELDS = [
    "id",
    "date",
    "quantity",
    "product_uom_qty",
    "location_id",
    "location_dest_id",
    "picking_id",
    "picking_type_id",
    "origin",
    "reference",
    "company_id",
    "product_id",
    "state",
]


class InventoryNegativeStockIncident(models.Model):
    _name = "inventory.negative.stock.incident"
    _description = "Negative Stock Incident"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "incident_datetime desc, id desc"
    _rec_name = "name"

    name = fields.Char(
        string="Reference",
        required=True,
        copy=False,
        default=lambda self: _("New"),
        help="Unique incident reference generated on scan.",
    )
    incident_number = fields.Integer(
        string="Incident Number",
        help="Sequence of this incident for the same product, location and company.",
    )
    product_id = fields.Many2one(
        "product.product",
        string="Product",
        required=True,
        index=True,
        ondelete="cascade",
        help="Product that went negative at the analyzed location.",
    )
    product_default_code = fields.Char(
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
        help="Company of the stock movements used for this incident.",
    )
    location_id = fields.Many2one(
        "stock.location",
        string="Location",
        required=True,
        index=True,
        ondelete="cascade",
        help="Stock location where the running balance crossed below zero.",
    )
    warehouse_id = fields.Many2one(
        "stock.warehouse",
        string="Warehouse",
        index=True,
        help="Warehouse of the location when it can be determined.",
    )
    negative_qty = fields.Float(
        string="Negative Quantity",
        digits="Product Unit",
        help="Running balance immediately after the triggering movement.",
    )
    stock_before = fields.Float(
        string="Stock Before",
        digits="Product Unit",
        help="Running inventory balance at the location just before the triggering movement.",
    )
    stock_after = fields.Float(
        string="Stock After",
        digits="Product Unit",
        help="Running inventory balance at the location just after the triggering movement.",
    )
    movement_qty = fields.Float(
        string="Movement Quantity",
        digits="Product Unit",
        help="Signed quantity of the triggering movement at the analyzed location.",
    )
    trigger_move_id = fields.Many2one(
        "stock.move",
        string="Negative-Creating Movement",
        index=True,
        ondelete="set null",
        help="Exact stock move where the running balance changed from >= 0 to < 0.",
    )
    trigger_picking_id = fields.Many2one(
        "stock.picking",
        string="Picking",
        index=True,
        ondelete="set null",
        help="Transfer that contains the triggering stock movement, when available.",
    )
    origin_document_name = fields.Char(
        string="Source Document",
        help="Display name of the related sales order, purchase order or other origin.",
    )
    origin_document_model = fields.Char(
        string="Source Document Model",
        help="Technical model of the related business document, when discovered.",
    )
    origin_document_res_id = fields.Integer(
        string="Source Document ID",
        help="Database id of the related business document, when discovered.",
    )
    picking_type_code = fields.Selection(
        related="trigger_picking_id.picking_type_code",
        string="Movement Type",
        store=True,
    )
    root_cause_type = fields.Selection(
        [
            ("insufficient_stock", "Insufficient Stock"),
            ("reservation_issue", "Reservation Issue"),
            ("sequence_timing", "Sequence / Timing Issue"),
            ("transfer_issue", "Transfer Issue"),
            ("inventory_adjustment", "Inventory Adjustment"),
            ("manual_unidentified", "Manual / Unidentified Movement"),
            ("unknown", "Unknown"),
        ],
        string="Root Cause",
        default="unknown",
        tracking=True,
        help="Generic classification of why the location went negative.",
    )
    root_cause_description = fields.Text(
        string="Explanation",
        help="Generated explanation based on the movement history and related documents.",
    )
    incident_datetime = fields.Datetime(
        string="Incident Date",
        index=True,
        help="Date and time of the movement that created the negative stock.",
    )
    corrected_datetime = fields.Datetime(
        string="Corrected Date",
        help="Date and time when the running balance returned to zero or positive.",
    )
    is_corrected = fields.Boolean(
        string="Corrected",
        help="The location later returned to a zero or positive running balance.",
    )
    state = fields.Selection(
        [
            ("active", "Active"),
            ("corrected", "Corrected"),
            ("investigating", "Investigating"),
            ("unknown", "Unknown"),
        ],
        string="Status",
        default="active",
        tracking=True,
        help="Active means the location is still negative. Corrected means stock later recovered.",
    )
    product_summary_id = fields.Many2one(
        "inventory.negative.stock.product",
        string="Product Summary",
        ondelete="set null",
        help="Dashboard row grouping this incident by product, location and company.",
    )
    current_qty = fields.Float(
        related="product_summary_id.current_qty",
        string="Current Quantity",
    )
    chain_json = fields.Json(
        string="Root Cause Chain",
        help="Structured chain nodes rendered by the OWL component.",
    )
    timeline_json = fields.Json(
        string="Stock Timeline",
        help="Limited surrounding movements for the selected incident.",
    )

    _trigger_location_unique = models.Constraint(
        "unique(trigger_move_id, location_id)",
        "An incident already exists for this movement and location.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code(
                    "inventory.negative.stock.incident"
                ) or _("New")
        return super().create(vals_list)

    def action_open_trigger_move(self):
        """Open the stock movement that created the negative quantity."""
        self.ensure_one()
        return self._action_open_record("stock.move", self.trigger_move_id.id)

    def action_open_picking(self):
        """Open the related picking when one exists."""
        self.ensure_one()
        return self._action_open_record("stock.picking", self.trigger_picking_id.id)

    def action_open_source_document(self):
        """Open the related sales order, purchase order or other origin document."""
        self.ensure_one()
        return self._action_open_record(
            self.origin_document_model, self.origin_document_res_id
        )

    def action_view_full_stock_history(self):
        """Open the standard stock move list for this product and location."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Stock History"),
            "res_model": "stock.move",
            "view_mode": "list,form",
            "domain": [
                ("product_id", "=", self.product_id.id),
                ("state", "=", "done"),
                "|",
                ("location_id", "=", self.location_id.id),
                ("location_dest_id", "=", self.location_id.id),
            ],
            "context": {
                "search_default_done": 1,
                "default_product_id": self.product_id.id,
            },
        }

    @api.model
    def get_filter_options(self):
        """Return lightweight lists used by the dashboard filter bar."""
        companies = self.env["res.company"].search([("id", "in", self.env.companies.ids)])
        warehouses = self.env["stock.warehouse"].search(
            [("company_id", "in", self.env.companies.ids)]
        )
        locations = self.env["stock.location"].search(
            [
                ("usage", "=", "internal"),
                "|",
                ("company_id", "in", self.env.companies.ids),
                ("company_id", "=", False),
            ],
            limit=500,
        )
        categories = self.env["product.category"].search([], limit=200)
        return {
            "companies": [{"id": rec.id, "name": rec.name} for rec in companies],
            "categories": [{"id": rec.id, "name": rec.complete_name} for rec in categories],
            "warehouses": [
                {"id": rec.id, "name": rec.name, "company_id": rec.company_id.id}
                for rec in warehouses
            ],
            "locations": [
                {
                    "id": rec.id,
                    "name": rec.complete_name or rec.name,
                    "warehouse_id": rec.warehouse_id.id,
                    "company_id": rec.company_id.id,
                }
                for rec in locations
            ],
            "root_causes": [
                {"id": key, "name": label}
                for key, label in self._fields["root_cause_type"].selection
            ],
            "states": [
                {"id": key, "name": label} for key, label in self._fields["state"].selection
            ],
            "current_company_id": self.env.company.id,
            "timeline_window": self._timeline_window(),
        }

    @api.model
    def get_dashboard_products(self, filters=None):
        """Return product/location rows that have at least one negative incident."""
        filters = filters or {}
        Summary = self.env["inventory.negative.stock.product"]
        if filters.get("refresh_current"):
            Summary.search(self._summary_domain(filters))._refresh_current_quantities()
        records = Summary.search(
            self._summary_domain(filters),
            limit=DASHBOARD_PRODUCT_LIMIT,
            order="last_negative_date desc, current_qty, id",
        )
        return [self._serialize_product_row(rec) for rec in records]

    @api.model
    def get_product_analysis(self, summary_id):
        """Return incidents for one product/location, grouped for the analysis panel."""
        summary = self.env["inventory.negative.stock.product"].browse(summary_id).exists()
        if not summary:
            return {}
        siblings = self.env["inventory.negative.stock.product"].search(
            [
                ("product_id", "=", summary.product_id.id),
                ("company_id", "=", summary.company_id.id),
            ],
            order="location_id",
        )
        location_groups = []
        for sibling in siblings:
            incidents = sibling.incident_ids.sorted(
                key=lambda rec: (rec.incident_datetime or rec.create_date, rec.id)
            )
            location_groups.append(
                {
                    "summary_id": sibling.id,
                    "location_id": sibling.location_id.id,
                    "location_name": sibling.location_id.complete_name,
                    "warehouse_name": sibling.warehouse_id.display_name or "",
                    "current_qty": sibling.current_qty,
                    "status": sibling.status,
                    "is_selected": sibling.id == summary.id,
                    "incidents": [self._serialize_incident_row(inc) for inc in incidents],
                }
            )
        return {
            "product": self._serialize_product_row(summary),
            "locations": location_groups,
        }

    @api.model
    def get_incident_analysis(self, incident_id):
        """Return the chain, timeline and explanation for one incident."""
        incident = self.browse(incident_id).exists()
        if not incident:
            return {}
        if not incident.chain_json or not incident.timeline_json:
            incident._rebuild_analysis_payload()
        return {
            "incident": self._serialize_incident_row(incident),
            "summary": {
                "product": incident.product_id.display_name,
                "product_code": incident.product_default_code or "",
                "location": incident.location_id.complete_name,
                "warehouse": incident.warehouse_id.display_name or "",
                "negative_qty": incident.negative_qty,
                "stock_before": incident.stock_before,
                "stock_after": incident.stock_after,
                "movement_qty": incident.movement_qty,
                "trigger_move": incident.trigger_move_id.display_name or "",
                "trigger_move_id": incident.trigger_move_id.id,
                "picking": incident.trigger_picking_id.display_name or "",
                "picking_id": incident.trigger_picking_id.id,
                "movement_type": incident._movement_type_label(),
                "root_cause": dict(self._fields["root_cause_type"].selection).get(
                    incident.root_cause_type, ""
                ),
                "root_cause_type": incident.root_cause_type,
                "explanation": incident.root_cause_description or "",
                "state": incident.state,
                "is_corrected": incident.is_corrected,
            },
            "chain": incident.chain_json or [],
            "timeline": incident.timeline_json or [],
            "related_documents": incident._related_document_links(),
            "history_action": incident.action_view_full_stock_history(),
        }

    @api.model
    def scan_negative_stock(self, filters=None):
        """Scan stock movement history and create or update incidents.

        Analysis is always performed server-side. The browser only receives
        the refreshed dashboard product list.
        """
        filters = filters or {}
        keys = self._collect_scan_keys(filters)
        created = 0
        updated = 0
        for product_id, location_id, company_id in keys:
            result = self._analyze_product_location(product_id, location_id, company_id)
            created += result["created"]
            updated += result["updated"]
        products = self.get_dashboard_products(filters)
        return {
            "created": created,
            "updated": updated,
            "analyzed": len(keys),
            "products": products,
        }

    @api.model
    def _cron_scan_negative_stock(self):
        """Refresh current negatives and recent movement history."""
        if not self._auto_scan_enabled():
            return
        self.scan_negative_stock(
            {
                "include_historical": True,
                "recent_only": True,
                "refresh_current": True,
            }
        )

    def _analyze_product_location(self, product_id, location_id, company_id):
        """Walk chronological moves and persist every >=0 to <0 crossing."""
        product = self.env["product.product"].browse(product_id)
        location = self.env["stock.location"].browse(location_id)
        company = self.env["res.company"].browse(company_id)
        if not product.exists() or not location.exists() or not company.exists():
            return {"created": 0, "updated": 0}

        move_rows = self._search_location_move_rows(product, location, company)
        if not move_rows:
            return {"created": 0, "updated": 0}

        rounding = product.uom_id.rounding or 0.01
        warehouse = self._warehouse_for_location(location)
        detected = []
        open_incident = None
        balance = 0.0
        lowest_qty = 0.0
        for index, row in enumerate(move_rows):
            qty = self._signed_qty_from_row(row, location.id)
            if float_is_zero(qty, precision_rounding=rounding):
                continue
            stock_before = balance
            stock_after = balance + qty
            if float_compare(stock_after, lowest_qty, precision_rounding=rounding) < 0:
                lowest_qty = stock_after
            crossed_negative = (
                float_compare(stock_before, 0.0, precision_rounding=rounding) >= 0
                and float_compare(stock_after, 0.0, precision_rounding=rounding) < 0
            )
            recovered = (
                open_incident
                and float_compare(stock_before, 0.0, precision_rounding=rounding) < 0
                and float_compare(stock_after, 0.0, precision_rounding=rounding) >= 0
            )
            if crossed_negative:
                open_incident = {
                    "index": index,
                    "move_id": row["id"],
                    "stock_before": stock_before,
                    "stock_after": stock_after,
                    "movement_qty": qty,
                    "incident_datetime": row["date"],
                    "is_corrected": False,
                    "corrected_datetime": False,
                }
                detected.append(open_incident)
            if recovered and open_incident:
                open_incident["is_corrected"] = True
                open_incident["corrected_datetime"] = row["date"]
                open_incident = None
            balance = stock_after

        needed_ids = {item["move_id"] for item in detected}
        window = self._timeline_window()
        for item in detected:
            start = max(0, item["index"] - window)
            end = item["index"] + window + 1
            needed_ids.update(row["id"] for row in move_rows[start:end])
        moves = self.env["stock.move"].browse(list(needed_ids))
        return self._upsert_incidents(
            product, location, company, warehouse, moves, move_rows, detected, rounding, lowest_qty
        )

    def _upsert_incidents(
        self,
        product,
        location,
        company,
        warehouse,
        moves,
        move_rows,
        detected,
        rounding,
        lowest_qty=0.0,
    ):
        """Create or update incident records for one product/location pair."""
        created = 0
        updated = 0
        existing = self.search(
            [
                ("product_id", "=", product.id),
                ("location_id", "=", location.id),
                ("company_id", "=", company.id),
            ]
        )
        existing_by_move = {rec.trigger_move_id.id: rec for rec in existing if rec.trigger_move_id}
        keep_ids = self.env["inventory.negative.stock.incident"]
        move_map = {move.id: move for move in moves}
        for number, data in enumerate(detected, start=1):
            move = move_map.get(data["move_id"])
            if not move:
                continue
            source = self._find_source_document(move)
            cause_type, description, state = self._classify_root_cause(
                move, data, moves, move_rows, location, rounding
            )
            values = {
                "incident_number": number,
                "product_id": product.id,
                "company_id": company.id,
                "location_id": location.id,
                "warehouse_id": warehouse.id if warehouse else False,
                "negative_qty": data["stock_after"],
                "stock_before": data["stock_before"],
                "stock_after": data["stock_after"],
                "movement_qty": data["movement_qty"],
                "trigger_move_id": move.id,
                "trigger_picking_id": move.picking_id.id,
                "origin_document_name": source.get("name", ""),
                "origin_document_model": source.get("res_model") or False,
                "origin_document_res_id": source.get("res_id") or 0,
                "root_cause_type": cause_type,
                "root_cause_description": description,
                "incident_datetime": data["incident_datetime"],
                "corrected_datetime": data["corrected_datetime"] or False,
                "is_corrected": data["is_corrected"],
                "state": "corrected" if data["is_corrected"] else state,
                "chain_json": self._build_chain(move, data, source),
                "timeline_json": self._build_timeline(
                    move_rows, move_map, data["index"], location, rounding
                ),
            }
            record = existing_by_move.get(move.id)
            if record:
                record.write(values)
                updated += 1
            else:
                record = self.create(values)
                created += 1
            keep_ids |= record

        obsolete = existing - keep_ids
        if obsolete:
            obsolete.unlink()

        self.env["inventory.negative.stock.product"]._sync_from_incidents(
            product, location, company, warehouse, keep_ids, lowest_qty=lowest_qty
        )
        return {"created": created, "updated": updated}

    def _search_location_moves(self, product, location, company):
        """Return done moves that change quantity at the given location."""
        domain = self._location_move_domain(product, location, company)
        return self.env["stock.move"].search(domain, order="date asc, id asc")

    def _search_location_move_rows(self, product, location, company):
        """Read only the fields needed to compute a running balance."""
        fields_to_read = [name for name in MOVE_READ_FIELDS if name in self.env["stock.move"]._fields]
        return self.env["stock.move"].search_read(
            self._location_move_domain(product, location, company),
            fields_to_read,
            order="date asc, id asc",
        )

    def _location_move_domain(self, product, location, company):
        return [
            ("product_id", "=", product.id),
            ("company_id", "=", company.id),
            ("state", "=", "done"),
            "|",
            ("location_id", "=", location.id),
            ("location_dest_id", "=", location.id),
        ]

    def _signed_qty_at_location(self, move, location):
        """Return signed done quantity of a move relative to one location."""
        return self._signed_qty_from_row(
            {
                "quantity": move.quantity,
                "location_id": (move.location_id.id, move.location_id.display_name),
                "location_dest_id": (move.location_dest_id.id, move.location_dest_id.display_name),
            },
            location.id,
        )

    def _signed_qty_from_row(self, row, location_id):
        """Return signed done quantity from a search_read row."""
        qty = row.get("quantity") or 0.0
        src = row["location_id"][0] if row.get("location_id") else False
        dest = row["location_dest_id"][0] if row.get("location_dest_id") else False
        if dest == location_id and src != location_id:
            return qty
        if src == location_id and dest != location_id:
            return -qty
        return 0.0

    def _collect_scan_keys(self, filters):
        """Collect distinct product/location/company keys that should be analyzed."""
        keys = set()
        keys.update(self._keys_from_negative_quants(filters))
        if filters.get("include_historical"):
            keys.update(self._keys_from_done_moves(filters))
        if filters.get("product_id"):
            keys = {key for key in keys if key[0] == filters["product_id"]}
        if filters.get("location_id"):
            keys = {key for key in keys if key[1] == filters["location_id"]}
        if filters.get("company_id"):
            keys = {key for key in keys if key[2] == filters["company_id"]}
        if filters.get("warehouse_id"):
            warehouse = self.env["stock.warehouse"].browse(filters["warehouse_id"])
            location_ids = set(
                self.env["stock.location"].search(
                    [("id", "child_of", warehouse.view_location_id.id)]
                ).ids
            )
            keys = {key for key in keys if key[1] in location_ids}
        return keys

    def _keys_from_negative_quants(self, filters):
        """Keys for locations that are currently negative."""
        domain = [
            ("location_id.usage", "=", "internal"),
            ("quantity", "<", 0),
            ("company_id", "in", self.env.companies.ids),
        ]
        domain += self._storable_product_domain()
        domain += self._quant_filter_domain(filters)
        groups = self.env["stock.quant"]._read_group(
            domain,
            groupby=["product_id", "location_id", "company_id"],
        )
        return {
            (product.id, location.id, company.id)
            for product, location, company in groups
            if product and location and company
        }

    def _keys_from_done_moves(self, filters):
        """Keys from done outgoing moves, used to detect historical negatives."""
        domain = [
            ("state", "=", "done"),
            ("location_id.usage", "=", "internal"),
            ("company_id", "in", self.env.companies.ids),
        ]
        domain += self._storable_product_domain()
        if filters.get("recent_only"):
            recent = fields.Datetime.now() - timedelta(days=2)
            domain.append(("date", ">=", recent))
        if filters.get("date_from"):
            domain.append(("date", ">=", filters["date_from"]))
        if filters.get("date_to"):
            domain.append(("date", "<=", filters["date_to"]))
        if filters.get("product_id"):
            domain.append(("product_id", "=", filters["product_id"]))
        if filters.get("categ_id"):
            domain.append(("product_id.categ_id", "=", filters["categ_id"]))
        groups = self.env["stock.move"]._read_group(
            domain,
            groupby=["product_id", "location_id", "company_id"],
        )
        return {
            (product.id, location.id, company.id)
            for product, location, company in groups
            if product and location and company
        }

    def _quant_filter_domain(self, filters):
        domain = []
        if filters.get("product_id"):
            domain.append(("product_id", "=", filters["product_id"]))
        if filters.get("categ_id"):
            domain.append(("product_id.categ_id", "=", filters["categ_id"]))
        if filters.get("location_id"):
            domain.append(("location_id", "=", filters["location_id"]))
        if filters.get("company_id"):
            domain.append(("company_id", "=", filters["company_id"]))
        if filters.get("warehouse_id"):
            warehouse = self.env["stock.warehouse"].browse(filters["warehouse_id"])
            if warehouse.view_location_id:
                domain.append(("location_id", "child_of", warehouse.view_location_id.id))
        return domain

    def _storable_product_domain(self):
        """Restrict analysis to storable (is_storable) products."""
        return [("product_id.is_storable", "=", True)]

    def _summary_domain(self, filters):
        domain = [("company_id", "in", self.env.companies.ids)]
        if filters.get("company_id"):
            domain.append(("company_id", "=", filters["company_id"]))
        if filters.get("warehouse_id"):
            domain.append(("warehouse_id", "=", filters["warehouse_id"]))
        if filters.get("location_id"):
            domain.append(("location_id", "=", filters["location_id"]))
        if filters.get("product_id"):
            domain.append(("product_id", "=", filters["product_id"]))
        if filters.get("categ_id"):
            domain.append(("categ_id", "=", filters["categ_id"]))
        if filters.get("search"):
            search = filters["search"]
            domain += [
                "|",
                ("product_id.name", "ilike", search),
                ("product_id.default_code", "ilike", search),
            ]
        if filters.get("stock_scope") == "current":
            domain.append(("current_qty", "<", 0))
        elif filters.get("stock_scope") == "historical":
            domain.append(("current_qty", ">=", 0))
        if filters.get("state"):
            domain.append(("status", "=", filters["state"]))
        if filters.get("root_cause_type") or filters.get("date_from") or filters.get("date_to"):
            incident_domain = []
            if filters.get("root_cause_type"):
                incident_domain.append(("root_cause_type", "=", filters["root_cause_type"]))
            if filters.get("date_from"):
                incident_domain.append(("incident_datetime", ">=", filters["date_from"]))
            if filters.get("date_to"):
                incident_domain.append(("incident_datetime", "<=", filters["date_to"]))
            incident_ids = self.search(incident_domain).ids
            domain.append(("incident_ids", "in", incident_ids or [0]))
        return domain

    def _classify_root_cause(self, move, data, moves, move_rows, location, rounding):
        """Classify the incident using only standard movement and document data."""
        stock_before = data["stock_before"]
        movement_qty = data["movement_qty"]
        index = data["index"]

        if self._is_inventory_move(move):
            return (
                "inventory_adjustment",
                self._explanation_inventory(move, data),
                "active",
            )

        if move.picking_id and move.picking_id.picking_type_code == "internal":
            return (
                "transfer_issue",
                self._explanation_transfer(move, data),
                "active",
            )

        upcoming_in = self._upcoming_incoming(move_rows, moves, index, location, rounding)
        if upcoming_in and float_compare(stock_before, abs(movement_qty), precision_rounding=rounding) < 0:
            return (
                "sequence_timing",
                self._explanation_timing(move, data, upcoming_in),
                "active",
            )

        if self._looks_like_reservation_issue(move, stock_before, rounding):
            return (
                "reservation_issue",
                self._explanation_reservation(move, data),
                "investigating",
            )

        if float_compare(abs(movement_qty), stock_before, precision_rounding=rounding) > 0:
            return (
                "insufficient_stock",
                self._explanation_insufficient(move, data),
                "active",
            )

        if not move.picking_id:
            return (
                "manual_unidentified",
                self._explanation_manual(move, data),
                "unknown",
            )

        return (
            "unknown",
            self._explanation_unknown(move, data),
            "unknown",
        )

    def _is_inventory_move(self, move):
        """Return True when the move is an inventory adjustment or scrap to inventory."""
        if "is_inventory" in move._fields and move.is_inventory:
            return True
        dest_usage = move.location_dest_id.usage
        src_usage = move.location_id.usage
        return dest_usage == "inventory" or src_usage == "inventory"

    def _looks_like_reservation_issue(self, move, stock_before, rounding):
        """Detect a done consumption that was not fully reserved beforehand.

        After a move is done, reservation data is limited. Only classify this
        when demand existed and the pre-move balance could not cover it, and
        move lines show no reserved quantity history we can trust. If the
        information is insufficient, return False so the cause stays generic.
        """
        demand = move.product_uom_qty or 0.0
        if float_compare(demand, 0.0, precision_rounding=rounding) <= 0:
            return False
        if float_compare(stock_before, demand, precision_rounding=rounding) >= 0:
            return False
        if not move.picking_id:
            return False
        if "forecast_availability" in move._fields:
            forecast = move.forecast_availability
            if forecast is not False and float_compare(
                forecast, demand, precision_rounding=rounding
            ) < 0:
                return True
        return False

    def _upcoming_incoming(self, move_rows, moves, index, location, rounding):
        """Return the next incoming move at the same location, if any."""
        window = self._timeline_window()
        move_map = {move.id: move for move in moves}
        for row in move_rows[index + 1 : index + 1 + window]:
            qty = self._signed_qty_from_row(row, location.id)
            if float_compare(qty, 0.0, precision_rounding=rounding) > 0:
                return move_map.get(row["id"]) or self.env["stock.move"].browse(row["id"])
        return self.env["stock.move"]

    def _find_source_document(self, move):
        """Discover a related standard business document without assuming a flow."""
        if "sale_line_id" in move._fields and move.sale_line_id:
            order = move.sale_line_id.order_id
            if order and self._can_read(order):
                return self._document_node("sale_order", order, _("Sales Order"))
        if "purchase_line_id" in move._fields and move.purchase_line_id:
            order = move.purchase_line_id.order_id
            if order and self._can_read(order):
                return self._document_node("purchase_order", order, _("Purchase Order"))
        if "raw_material_production_id" in move._fields and move.raw_material_production_id:
            production = move.raw_material_production_id
            if self._can_read(production):
                return self._document_node("production", production, _("Manufacturing Order"))
        if "production_id" in move._fields and move.production_id:
            production = move.production_id
            if self._can_read(production):
                return self._document_node("production", production, _("Manufacturing Order"))

        picking = move.picking_id
        if picking:
            if "sale_id" in picking._fields and picking.sale_id and self._can_read(picking.sale_id):
                return self._document_node("sale_order", picking.sale_id, _("Sales Order"))
            if "purchase_id" in picking._fields and picking.purchase_id and self._can_read(
                picking.purchase_id
            ):
                return self._document_node(
                    "purchase_order", picking.purchase_id, _("Purchase Order")
                )
            references = picking.reference_ids if "reference_ids" in picking._fields else False
            if references and "sale_ids" in references._fields:
                sale_order = references.sale_ids[:1]
                if sale_order and self._can_read(sale_order):
                    return self._document_node("sale_order", sale_order, _("Sales Order"))
            if references and "purchase_ids" in references._fields:
                purchase_order = references.purchase_ids[:1]
                if purchase_order and self._can_read(purchase_order):
                    return self._document_node(
                        "purchase_order", purchase_order, _("Purchase Order")
                    )
        if move.origin:
            return {
                "type": "source",
                "title": _("Source Document"),
                "subtitle": move.origin,
                "name": move.origin,
                "res_model": False,
                "res_id": False,
            }
        return {}

    def _document_node(self, node_type, record, title):
        return {
            "type": node_type,
            "title": title,
            "subtitle": record.display_name,
            "name": record.display_name,
            "res_model": record._name,
            "res_id": record.id,
        }

    def _build_chain(self, move, data, source):
        """Build a dynamic list of chain nodes from the records that exist."""
        nodes = [
            {
                "type": "stock_before",
                "title": _("Stock Before"),
                "subtitle": _("Qty: %s") % data["stock_before"],
                "qty": data["stock_before"],
                "res_model": False,
                "res_id": False,
            },
            {
                "type": "stock_move",
                "title": _("Stock Movement"),
                "subtitle": self._move_label(move),
                "qty": data["movement_qty"],
                "balance_from": data["stock_before"],
                "balance_to": data["stock_after"],
                "res_model": "stock.move",
                "res_id": move.id,
            },
        ]
        if move.picking_id and self._can_read(move.picking_id):
            nodes.append(
                {
                    "type": "picking",
                    "title": _("Picking"),
                    "subtitle": move.picking_id.display_name,
                    "res_model": "stock.picking",
                    "res_id": move.picking_id.id,
                }
            )
        if self._is_inventory_move(move) and not move.picking_id:
            nodes.append(
                {
                    "type": "inventory_adjustment",
                    "title": _("Inventory Adjustment"),
                    "subtitle": move.reference or move.display_name,
                    "res_model": "stock.move",
                    "res_id": move.id,
                }
            )
        if source:
            nodes.append(
                {
                    "type": source.get("type") or "source",
                    "title": source.get("title") or _("Source Document"),
                    "subtitle": source.get("subtitle") or source.get("name") or "",
                    "res_model": source.get("res_model") or False,
                    "res_id": source.get("res_id") or False,
                }
            )
        for related in self._related_moves(move):
            nodes.append(
                {
                    "type": "related_move",
                    "title": _("Related Stock Movement"),
                    "subtitle": self._move_label(related),
                    "qty": related.quantity,
                    "res_model": "stock.move",
                    "res_id": related.id,
                }
            )
        return nodes

    def _related_moves(self, move):
        """Collect standard related moves without assuming a business flow."""
        related = self.env["stock.move"]
        if "move_dest_ids" in move._fields:
            related |= move.move_dest_ids
        if "move_orig_ids" in move._fields:
            related |= move.move_orig_ids
        if "returned_move_ids" in move._fields:
            related |= move.returned_move_ids
        if "origin_returned_move_id" in move._fields and move.origin_returned_move_id:
            related |= move.origin_returned_move_id
        if move.picking_id:
            siblings = move.picking_id.move_ids.filtered(
                lambda rec: rec.state == "done" and rec.id != move.id
            )
            related |= siblings
        return related.filtered(lambda rec: rec.id != move.id)[:8]

    def _build_timeline(self, move_rows, move_map, trigger_index, location, rounding):
        """Return a limited surrounding timeline with running balances."""
        window = self._timeline_window()
        relevant = []
        for index, row in enumerate(move_rows):
            qty = self._signed_qty_from_row(row, location.id)
            if float_is_zero(qty, precision_rounding=rounding):
                continue
            relevant.append((index, row, qty))

        trigger_pos = next(
            (pos for pos, (index, _row, _qty) in enumerate(relevant) if index == trigger_index),
            0,
        )
        start = max(0, trigger_pos - window)
        end = min(len(relevant), trigger_pos + window + 1)
        slice_rows = relevant[start:end]

        balance = 0.0
        for _index, _row, qty in relevant[:start]:
            balance += qty

        rows = []
        for index, row, qty in slice_rows:
            move = move_map.get(row["id"]) or self.env["stock.move"].browse(row["id"])
            stock_before = balance
            balance += qty
            rows.append(
                {
                    "move_id": row["id"],
                    "date": row["date"]
                    if isinstance(row.get("date"), str)
                    else fields.Datetime.to_string(row.get("date")),
                    "operation": self._operation_label(move),
                    "reference": move.reference or move.picking_id.display_name or move.display_name,
                    "qty": qty,
                    "balance": balance,
                    "stock_before": stock_before,
                    "is_trigger": index == trigger_index,
                    "res_model": "stock.move",
                    "res_id": row["id"],
                    "picking_id": move.picking_id.id,
                }
            )
        return rows

    def _rebuild_analysis_payload(self):
        """Recompute chain and timeline when an older incident is opened."""
        for incident in self:
            move = incident.trigger_move_id
            if not move:
                continue
            move_rows = incident._search_location_move_rows(
                incident.product_id, incident.location_id, incident.company_id
            )
            rounding = incident.product_id.uom_id.rounding or 0.01
            trigger_index = next(
                (index for index, row in enumerate(move_rows) if row["id"] == move.id), 0
            )
            data = {
                "index": trigger_index,
                "stock_before": incident.stock_before,
                "stock_after": incident.stock_after,
                "movement_qty": incident.movement_qty,
            }
            source = incident._find_source_document(move)
            window = incident._timeline_window()
            nearby_ids = [
                row["id"]
                for row in move_rows[max(0, trigger_index - window) : trigger_index + window + 1]
            ]
            move_map = {rec.id: rec for rec in self.env["stock.move"].browse(nearby_ids)}
            move_map[move.id] = move
            incident.write(
                {
                    "chain_json": incident._build_chain(move, data, source),
                    "timeline_json": incident._build_timeline(
                        move_rows, move_map, trigger_index, incident.location_id, rounding
                    ),
                }
            )

    def _related_document_links(self):
        """Return clickable related records for the analysis panel."""
        self.ensure_one()
        links = []
        if self.trigger_move_id:
            links.append(
                {
                    "name": self.trigger_move_id.display_name,
                    "label": _("Stock Move"),
                    "res_model": "stock.move",
                    "res_id": self.trigger_move_id.id,
                }
            )
        if self.trigger_picking_id:
            links.append(
                {
                    "name": self.trigger_picking_id.display_name,
                    "label": _("Picking"),
                    "res_model": "stock.picking",
                    "res_id": self.trigger_picking_id.id,
                }
            )
        if self.origin_document_model and self.origin_document_res_id:
            links.append(
                {
                    "name": self.origin_document_name or self.origin_document_model,
                    "label": _("Source Document"),
                    "res_model": self.origin_document_model,
                    "res_id": self.origin_document_res_id,
                }
            )
        return links

    def _serialize_product_row(self, summary):
        return {
            "id": summary.id,
            "product_id": summary.product_id.id,
            "product_name": summary.product_id.display_name,
            "default_code": summary.product_id.default_code or "",
            "warehouse_id": summary.warehouse_id.id,
            "warehouse_name": summary.warehouse_id.display_name or "",
            "location_id": summary.location_id.id,
            "location_name": summary.location_id.complete_name,
            "company_id": summary.company_id.id,
            "current_qty": summary.current_qty,
            "lowest_qty": summary.lowest_qty,
            "incident_count": summary.incident_count,
            "last_negative_date": fields.Datetime.to_string(summary.last_negative_date)
            if summary.last_negative_date
            else False,
            "status": summary.status,
            "is_currently_negative": summary.current_qty < 0,
        }

    def _serialize_incident_row(self, incident):
        return {
            "id": incident.id,
            "name": incident.name,
            "incident_number": incident.incident_number,
            "stock_before": incident.stock_before,
            "stock_after": incident.stock_after,
            "movement_qty": incident.movement_qty,
            "negative_qty": incident.negative_qty,
            "incident_datetime": fields.Datetime.to_string(incident.incident_datetime)
            if incident.incident_datetime
            else False,
            "corrected_datetime": fields.Datetime.to_string(incident.corrected_datetime)
            if incident.corrected_datetime
            else False,
            "is_corrected": incident.is_corrected,
            "state": incident.state,
            "root_cause_type": incident.root_cause_type,
            "root_cause": dict(self._fields["root_cause_type"].selection).get(
                incident.root_cause_type, ""
            ),
            "trigger_move": incident.trigger_move_id.display_name or "",
            "picking": incident.trigger_picking_id.display_name or "",
        }

    def _warehouse_for_location(self, location):
        """Resolve the warehouse of a location using standard location fields."""
        if location.warehouse_id:
            return location.warehouse_id
        return self.env["stock.warehouse"].search(
            [("view_location_id", "parent_of", location.id)], limit=1
        )

    def _move_label(self, move):
        operation = self._operation_label(move)
        reference = move.reference or move.picking_id.name or move.display_name
        return "%s / %s" % (operation, reference)

    def _operation_label(self, move):
        if self._is_inventory_move(move):
            return _("Inventory Adjustment")
        code = move.picking_id.picking_type_code if move.picking_id else False
        labels = {
            "incoming": _("Receipt"),
            "outgoing": _("Delivery"),
            "internal": _("Internal Transfer"),
        }
        if code in labels:
            return labels[code]
        if move.picking_type_id:
            return move.picking_type_id.name
        return _("Stock Movement")

    def _movement_type_label(self):
        self.ensure_one()
        if self.trigger_move_id:
            return self._operation_label(self.trigger_move_id)
        return _("Stock Movement")

    def _explanation_insufficient(self, move, data):
        return _(
            "This movement consumed %(consumed)s units while the available "
            "stock balance was %(before)s, causing the inventory balance "
            "to become %(after)s."
        ) % {
            "consumed": abs(data["movement_qty"]),
            "before": data["stock_before"],
            "after": data["stock_after"],
        }

    def _explanation_reservation(self, move, data):
        return _(
            "The required quantity was not fully available or reserved before "
            "%(move)s was validated. Stock before the movement was %(before)s "
            "and the movement quantity was %(qty)s."
        ) % {
            "move": self._move_label(move),
            "before": data["stock_before"],
            "qty": data["movement_qty"],
        }

    def _explanation_timing(self, move, data, incoming):
        return _(
            "A stock-consuming movement (%(move)s) occurred before an expected "
            "stock-in movement (%(incoming)s). The balance changed from "
            "%(before)s to %(after)s."
        ) % {
            "move": self._move_label(move),
            "incoming": self._move_label(incoming),
            "before": data["stock_before"],
            "after": data["stock_after"],
        }

    def _explanation_transfer(self, move, data):
        return _(
            "An internal transfer (%(move)s) moved %(qty)s units from this "
            "location while the available balance was %(before)s, resulting "
            "in %(after)s."
        ) % {
            "move": self._move_label(move),
            "qty": abs(data["movement_qty"]),
            "before": data["stock_before"],
            "after": data["stock_after"],
        }

    def _explanation_inventory(self, move, data):
        return _(
            "The negative quantity originated from an inventory adjustment "
            "(%(move)s). The counted or adjusted quantity changed the balance "
            "from %(before)s to %(after)s."
        ) % {
            "move": self._move_label(move),
            "before": data["stock_before"],
            "after": data["stock_after"],
        }

    def _explanation_manual(self, move, data):
        return _(
            "The negative quantity was created by %(move)s, which is not linked "
            "to a standard picking. The balance changed from %(before)s to %(after)s. "
            "A more specific cause could not be determined."
        ) % {
            "move": self._move_label(move),
            "before": data["stock_before"],
            "after": data["stock_after"],
        }

    def _explanation_unknown(self, move, data):
        return _(
            "The system detected that %(move)s changed the balance from "
            "%(before)s to %(after)s, but there is not enough information "
            "to determine a more specific root cause."
        ) % {
            "move": self._move_label(move),
            "before": data["stock_before"],
            "after": data["stock_after"],
        }

    def _can_read(self, record):
        """Respect the user's access rights; skip documents they cannot read."""
        if not record:
            return False
        try:
            record.read(["display_name"])
            return True
        except Exception:
            return False

    def _action_open_record(self, res_model, res_id):
        if not res_model or not res_id:
            return False
        return {
            "type": "ir.actions.act_window",
            "res_model": res_model,
            "res_id": res_id,
            "view_mode": "form",
            "target": "current",
        }

    def _timeline_window(self):
        value = self.env["ir.config_parameter"].sudo().get_param(
            "sh_inventory_negative_stock_analyzer.timeline_window",
            default=str(TIMELINE_DEFAULT_WINDOW),
        )
        try:
            return max(1, int(value))
        except (TypeError, ValueError):
            return TIMELINE_DEFAULT_WINDOW

    def _auto_scan_enabled(self):
        return (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("sh_inventory_negative_stock_analyzer.auto_scan", "True")
            not in ("False", "false", "0")
        )
