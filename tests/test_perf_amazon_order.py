from odoo.tests.common import TransactionCase
import time

class TestAmazonOrderSyncPerf(TransactionCase):

    def setUp(self):
        super().setUp()

        # Setup account
        self.account = self.env['amazon.account'].create({
            'name': 'Test Account',
        })

        # Create wizard
        self.wizard = self.env['amazon.order.sync.wizard'].create({
            'account_id': self.account.id,
            'create_sale_orders': True,
        })

        self.amazon_order = self.env['amazon.order'].create({
            'amazon_order_id': 'TEST-ORDER-PERF',
            'account_id': self.account.id,
        })

        # Create 100 order lines with distinct SKUs
        for i in range(100):
            self.env['amazon.order.line'].create({
                'order_id': self.amazon_order.id,
                'seller_sku': f'PERF-SKU-{i}',
                'title': f'Perf Product {i}',
                'quantity': 1,
                'item_price': 10.0,
            })

    def test_performance_create_sale_order(self):
        # Time the method under test
        start_time = time.time()

        self.wizard._create_sale_order(self.amazon_order)

        end_time = time.time()
        duration = end_time - start_time
        print(f"\n[PERFORMANCE] _create_sale_order for 100 lines took {duration:.4f} seconds\n")
