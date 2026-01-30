# -*- coding: utf-8 -*-
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta

from odoo.tests.common import TransactionCase
from odoo.addons.amazon_connector.models.amazon_account import AmazonAccount

class TestAmazonOrderSync(TransactionCase):

    def setUp(self):
        super().setUp()

        # Patch commit to avoid breaking test transaction
        self.patcher_commit = patch('odoo.sql_db.Cursor.commit', MagicMock())
        self.patcher_commit.start()
        self.addCleanup(self.patcher_commit.stop)

        # Create a currency if needed (USD usually exists in demo data or base)
        self.currency_usd = self.env.ref('base.USD', raise_if_not_found=False)
        if not self.currency_usd:
            self.currency_usd = self.env['res.currency'].create({
                'name': 'USD',
                'symbol': '$',
            })

        # Create Marketplace
        self.marketplace = self.env['amazon.marketplace'].create({
            'name': 'Amazon US',
            'marketplace_id': 'ATVPDKIKX0DER',
            'region': 'na',
            'currency_id': self.currency_usd.id,
            'country_code': 'US',
        })

        # Create Account
        self.account = self.env['amazon.account'].create({
            'name': 'Test Account',
            'company_id': self.env.company.id,
            'seller_id': 'TEST_SELLER_ID',
            'marketplace_ids': [(6, 0, [self.marketplace.id])],
            'default_marketplace_id': self.marketplace.id,
            'lwa_client_id': 'test_client_id',
            'lwa_client_secret': 'test_secret',
            'refresh_token': 'test_refresh_token',
            'aws_access_key': 'test_access_key',
            'aws_secret_key': 'test_secret_key',
            'environment': 'sandbox',
            'active': True,
        })

    def test_sync_orders_success(self):
        """Test successful order synchronization."""

        # Mock data
        mock_orders = [{
            'AmazonOrderId': '123-1234567-1234567',
            'PurchaseDate': '2023-01-01T12:00:00Z',
            'LastUpdateDate': '2023-01-01T13:00:00Z',
            'OrderStatus': 'Unshipped',
            'FulfillmentChannel': 'MFN',
            'OrderTotal': {'CurrencyCode': 'USD', 'Amount': '100.00'},
            'BuyerInfo': {
                'BuyerEmail': 'buyer@example.com',
                'BuyerName': 'Test Buyer'
            },
            'MarketplaceId': 'ATVPDKIKX0DER',
        }]

        mock_items = [{
            'OrderItemId': '987654321',
            'ASIN': 'B000000000',
            'SellerSKU': 'TEST-SKU',
            'Title': 'Test Product',
            'QuantityOrdered': 1,
            'ItemPrice': {'CurrencyCode': 'USD', 'Amount': '100.00'},
        }]

        # Patch the Client and Orders API
        # We patch where the class is defined
        with patch('odoo.addons.amazon_connector.services.sp_api_client.OdooSPAPIClient') as MockClient, \
             patch('odoo.addons.amazon_connector.services.sp_api_orders.SPAPIOrders') as MockOrdersAPI:

            # Setup mock instances
            mock_client_instance = MockClient.return_value
            mock_orders_api_instance = MockOrdersAPI.return_value

            mock_orders_api_instance.get_orders_all.return_value = mock_orders
            mock_orders_api_instance.get_order_items_all.return_value = mock_items

            # Run sync
            self.account._sync_orders()

            # Verify API calls
            MockClient.assert_called_once()
            MockOrdersAPI.assert_called_once_with(mock_client_instance)
            mock_orders_api_instance.get_orders_all.assert_called_once()
            mock_orders_api_instance.get_order_items_all.assert_called_once_with('123-1234567-1234567')

            # Verify Order Created
            order = self.env['amazon.order'].search([
                ('amazon_order_id', '=', '123-1234567-1234567')
            ])
            self.assertTrue(order, "Order should be created")
            self.assertEqual(order.order_status, 'unshipped')
            self.assertEqual(order.order_total, 100.00)
            self.assertEqual(order.buyer_email, 'buyer@example.com')

            # Verify Order Lines Created
            line = self.env['amazon.order.line'].search([
                ('order_id', '=', order.id)
            ])
            self.assertTrue(line, "Order line should be created")
            self.assertEqual(line.order_item_id, '987654321')
            self.assertEqual(line.item_price, 100.00)
            self.assertEqual(line.seller_sku, 'TEST-SKU')

            # Verify Log
            log = self.env['amazon.sync.log'].search([
                ('account_id', '=', self.account.id),
                ('operation', '=', 'order_sync')
            ], limit=1, order='id desc')
            self.assertEqual(log.status, 'success')
            self.assertEqual(log.record_count, 1)

    def test_sync_orders_failure(self):
        """Test partial failure in order synchronization."""

        mock_orders = [
            {'AmazonOrderId': 'ORDER-1', 'MarketplaceId': 'ATVPDKIKX0DER'}, # Good order
            {'AmazonOrderId': 'ORDER-2', 'MarketplaceId': 'ATVPDKIKX0DER'}, # Bad order
        ]

        # Patch to simulate error on second order
        with patch('odoo.addons.amazon_connector.services.sp_api_client.OdooSPAPIClient') as MockClient, \
             patch('odoo.addons.amazon_connector.services.sp_api_orders.SPAPIOrders') as MockOrdersAPI:

            mock_orders_api = MockOrdersAPI.return_value
            mock_orders_api.get_orders_all.return_value = mock_orders

            # Mock get_order_items_all to raise exception for second order
            def side_effect(order_id):
                if order_id == 'ORDER-2':
                    raise Exception("API Error")
                return []

            mock_orders_api.get_order_items_all.side_effect = side_effect

            # Run sync
            self.account._sync_orders()

            # Verify first order created
            order1 = self.env['amazon.order'].search([('amazon_order_id', '=', 'ORDER-1')])
            self.assertTrue(order1)

            # Verify Log
            log = self.env['amazon.sync.log'].search([
                ('account_id', '=', self.account.id),
                ('operation', '=', 'order_sync')
            ], limit=1, order='id desc')

            self.assertEqual(log.status, 'warning')
            self.assertEqual(log.error_count, 1)
            self.assertEqual(log.record_count, 1)
