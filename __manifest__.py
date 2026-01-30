# -*- coding: utf-8 -*-
# Part of Odoo 18 Amazon Connector
# Copyright 2025 - All Rights Reserved
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0)

{
    'name': 'Amazon Connector',
    'version': '18.0.1.0.0',
    'category': 'Sales/Sales',
    'summary': 'Full Amazon SP-API Integration for Odoo 18',
    'description': """
Amazon Connector for Odoo 18
============================

Enterprise-grade Amazon Selling Partner API (SP-API) integration providing:

**Product Management**
- Full product catalog synchronization
- ASIN/SKU mapping and variant support
- Category and browse node mapping
- A+ Content and Brand Registry support

**Inventory Management**
- Real-time inventory synchronization
- Multi-warehouse and FBA support
- Safety stock and replenishment alerts

**FBA Integration**
- Inbound shipment creation and tracking
- FBA fee calculation and monitoring
- Multi-channel fulfillment (MCF)

**Order Management**
- Automatic order import (FBA & FBM)
- Order status and tracking sync
- Returns and refunds processing

**Financial**
- Settlement report import
- Fee reconciliation
- VAT calculation (EU compliance)

**Supported Marketplaces**
- Europe: DE, UK, FR, IT, ES, NL, SE, PL, BE
- Americas: US, CA, MX, BR
- Asia-Pacific: JP, AU, IN
- Middle East: UAE, SA, TR
    """,
    'author': 'Amazon Connector Team',
    'website': 'https://github.com/odoo-amazon-connector',
    'license': 'LGPL-3',
    'depends': [
        # Core Odoo modules
        'base',
        'sale_management',
        'stock',
        'product',
        'account',
        'delivery',
        'sale_stock',
        # Optional: OCA queue_job for background processing
        # 'queue_job',
    ],
    'external_dependencies': {
        'python': [
            'requests',
            'cryptography',
            'python-dateutil',
        ],
    },
    'data': [
        # Security (load first)
        'security/amazon_security.xml',
        'security/ir.model.access.csv',
        # Data
        'data/amazon_marketplace_data.xml',
        'data/amazon_cron_data.xml',
        'data/amazon_pricing_cron_data.xml',
        'data/mail_template_data.xml',
        # Views
        'views/amazon_marketplace_views.xml',
        'views/amazon_account_views.xml',
        'views/amazon_product_views.xml',
        'views/amazon_order_views.xml',
        'views/amazon_fba_views.xml',
        'views/amazon_inventory_views.xml',
        'views/amazon_forecast_views.xml',
        'views/amazon_settlement_views.xml',
        'views/amazon_pricing_views.xml',
        'views/amazon_dashboard.xml',
        'views/product_template_views.xml',
        'views/sale_order_views.xml',
        'views/menus.xml',
        # Wizard Views
        'views/wizard_views.xml',
    ],
    'demo': [
        'demo/amazon_demo_data.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'amazon_connector/static/src/css/amazon_dashboard.css',
            'amazon_connector/static/src/js/amazon_dashboard.js',
            'amazon_connector/static/src/xml/amazon_dashboard.xml',
        ],
    },
    'images': [
        'static/description/banner.png',
        'static/description/icon.png',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
    'sequence': 10,
    'post_init_hook': 'post_init_hook',
    'uninstall_hook': 'uninstall_hook',
}
