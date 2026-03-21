from odoo.tests.common import TransactionCase
import time

class TestBenchmarkWizard(TransactionCase):
    def test_benchmark_compute_amazon_data(self):
        Account = self.env['amazon.account']
        Marketplace = self.env['amazon.marketplace']
        Product = self.env['product.template']
        Listing = self.env['amazon.product.listing']
        Wizard = self.env['amazon.fba.shipment.wizard']
        WizardLine = self.env['amazon.fba.shipment.wizard.line']

        account = Account.create({'name': 'Test Account'})
        marketplace = Marketplace.create({'name': 'Test MP', 'api_ref': 'TEST', 'region': 'na'})

        # We need to bypass the _test_connection or anything if account requires it
        # Assume it works.

        # Create 100 products and listings
        products = Product.create([{'name': f'Test Product {i}'} for i in range(100)])

        listings = []
        for i, product in enumerate(products):
            listings.append({
                'name': f'Listing {i}',
                'product_tmpl_id': product.id,
                'account_id': account.id,
                'marketplace_id': marketplace.id,
                'fulfillment_channel': 'AFN',
                'seller_sku': f'SKU_{i}',
                'asin': f'ASIN_{i}',
                'fnsku': f'FNSKU_{i}',
            })
        Listing.create(listings)

        wizard = Wizard.create({
            'account_id': account.id,
            'marketplace_id': marketplace.id,
        })

        lines_data = [{
            'wizard_id': wizard.id,
            'product_id': p.id,
            'quantity': 1,
        } for p in products]

        # Time the line creation which triggers the compute
        start_time = time.time()

        # Reset query count to measure just the creation
        query_count_start = self.env.cr.sql_log_count

        lines = WizardLine.create(lines_data)

        # Force computation if needed
        for line in lines:
            _ = line.seller_sku

        query_count_end = self.env.cr.sql_log_count
        end_time = time.time()

        elapsed = end_time - start_time
        queries = query_count_end - query_count_start

        print(f"\n==========================================")
        print(f"BENCHMARK RESULTS")
        print(f"Time elapsed: {elapsed:.4f} seconds")
        print(f"Total queries: {queries}")
        print(f"==========================================\n")

        self.assertTrue(True)
