# -*- coding: utf-8 -*-
# Part of Odoo 18 Amazon Connector
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0)

# Core Amazon models
from . import amazon_marketplace
from . import amazon_account
from . import amazon_credential
from . import amazon_product
from . import amazon_product_category
from . import amazon_order
from . import amazon_order_line
from . import amazon_return
from . import amazon_sync_log

# FBA models
from . import amazon_fba_shipment
from . import amazon_fba_shipment_item
from . import amazon_fba_inventory

# Inventory models
from . import amazon_inventory_sync

# Predictive Inventory Intelligence models
from . import amazon_demand_history
from . import amazon_inventory_forecast
from . import amazon_restock_suggestion

# Dashboard helpers
from . import amazon_dashboard

# Financial models
from . import amazon_settlement
from . import amazon_settlement_line
from . import amazon_fee

# Pricing Intelligence
from . import amazon_pricing_intelligence

# Odoo model extensions
from . import product_template
from . import sale_order
from . import stock_warehouse
from . import account_move
