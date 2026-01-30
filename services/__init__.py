# -*- coding: utf-8 -*-
"""
Amazon SP-API Services for Odoo 18

This package provides comprehensive integration with Amazon's Selling Partner API,
including authentication, rate limiting, request signing, and API-specific clients.
"""

from . import encryption
from . import sp_api_auth
from . import sp_api_client
from . import sp_api_products
from . import sp_api_orders
from . import sp_api_fba
from . import sp_api_feeds
from . import sp_api_reports
from . import sp_api_pricing

__all__ = [
    'encryption',
    'sp_api_auth',
    'sp_api_client',
    'sp_api_products',
    'sp_api_orders',
    'sp_api_fba',
    'sp_api_feeds',
    'sp_api_reports',
    'sp_api_pricing',
]
