from odoo.tests.common import TransactionCase
from unittest.mock import patch, MagicMock
from odoo.addons.amazon_connector.models.amazon_account import AmazonAccount
import time

class TestAmazonOrderPerf(TransactionCase):
    def setUp(self):
        super().setUp()

        self.patcher_commit = patch('odoo.sql_db.Cursor.commit', MagicMock())
        self.patcher_commit.start()
        self.addCleanup(self.patcher_commit.stop)

        self.currency_usd = self.env.ref('base.USD', raise_if_not_found=False)
        if not self.currency_usd:
            self.currency_usd = self.env['res.currency'].create({
                'name': 'USD',
                'symbol': '$',
            })

        self.marketplace = self.env['amazon.marketplace'].create({
            'name': 'Amazon US',
            'marketplace_id': 'ATVPDKIKX0DER',
            'region': 'na',
            'currency_id': self.currency_usd.id,
            'country_code': 'US',
        })

        self.account = self.env['amazon.account'].create({
            'name': 'Test Account Perf',
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

        # Create 100 products and listings
        for i in range(100):
            product = self.env['product.product'].create({
                'name': f'Perf Product {i}',
                'default_code': f'PERF-SKU-{i}',
            })
            self.env['amazon.product.listing'].create({
                'seller_sku': f'PERF-SKU-{i}',
                'account_id': self.account.id,
                'marketplace_id': self.marketplace.id,
                'product_id': product.id,
            })

    def test_sync_orders_perf(self):
        mock_orders = []
        mock_items = {}

        for i in range(100):
            order_id = f'123-1234567-0000{i:03d}'
            mock_orders.append({
                'AmazonOrderId': order_id,
                'PurchaseDate': '2023-01-01T12:00:00Z',
                'LastUpdateDate': '2023-01-01T13:00:00Z',
                'OrderStatus': 'Unshipped',
                'FulfillmentChannel': 'MFN',
                'OrderTotal': {'CurrencyCode': 'USD', 'Amount': '100.00'},
                'MarketplaceId': 'ATVPDKIKX0DER',
            })
            mock_items[order_id] = [
                {
                    'OrderItemId': f'987654321{i:03d}',
                    'ASIN': f'B00000{i:03d}',
                    'SellerSKU': f'PERF-SKU-{i}',
                    'Title': f'Perf Product {i}',
                    'QuantityOrdered': 1,
                    'ItemPrice': {'CurrencyCode': 'USD', 'Amount': '100.00'},
                }
            ]

        with patch('odoo.addons.amazon_connector.services.sp_api_client.OdooSPAPIClient') as MockClient, \
             patch('odoo.addons.amazon_connector.services.sp_api_orders.SPAPIOrders') as MockOrdersAPI:

            mock_client_instance = MockClient.return_value
            mock_orders_api_instance = MockOrdersAPI.return_value

            mock_orders_api_instance.get_orders_all.return_value = mock_orders
            mock_orders_api_instance.get_order_items_all.side_effect = lambda order_id: mock_items[order_id]

            start_time = time.time()
            with self.assertQueryCount(__any__=True) as qc:
                self.account._sync_orders()
            end_time = time.time()

            print(f"Sync orders (100 orders, 1 item each) took {end_time - start_time:.4f}s with {len(qc)} queries")
