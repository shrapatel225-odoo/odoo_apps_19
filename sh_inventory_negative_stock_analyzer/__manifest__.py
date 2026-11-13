# -*- coding: utf-8 -*-
{
    "name": "Inventory Negative Stock Root Cause Analyzer",
    "author": "Donika Enterprise",
    "support": "shra.patel225@gmail.com",
    "category": "Warehouse",
    "summary": (
        "Negative Stock Analyzer Inventory Root Cause Negative Quantity "
        "Stock Movement History Why Negative Stock Delivery Shortage "
        "Warehouse Negative Inventory Timeline Stock Balance Crossing "
        "Odoo Inventory Reporting"
    ),
    "version": "19.0.1.0.0",
    "depends": [
        "stock",
        "mail",
    ],
    "application": True,
    "data": [
        "security/sh_nsa_security.xml",
        "security/ir.model.access.csv",
        "data/ir_sequence_data.xml",
        "data/ir_cron_data.xml",
        "views/inventory_negative_stock_incident_views.xml",
        "views/inventory_negative_stock_product_views.xml",
        "views/res_config_settings_views.xml",
        "views/sh_nsa_menus.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "sh_inventory_negative_stock_analyzer/static/src/scss/negative_stock_analyzer.scss",
            "sh_inventory_negative_stock_analyzer/static/src/js/root_cause_chain.js",
            "sh_inventory_negative_stock_analyzer/static/src/js/negative_stock_analyzer.js",
            "sh_inventory_negative_stock_analyzer/static/src/xml/root_cause_chain.xml",
            "sh_inventory_negative_stock_analyzer/static/src/xml/negative_stock_analyzer.xml",
        ],
    },
    "images": ["static/description/banner.png"],
    "license": "OPL-1",
    "price": 159,
    "currency": "EUR",
    "auto_install": False,
    "installable": True,
}
