# -*- coding: utf-8 -*-

from datetime import timedelta

from odoo import fields
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestNegativeStockAnalyzer(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Incident = cls.env["inventory.negative.stock.incident"]
        cls.product = cls.env["product.product"].create(
            {
                "name": "NSA Test Product",
                "type": "consu",
                "is_storable": True,
                "uom_id": cls.env.ref("uom.product_uom_unit").id,
            }
        )
        cls.warehouse = cls.env["stock.warehouse"].search(
            [("company_id", "=", cls.env.company.id)], limit=1
        )
        cls.stock_location = cls.warehouse.lot_stock_id
        cls.supplier_location = cls.env.ref("stock.stock_location_suppliers")
        cls.customer_location = cls.env.ref("stock.stock_location_customers")
        cls.base_date = fields.Datetime.now() - timedelta(days=1)

    def _make_move(self, qty, location_from, location_to, hours=0):
        move = self.env["stock.move"].create(
            {
                "product_id": self.product.id,
                "product_uom_qty": abs(qty),
                "product_uom": self.product.uom_id.id,
                "location_id": location_from.id,
                "location_dest_id": location_to.id,
                "company_id": self.env.company.id,
            }
        )
        move._action_confirm()
        move.quantity = abs(qty)
        move.picked = True
        move._action_done()
        move.date = self.base_date + timedelta(hours=hours)
        return move

    def test_detect_negative_creating_movement(self):
        """The scanner identifies the first move that crosses from >= 0 to < 0."""
        self._make_move(20, self.supplier_location, self.stock_location, hours=0)
        self._make_move(10, self.stock_location, self.customer_location, hours=1)
        self._make_move(10, self.stock_location, self.customer_location, hours=2)
        trigger = self._make_move(10, self.stock_location, self.customer_location, hours=3)

        result = self.Incident.scan_negative_stock(
            {
                "product_id": self.product.id,
                "location_id": self.stock_location.id,
                "company_id": self.env.company.id,
                "include_historical": True,
            }
        )
        self.assertGreaterEqual(result["created"], 1)

        incident = self.Incident.search(
            [
                ("product_id", "=", self.product.id),
                ("location_id", "=", self.stock_location.id),
            ],
            limit=1,
        )
        self.assertTrue(incident)
        self.assertEqual(incident.trigger_move_id, trigger)
        self.assertEqual(incident.stock_before, 0.0)
        self.assertEqual(incident.stock_after, -10.0)
        self.assertEqual(incident.movement_qty, -10.0)
        self.assertFalse(incident.is_corrected)
        self.assertEqual(incident.state, "active")
        self.assertTrue(incident.chain_json)
        self.assertTrue(incident.timeline_json)

    def test_historical_incident_is_marked_corrected(self):
        """A later receipt that restores the balance marks the incident as corrected."""
        self._make_move(5, self.supplier_location, self.stock_location, hours=0)
        self._make_move(10, self.stock_location, self.customer_location, hours=1)
        self._make_move(10, self.supplier_location, self.stock_location, hours=2)

        self.Incident.scan_negative_stock(
            {
                "product_id": self.product.id,
                "location_id": self.stock_location.id,
                "company_id": self.env.company.id,
                "include_historical": True,
            }
        )
        incident = self.Incident.search(
            [
                ("product_id", "=", self.product.id),
                ("location_id", "=", self.stock_location.id),
            ],
            limit=1,
        )
        self.assertTrue(incident.is_corrected)
        self.assertEqual(incident.state, "corrected")
        self.assertEqual(incident.stock_before, 5.0)
        self.assertEqual(incident.stock_after, -5.0)

    def test_dashboard_payload_is_limited(self):
        """Frontend helpers return only the selected product and incident payload."""
        self._make_move(1, self.stock_location, self.customer_location, hours=0)
        self.Incident.scan_negative_stock(
            {
                "product_id": self.product.id,
                "include_historical": True,
                "company_id": self.env.company.id,
            }
        )
        products = self.Incident.get_dashboard_products(
            {"product_id": self.product.id, "company_id": self.env.company.id}
        )
        self.assertTrue(products)
        analysis = self.Incident.get_product_analysis(products[0]["id"])
        self.assertEqual(analysis["product"]["product_id"], self.product.id)
        incident_id = analysis["locations"][0]["incidents"][0]["id"]
        detail = self.Incident.get_incident_analysis(incident_id)
        self.assertIn("chain", detail)
        self.assertIn("timeline", detail)
        self.assertIn("history_action", detail)
