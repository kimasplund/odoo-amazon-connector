import time
import logging

def run_benchmark(env):
    # Setup test data
    Account = env['amazon.account']
    Marketplace = env['amazon.marketplace']
    Product = env['product.template']
    Listing = env['amazon.product.listing']
    Wizard = env['amazon.fba.shipment.wizard']
    WizardLine = env['amazon.fba.shipment.wizard.line']

    # Create account and marketplace
    account = Account.create({'name': 'Test Account'})
    marketplace = Marketplace.create({'name': 'Test MP', 'api_ref': 'TEST', 'region': 'na'})

    # Create 100 products and listings
    products = Product.create([{'name': f'Test Product {i}'} for i in range(100)])

    for i, product in enumerate(products):
        Listing.create({
            'name': f'Listing {i}',
            'product_tmpl_id': product.id,
            'account_id': account.id,
            'marketplace_id': marketplace.id,
            'fulfillment_channel': 'AFN',
            'seller_sku': f'SKU_{i}',
            'asin': f'ASIN_{i}',
            'fnsku': f'FNSKU_{i}',
        })

    wizard = Wizard.create({
        'account_id': account.id,
        'marketplace_id': marketplace.id,
    })

    # Create lines without triggering compute (by using raw create or taking advantage of context)
    # Actually, create will trigger compute, let's time the create. Or create them and then recompute.

    lines_data = [{
        'wizard_id': wizard.id,
        'product_id': p.id,
        'quantity': 1,
    } for p in products]

    start_time = time.time()

    # This will trigger the compute method for each line
    lines = WizardLine.create(lines_data)

    end_time = time.time()
    elapsed = end_time - start_time

    print(f"Time taken to create 100 lines (triggering compute): {elapsed:.4f} seconds")

    # Count queries if possible?
    # We can use env.cr.sql_log_count or similar if in Odoo tests
