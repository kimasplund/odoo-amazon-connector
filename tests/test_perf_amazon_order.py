# -*- coding: utf-8 -*-
import time
import logging
from unittest.mock import patch
from odoo.tests.common import TransactionCase

_logger = logging.getLogger(__name__)

class TestAmazonOrderPerf(TransactionCase):

    def setUp(self):
        super().setUp()
        self.marketplace = self.env['amazon.marketplace'].create({
            'name': 'Amazon US',
            'marketplace_id': 'ATVPDKIKX0DER',
            'region': 'na',
            'currency_id': self.env.ref('base.USD').id,
            'country_code': 'US',
        })
        self.account = self.env['amazon.account'].create({
            'name': 'Test Account',
            'company_id': self.env.company.id,
            'seller_id': 'TEST_SELLER_ID',
            'marketplace_ids': [(6, 0, [self.marketplace.id])],
            'default_marketplace_id': self.marketplace.id,
            'environment': 'sandbox',
        })

    def test_create_from_spapi_optimization(self):
        """Test that create_from_spapi uses order_cache and avoids search."""

        # Create an existing order
        existing_order = self.env['amazon.order'].create({
            'amazon_order_id': 'TEST-ORDER-EXISTING',
            'account_id': self.account.id,
            'purchase_date': '2023-01-01',
            'order_status': 'unshipped',
            'fulfillment_channel': 'MFN',
            'currency_id': self.env.ref('base.USD').id,
            'marketplace_id': self.marketplace.id,
        })

        # Data for existing order
        data_existing = {
            'AmazonOrderId': 'TEST-ORDER-EXISTING',
            'PurchaseDate': '2023-01-01T12:00:00Z',
            'LastUpdateDate': '2023-01-01T13:00:00Z',
            'OrderStatus': 'Shipped',
            'MarketplaceId': 'ATVPDKIKX0DER',
            'OrderTotal': {'CurrencyCode': 'USD', 'Amount': '120.00'},
        }

        # Data for NEW order
        data_new = {
            'AmazonOrderId': 'TEST-ORDER-NEW',
            'PurchaseDate': '2023-01-02T12:00:00Z',
            'OrderStatus': 'Unshipped',
            'MarketplaceId': 'ATVPDKIKX0DER',
            'OrderTotal': {'CurrencyCode': 'USD', 'Amount': '50.00'},
        }

        # Cache with existing order only
        order_cache = {'TEST-ORDER-EXISTING': existing_order}

        # 1. Test UPDATE with cache
        # We expect NO search for 'TEST-ORDER-EXISTING'
        with patch.object(type(self.env['amazon.order']), 'search', side_effect=self.env['amazon.order'].search) as mock_search:
            self.env['amazon.order'].create_from_spapi(self.account, data_existing, order_cache=order_cache)

            # Verify update
            self.assertEqual(existing_order.order_status, 'shipped')

            # Check for specific search call
            calls = [c for c in mock_search.call_args_list if c[0] and isinstance(c[0][0], list) and
                     any(term[0] == 'amazon_order_id' and term[2] == 'TEST-ORDER-EXISTING' for term in c[0][0])]
            self.assertEqual(len(calls), 0, "Should not search for existing order when in cache")

        # 2. Test CREATE with cache (cache miss)
        # We expect NO search for 'TEST-ORDER-NEW' because we trust the cache (it's not in cache -> create)
        with patch.object(type(self.env['amazon.order']), 'search', side_effect=self.env['amazon.order'].search) as mock_search:
            new_order = self.env['amazon.order'].create_from_spapi(self.account, data_new, order_cache=order_cache)

            # Verify creation
            self.assertTrue(new_order)
            self.assertEqual(new_order.amazon_order_id, 'TEST-ORDER-NEW')

            # Check for specific search call
            calls = [c for c in mock_search.call_args_list if c[0] and isinstance(c[0][0], list) and
                     any(term[0] == 'amazon_order_id' and term[2] == 'TEST-ORDER-NEW' for term in c[0][0])]
            self.assertEqual(len(calls), 0, "Should not search for new order when cache is provided")
